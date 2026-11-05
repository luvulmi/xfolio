"""T08 만료 경계·복원 gate·명시 실행/비밀 비노출. 외부 연결 없이 SQLite 사용."""

import json
from datetime import UTC, datetime, timedelta
from runpy import run_path
from types import SimpleNamespace

import pytest
import sqlalchemy as sa

from tests.support.paths import ROOT

DEPLOY = ROOT / "deploy" / "newsletter"
TOOLS = run_path(str(DEPLOY / "maintenance.py"))
NOW = datetime(2026, 11, 4, 13, 30, tzinfo=UTC)


def database(*, missing=None):
    engine = sa.create_engine("sqlite://")
    metadata = sa.MetaData()
    for name in TOOLS["RETENTION"]:
        if name != missing:
            sa.Table(
                name,
                metadata,
                sa.Column("id", sa.Integer, primary_key=True),
                sa.Column("expires_at", sa.DateTime(timezone=True)),
            )
    for name in TOOLS["LEGACY_PAYLOAD_TABLES"]:
        sa.Table(name, metadata, sa.Column("id", sa.Integer, primary_key=True))
    if missing != "operations_events":
        sa.Table(
            "operations_events",
            metadata,
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("kind", sa.String),
            sa.Column("expires_at", sa.DateTime(timezone=True)),
        )
    metadata.create_all(engine)
    return engine, metadata


def test_plan_does_not_create_engine_or_read_secret(monkeypatch, capsys):
    monkeypatch.setenv("XFOLIO_MAINTENANCE_DATABASE_URL", "secret:not-a-database")
    assert TOOLS["main"](["plan"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["database_accessed"] is False
    assert data["retention_days"]["telegram_outbox"] == 365
    assert data["retention_days"]["newsletter_editions"] == 90
    assert data["operations_event_retention_days"] == {"newsletter_prepare": 90}
    assert "secret" not in json.dumps(data)


def test_purge_requires_explicit_execute_before_database(monkeypatch, capsys):
    monkeypatch.setenv("XFOLIO_MAINTENANCE_DATABASE_URL", "secret:password")
    assert TOOLS["main"](["purge"]) == 1
    assert json.loads(capsys.readouterr().out) == {"error": "purge_requires_execute"}


@pytest.mark.parametrize(
    ("value", "error"),
    [
        ("", "explicit_maintenance_database_required"),
        ("sqlite://", "maintenance_database_invalid"),
        (
            "postgresql://user:DO_NOT_PRINT@db.example/restore?sslmode=require",
            "remote_database_tls_verification_required",
        ),
        ("malformedDO_NOT_PRINT", "maintenance_database_invalid"),
    ],
)
def test_invalid_database_and_tls_do_not_disclose_values(
    value, error, monkeypatch, capsys
):
    monkeypatch.setenv("XFOLIO_MAINTENANCE_DATABASE_URL", value)
    assert TOOLS["main"](["verify"]) == 1
    assert json.loads(capsys.readouterr().out) == {"error": error}


def test_restore_gate_detects_expiry_at_exact_boundary_and_legacy_data():
    engine, metadata = database()
    table = metadata.tables["newsletter_editions"]
    with engine.begin() as conn:
        conn.execute(
            table.insert(),
            [
                {"id": 1, "expires_at": NOW},
                {"id": 2, "expires_at": NOW + timedelta(microseconds=1)},
            ],
        )
    result = TOOLS["verify"](engine, now=NOW)
    assert result["expired_rows"]["newsletter_editions"] == 1
    assert result["can_resume"] is False
    with engine.begin() as conn:
        conn.execute(table.delete().where(table.c.id == 1))
    assert TOOLS["verify"](engine, now=NOW)["can_resume"] is True
    with engine.begin() as conn:
        conn.execute(metadata.tables["content_drafts"].insert().values(id=1))
    result = TOOLS["verify"](engine, now=NOW)
    assert result["can_resume"] is False
    assert result["legacy_payload_rows"]["content_drafts"] == 1


@pytest.mark.parametrize("missing", ["telegram_outbox", "operations_events"])
def test_missing_new_schema_cannot_pass_restore_gate(missing):
    engine, _ = database(missing=missing)
    with pytest.raises(TOOLS["MaintenanceError"], match="newsletter_schema_incomplete"):
        TOOLS["verify"](engine, now=NOW)


def test_naive_time_is_rejected():
    with pytest.raises(TOOLS["MaintenanceError"], match="aware_time_required"):
        TOOLS["utc_now"](NOW.replace(tzinfo=None))


def test_purge_calls_owned_services_then_requires_clean_restore_gate(monkeypatch):
    engine, metadata = database()
    for name in TOOLS["RETENTION"]:
        with engine.begin() as conn:
            conn.execute(metadata.tables[name].insert().values(id=1, expires_at=NOW))
    called = []
    names = list(TOOLS["RETENTION"])
    service_tables = (
        names[:1],
        names[1:2],
        names[2:4],
        names[4:5],
        names[5:6],
        ("operations_events",),
    )
    with engine.begin() as conn:
        conn.execute(
            metadata.tables["operations_events"].insert(),
            [
                {"id": 1, "kind": "newsletter_prepare", "expires_at": NOW},
                {"id": 2, "kind": "auth_session", "expires_at": NOW},
            ],
        )
    assert (
        TOOLS["verify"](engine, now=NOW)["expired_rows"][
            "operations_events.newsletter_prepare"
        ]
        == 1
    )
    services = {}
    for (module, cls_name, method), tables in zip(TOOLS["STORES"], service_tables):

        def make_service(class_name, method_name, table_names):
            def run(self, *, now):
                called.append(class_name)
                count = 0
                with self.engine.begin() as conn:
                    for name in table_names:
                        table = metadata.tables[name]
                        condition = table.c.expires_at <= now
                        if name == "operations_events":
                            condition &= table.c.kind == "newsletter_prepare"
                        count += conn.execute(table.delete().where(condition)).rowcount
                return count

            def init(self, shared_engine):
                self.engine = shared_engine

            return type(class_name, (), {"__init__": init, method_name: run})

        services[module] = SimpleNamespace(
            **{cls_name: make_service(cls_name, method, tables)}
        )
    monkeypatch.setattr(
        TOOLS["importlib"], "import_module", lambda name: services[name]
    )
    result = TOOLS["purge"](engine, now=NOW)
    assert called == [cls_name for _, cls_name, _ in TOOLS["STORES"]]
    assert result["can_resume"] is True
    assert not any(result["expired_rows"].values())
    assert sum(result["deleted"].values()) == len(TOOLS["RETENTION"]) + 1
    with engine.connect() as conn:
        assert (
            conn.scalar(
                sa.select(sa.func.count()).select_from(
                    metadata.tables["operations_events"]
                )
            )
            == 1
        )
