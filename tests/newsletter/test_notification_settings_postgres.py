"""T05 격리PG: 공용 설정·감사·revision·원자 rollback과0006 이행."""

import os
import secrets
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from runpy import run_path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.schema import CreateTable

from tests.support.paths import ROOT
from xfolio.api.newsletter_admin import NewsletterAdminStore
from xfolio.db.domestic import watchlist
from xfolio.db.notification_settings import audit, settings
from xfolio.domestic.models import DomesticError
from xfolio.domestic.store import DomesticStore
from xfolio.newsletter.edition import MorningSettings
from xfolio.newsletter.settings import (
    NotificationSettingsError,
    NotificationSettingsStore,
)

NOW = datetime(2026, 11, 4, 13, 40, tzinfo=UTC)


@pytest.fixture
def db():
    url = os.environ.get("XFOLIO_TEST_DATABASE_URL")
    if not url:
        pytest.skip("explicit isolated PostgreSQL required")
    base = sa.create_engine(url, hide_parameters=True)
    schema = "xf_t05_" + secrets.token_hex(8)
    with base.begin() as conn:
        conn.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    engine = sa.create_engine(
        url, hide_parameters=True, connect_args={"options": f"-csearch_path={schema}"}
    )
    config = Config(str(ROOT / "alembic.ini"))
    try:
        with engine.begin() as conn:
            config.attributes["connection"] = conn
            command.upgrade(config, "head")
        DomesticStore(engine).bootstrap(NOW)
        yield engine, config
    finally:
        engine.dispose()
        with base.begin() as conn:
            conn.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        base.dispose()


def test_0006_defaults_fixed_ddl_and_downgrade_preserves_t02(db):
    engine, config = db
    service = NotificationSettingsStore(engine)
    assert service.get() == MorningSettings(revision=1)
    snapshot = run_path(str(ROOT / "migrations/schema_0006.py"))
    for name, table in (("settings", settings), ("audit", audit)):
        assert str(CreateTable(table).compile(dialect=engine.dialect)) == str(
            CreateTable(snapshot[name]).compile(dialect=engine.dialect)
        )
    with engine.begin() as conn:
        config.attributes["connection"] = conn
        command.downgrade(config, "0005_morning_newsletter")
        assert conn.scalar(sa.select(watchlist.c.revision)) == 1
        command.upgrade(config, "head")
    assert service.get().revision == 1


def test_settings_revision_audit_and_worker_transaction_read(db):
    engine, _ = db
    service = NotificationSettingsStore(engine)
    assert (
        service.update(
            expected_revision=1, changes={"paused": True}, actor="owner", now=NOW
        ).revision
        == 2
    )
    assert service.get().paused
    with engine.begin() as conn:
        assert service.get(conn=conn, for_update=True).revision == 2
        row = conn.execute(sa.select(audit)).mappings().one()
        assert row["before"]["paused"] is False and row["after"]["paused"] is True
        assert row["expires_at"] == NOW + timedelta(days=365)
    with pytest.raises(NotificationSettingsError, match="revision_conflict"):
        service.update(
            expected_revision=1, changes={"paused": False}, actor="owner", now=NOW
        )
    with pytest.raises(NotificationSettingsError, match="transaction_required"):
        service.get(for_update=True)


@pytest.mark.parametrize(
    "changes",
    [
        {"paused": "true"},
        {"paused": 1},
        {"token": "secret"},
        {},
        {"paused": None},
        {"intraday_enabled": True},
        {"close_enabled": True},
    ],
)
def test_invalid_settings_do_not_change_db(db, changes):
    engine, _ = db
    with pytest.raises(NotificationSettingsError):
        NotificationSettingsStore(engine).update(
            expected_revision=1, changes=changes, actor="owner", now=NOW
        )
    assert NotificationSettingsStore(engine).get().revision == 1


def test_audit_failure_rolls_back_settings_and_watchlist(db):
    engine, _ = db
    with pytest.raises(NotificationSettingsError, match="invalid_actor"):
        NotificationSettingsStore(engine).update(
            expected_revision=1, changes={"paused": True}, actor="", now=NOW
        )
    assert NotificationSettingsStore(engine).get().revision == 1
    original = DomesticStore(engine).watchlist()
    with pytest.raises(NotificationSettingsError, match="invalid_actor"):
        NewsletterAdminStore(engine).update_watchlist(
            expected_revision=1,
            codes=list(reversed(original["codes"])),
            actor="",
            now=NOW,
        )
    assert DomesticStore(engine).watchlist() == original


def test_concurrent_settings_only_one_revision_wins(db):
    engine, _ = db

    def attempt(_):
        try:
            return (
                NotificationSettingsStore(engine)
                .update(
                    expected_revision=1,
                    changes={"paused": True},
                    actor="owner",
                    now=NOW,
                )
                .revision
            )
        except NotificationSettingsError as exc:
            return str(exc)

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(map(str, pool.map(attempt, range(2)))) == [
            "2",
            "revision_conflict",
        ]


def test_watchlist_reuses_t02_validation_and_keeps_history(db):
    engine, _ = db
    admin = NewsletterAdminStore(engine)
    original = admin.get_watchlist()
    revised = admin.update_watchlist(
        expected_revision=original["revision"],
        codes=list(reversed(original["codes"])),
        actor="owner",
        now=NOW,
    )
    assert revised["revision"] == 2
    with pytest.raises(DomesticError, match="revision_conflict"):
        admin.update_watchlist(
            expected_revision=1, codes=original["codes"], actor="owner", now=NOW
        )
    with pytest.raises(DomesticError, match="active_limit_or_duplicate"):
        admin.update_watchlist(
            expected_revision=2, codes=["360750"] * 11, actor="owner", now=NOW
        )
    with engine.connect() as conn:
        assert conn.scalar(sa.select(sa.func.count()).select_from(audit)) == 1
    assert (
        NotificationSettingsStore(engine).purge_expired(now=NOW + timedelta(days=365))
        == 1
    )
    assert len(admin.get_watchlist()["items"]) == 3
