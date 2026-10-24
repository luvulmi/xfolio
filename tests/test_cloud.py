"""무통신 기본값·비밀 비노출·운영자 권한·원본 보존 경계를 검증한다."""

import json
import runpy
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import certifi
import pytest

from xfolio import cloud
from xfolio.demo import demo_preview
from xfolio.storage import PreviewStore, StorageError, configured_store

try:
    import psycopg

    from xfolio.postgres import PostgresPreviewStore
except ImportError:
    pytest.skip("클라우드 시험에는 cloud extra가 필요합니다.", allow_module_level=True)

NOW = datetime(2026, 10, 25, tzinfo=UTC)
URL = "postgresql://user:test-secret@db.example.invalid/db?sslmode=disable"
CLOUD_APP = Path(__file__).resolve().parents[1] / "dashboard" / "cloud_app.py"


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("클라우드 단위 시험에서 실제 DB 연결을 시도했습니다.")

    monkeypatch.setattr(psycopg, "connect", forbidden)
    monkeypatch.delenv("XFOLIO_DATABASE_URL", raising=False)


@pytest.fixture
def connection(monkeypatch):
    connection = MagicMock()
    connect = MagicMock()
    connect.return_value.__enter__.return_value = connection
    monkeypatch.setattr(psycopg, "connect", connect)
    return connection, connect


def test_remote_selection_never_falls_back_to_local_sqlite(monkeypatch):
    monkeypatch.setenv("XFOLIO_DATABASE_URL", URL)
    assert isinstance(configured_store(), PostgresPreviewStore)
    assert isinstance(configured_store(Path("explicit.sqlite3")), PreviewStore)
    monkeypatch.setattr(
        psycopg, "connect", MagicMock(side_effect=psycopg.OperationalError(URL))
    )
    with pytest.raises(StorageError) as error:
        configured_store().recent()
    assert "test-secret" not in str(error.value)
    assert "db.example" not in str(error.value)


def test_save_forces_tls_verification_and_rejects_publishable_data_before_connect(
    connection,
):
    conn, connect = connection
    store = PostgresPreviewStore(URL)
    invalid = demo_preview().model_copy(update={"can_publish": True})
    with pytest.raises(ValueError):
        store.save(invalid)
    connect.assert_not_called()
    conn.execute.return_value.rowcount = 1
    assert store.save(demo_preview())
    assert connect.call_args.kwargs["sslmode"] == "verify-full"
    assert connect.call_args.kwargs["sslrootcert"] == certifi.where()
    assert connect.call_args.kwargs["connect_timeout"] == 10
    query, values = conn.execute.call_args.args
    assert "test-secret" not in query
    assert values[0] == demo_preview().preview_id
    assert values[1].tzinfo is not None
    conn.execute.return_value.rowcount = 0
    assert not store.save(demo_preview())


def test_exact_version_readback_and_bad_limits(connection):
    conn, connect = connection
    store = PostgresPreviewStore(URL)
    preview = demo_preview()
    conn.execute.return_value.fetchone.return_value = (preview.model_dump_json(),)
    assert store.get(preview.preview_id) == preview
    conn.execute.return_value.fetchone.return_value = None
    assert store.get("missing") is None
    connect.reset_mock()
    with pytest.raises(ValueError):
        store.recent(101)
    connect.assert_not_called()


def test_sqlite_migration_preserves_source_and_checks_every_payload(
    tmp_path, connection
):
    conn, connect = connection
    source = tmp_path / "source.sqlite3"
    original = PreviewStore(source)
    original.save(demo_preview())
    original.save(demo_preview("zero"))
    before = source.read_bytes()
    conn.execute.return_value.rowcount = 1
    result = PostgresPreviewStore(URL).migrate_sqlite(source)
    assert result == {"source_rows": 2, "inserted": 2}
    assert source.read_bytes() == before
    inserts = [
        call for call in conn.execute.call_args_list if "INSERT INTO" in call.args[0]
    ]
    assert len(inserts) == 2
    # 1회 연결 안에서 복사하므로 psycopg context의 단일 트랜잭션을 사용한다.
    connect.assert_called_once()


def test_migration_missing_source_does_not_create_a_file_or_connect(tmp_path):
    source = tmp_path / "absent.sqlite3"
    with pytest.raises(StorageError):
        PostgresPreviewStore(URL).migrate_sqlite(source)
    assert not source.exists()


def test_cloud_dry_run_and_missing_settings_do_not_connect(capsys):
    cloud.main(["--initialize"])
    assert json.loads(capsys.readouterr().out)["database_requests"] == 0
    with pytest.raises(SystemExit) as error:
        cloud.main(["--run"])
    assert error.value.code == 2


def test_cloud_trial_reports_roundtrip_and_duplicate_only(monkeypatch, capsys):
    monkeypatch.setenv("XFOLIO_DATABASE_URL", URL)
    store = MagicMock()
    store.save.side_effect = [True, False]
    store.get.return_value = demo_preview()
    monkeypatch.setattr(cloud, "configured_store", lambda: store)
    cloud.main(["--run", "--initialize"])
    result = json.loads(capsys.readouterr().out)
    assert result["roundtrip"] and result["deduplicated"]
    assert result["synthetic"] and not result["can_publish"]
    assert datetime.fromisoformat(result["observed_at_utc"]).utcoffset() == timedelta(0)
    assert "test-secret" not in json.dumps(result)
    store.initialize.assert_called_once()


def test_cloud_failure_does_not_print_database_url(monkeypatch, capsys):
    monkeypatch.setenv("XFOLIO_DATABASE_URL", URL)
    store = MagicMock()
    store.save.side_effect = StorageError(URL)
    monkeypatch.setattr(cloud, "configured_store", lambda: store)
    with pytest.raises(SystemExit) as error:
        cloud.main(["--run"])
    assert error.value.code == 1
    output = capsys.readouterr()
    assert "test-secret" not in output.out + output.err


def claims(**changes):
    return {
        "iss": "https://accounts.google.com",
        "sub": "google-user-123",
        "email": "operator@example.com",
        "email_verified": True,
        "exp": (NOW + timedelta(hours=1)).timestamp(),
        **changes,
    }


@pytest.mark.parametrize(
    "changes",
    [
        {"iss": "https://attacker.example"},
        {"iss": []},
        {"sub": ""},
        {"email_verified": False},
        {"email_verified": "true"},
        {"email": "other@example.com"},
        {"exp": NOW.timestamp()},
        {"exp": None},
        {"exp": float("inf")},
    ],
)
def test_operator_rejects_wrong_issuer_unverified_unknown_or_expired(changes):
    assert not cloud.operator_allowed(
        claims(**changes), ["operator@example.com"], now=NOW
    )


def test_operator_allowlist_and_google_verified_claims():
    assert cloud.operator_allowed(claims(), [" OPERATOR@example.com "], now=NOW)
    assert not cloud.operator_allowed(claims(), [], now=NOW)


class Stopped(Exception):
    pass


def ui_stub(monkeypatch, secrets):
    st = MagicMock()
    st.secrets = secrets
    st.user.is_logged_in = False
    st.stop.side_effect = Stopped
    monkeypatch.setitem(sys.modules, "streamlit", st)
    return st


def test_cloud_dashboard_missing_settings_stops_before_database(monkeypatch):
    st = ui_stub(monkeypatch, {})
    with pytest.raises(Stopped):
        runpy.run_path(str(CLOUD_APP))
    st.error.assert_called_once()
    st.button.assert_not_called()


def test_cloud_dashboard_logged_out_does_not_read_database(monkeypatch):
    config = {
        "XFOLIO_DATABASE_URL": URL,
        "XFOLIO_ADMIN_EMAILS": ["operator@example.com"],
        "auth": {
            "client_id": "test-client",
            "client_secret": "test-client-secret",
            "cookie_secret": "test-cookie-secret",
            "server_metadata_url": "https://accounts.google.com/.well-known/openid-configuration",
        },
    }
    st = ui_stub(monkeypatch, config)
    st.button.return_value = False
    with pytest.raises(Stopped):
        runpy.run_path(str(CLOUD_APP))
    st.info.assert_called_once()
    st.button.assert_called_once()
