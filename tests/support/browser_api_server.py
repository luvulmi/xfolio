"""격리 PostgreSQL·모의 Google provider를 사용하는 HTTPS 브라우저 시험 서버.

제품 로그인 경로나 synthetic 차단을 바꾸지 않는다. 명시한 loopback 시험 DB만
사용하며, 테스트 전용 schema를 만들어 제품 API·세션·조회·보류를 실행한다.
"""

import hashlib
import ipaddress
import json
import os
import re
import secrets
import sys
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import sqlalchemy as sa
import uvicorn
from alembic import command
from alembic.config import Config
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from fastapi.staticfiles import StaticFiles
from sqlalchemy.engine import make_url

from xfolio.api.app import create_app
from xfolio.api.auth import Settings
from xfolio.api.store import PostgresStore
from xfolio.db.schema import content_drafts, evidence_bundles, publication_jobs

ROOT = Path(__file__).resolve().parents[2]
ORIGIN = "https://127.0.0.1:8447"
EMAIL = "browser-operator@example.invalid"
SCHEMA = "xfolio_browser_e2e_" + secrets.token_hex(4)
SCHEMA_RECORD = ROOT / ".cache" / "browser-e2e" / "run-schema.txt"
TEST_CLOCK = datetime.combine(
    datetime.now(ZoneInfo("Asia/Seoul")).date(), time(7, 35), ZoneInfo("Asia/Seoul")
).astimezone(UTC)


class GoogleProviderDouble:
    """외부 Google 요청만 대체한다. state/flow-cookie/session은 실제 API가 처리."""

    def __init__(self):
        self.codes = {}

    async def authorize(self, state, nonce):
        code = secrets.token_urlsafe(32)
        self.codes[code] = nonce
        return f"{ORIGIN}/api/auth/callback?{urlencode({'state': state, 'code': code})}"

    async def verify(self, code, nonce, now):
        expected_nonce = self.codes.pop(code, None)
        if not expected_nonce or not secrets.compare_digest(expected_nonce, nonce):
            raise ValueError("invalid_test_code")
        return {
            "iss": "https://accounts.google.com",
            "sub": "browser-test-operator",
            "email": EMAIL,
            "email_verified": True,
            "exp": (now + timedelta(minutes=5)).timestamp(),
            "name": "격리 PostgreSQL 브라우저 시험",
        }


def prepare_database():
    configured = os.environ.get("XFOLIO_BROWSER_TEST_DATABASE_URL", "")
    if not configured:
        raise ValueError("XFOLIO_BROWSER_TEST_DATABASE_URL is required")
    url = make_url(configured).set(drivername="postgresql+psycopg")
    if url.host not in {"127.0.0.1", "localhost", "::1"} or not url.database:
        raise ValueError("explicit loopback PostgreSQL test database required")
    # A fresh namespace keeps existing tables and parallel test schemas untouched.
    admin = sa.create_engine(url, hide_parameters=True)
    with admin.begin() as connection:
        connection.execute(sa.text(f"CREATE SCHEMA {SCHEMA}"))
    scoped_url = url.update_query_dict({"options": f"-csearch_path={SCHEMA}"})
    store = PostgresStore(scoped_url.render_as_string(hide_password=False))
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    try:
        with store.engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
    except Exception:
        store.engine.dispose()
        with admin.begin() as connection:
            connection.execute(sa.text(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE"))
        admin.dispose()
        raise
    return admin, store


def cleanup_recorded_schema():
    """Windows의 강제 프로세스 종료에도 Playwright teardown이 자기 schema를 정리."""
    if not SCHEMA_RECORD.exists():
        return
    schema = SCHEMA_RECORD.read_text(encoding="ascii").strip()
    if not re.fullmatch(r"xfolio_browser_e2e_[a-f0-9]{8}", schema):
        raise ValueError("invalid test schema record")
    configured = os.environ.get("XFOLIO_BROWSER_TEST_DATABASE_URL", "")
    url = make_url(configured).set(drivername="postgresql+psycopg")
    if url.host not in {"127.0.0.1", "localhost", "::1"} or not url.database:
        raise ValueError("explicit loopback PostgreSQL test database required")
    engine = sa.create_engine(url, hide_parameters=True)
    try:
        with engine.begin() as connection:
            connection.execute(sa.text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
        SCHEMA_RECORD.unlink(missing_ok=True)
    finally:
        engine.dispose()


def seed_synthetic(store):
    now = datetime.now(UTC)
    target_date = now.astimezone(ZoneInfo("Asia/Seoul")).date()
    payload = {
        "market_trade_date": target_date.isoformat(),
        "frozen_at": now.isoformat(),
        "validation": {"status": "passed", "blocking_reasons": []},
        "rights_verified": False,
        "collection_complete": True,
        "max_cost_krw": "0",
        "posts": [
            {
                "position": 1,
                "kind": "news",
                "text": "[가상] 실제 PostgreSQL 조회·보류 시험용 문안입니다.",
                "event_key": "browser-synthetic-event",
                "fact_version": "v1",
                "evidence_ids": ["browser-evidence"],
            }
        ],
    }
    digest = hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode()
    ).hexdigest()
    with store.engine.begin() as connection:
        connection.execute(
            evidence_bundles.insert().values(
                id="browser-evidence",
                source_id="synthetic-browser-source",
                content_version="fixture-v1",
                event_key="browser-synthetic-event",
                published_at=now - timedelta(hours=1),
                collected_at=now,
                rights_verified=False,
                payload={
                    "source": "Synthetic Browser Fixture",
                    "url": "https://example.invalid/browser-fixture",
                    "permitted_excerpt": "합성 자료이며 공개·AI 권한을 확인한 실자료가 아닙니다.",
                    "fact_version": "v1",
                    "claims": [],
                },
            )
        )
        connection.execute(
            content_drafts.insert().values(
                id="browser-draft-v1",
                edition_id="browser-pm",
                version=1,
                content_hash=digest,
                synthetic=True,
                validation_passed=True,
                payload=payload,
            )
        )
        connection.execute(
            publication_jobs.insert().values(
                id="browser-pm",
                account_id="synthetic-browser-account",
                target_date=target_date,
                edition="PM",
                draft_id="browser-draft-v1",
                status="validated",
                scheduled_at=now,
                expires_at=now + timedelta(minutes=10),
                payload={},
            )
        )


def seed_am_workflow(store):
    """실제 AM 저장/승인의 시험 전제. 공급자·AI·X 실제 호출은 없다."""
    sys.path.insert(0, str(ROOT / "tests"))
    import am_fixtures

    from xfolio.am_edition import save_am_edition

    am_fixtures.CUTOFF = (TEST_CLOCK - timedelta(minutes=5)).astimezone(
        ZoneInfo("Asia/Seoul")
    )
    am_fixtures.NOW = TEST_CLOCK
    save_am_edition(
        store.engine,
        am_fixtures.inputs(3),
        account_id="browser-am-fixture",
        now=TEST_CLOCK,
    )


def certificate():
    directory = ROOT / ".cache" / "browser-e2e"
    directory.mkdir(parents=True, exist_ok=True)
    key_file, cert_file = directory / "key.pem", directory / "cert.pem"
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "XFolio browser test")])
    now = datetime.now(UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName(
                [x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
            ),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    key_file.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    cert_file.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    return key_file, cert_file


def seed_newsletter_workflow(store):
    """T07: real stores/worker with test-only provider/AI/Telegram doubles."""
    sys.path.insert(0, str(ROOT / "tests"))
    from test_telegram_outbox_postgres import FakeLive
    from test_worker_collection_postgres import setup

    from xfolio.db.notification_settings import settings as notification_settings
    from xfolio.domestic.store import DomesticStore
    from xfolio.jobs.outbox import TelegramOutboxStore
    from xfolio.jobs.worker import MorningWorker
    from xfolio.newsletter import at
    from xfolio.newsletter_demo import demo_inputs
    from xfolio.newsletter_store import NewsletterStore

    data = demo_inputs()
    DomesticStore(store.engine).bootstrap(data.frozen_at - timedelta(days=1))
    with store.engine.begin() as conn:
        conn.execute(
            notification_settings.update().values(
                updated_at=data.frozen_at - timedelta(days=1)
            )
        )
    service, clock, _calls, _ai = setup((store.engine, data))
    prepared = service.prepare()
    if prepared["status"] != "ready":
        raise ValueError("newsletter_browser_seed_failed")
    clock[0] = at(data.target_date, 8)
    worker = MorningWorker(
        calendar=service.calendar,
        collect_inputs=None,
        preparation=service,
        newsletter_store=NewsletterStore(store.engine),
        outbox_store=TelegramOutboxStore(store.engine),
        transport=FakeLive(),
        clock=lambda: clock[0],
    )
    if worker.send()["status"] != "confirmed":
        raise ValueError("newsletter_browser_delivery_seed_failed")
    return at(data.target_date, 8, 1)


def main():
    if not (ROOT / "frontend" / "dist" / "index.html").exists():
        raise ValueError("run npm run build in frontend first")
    admin, store = prepare_database()
    try:
        clock = TEST_CLOCK
        if os.environ.get("XFOLIO_BROWSER_TEST_NEWSLETTER") == "true":
            clock = seed_newsletter_workflow(store)
        else:
            seed_synthetic(store)
            seed_am_workflow(store)
        settings = Settings(
            origin=ORIGIN,
            google_client_id="browser-provider-double",
            google_client_secret=secrets.token_urlsafe(32),
            allowed_emails=(EMAIL,),
            cursor_secret=secrets.token_urlsafe(32),
            mode="reviewed",
        )
        app = create_app(settings, store, GoogleProviderDouble(), clock=lambda: clock)
        app.mount("/", StaticFiles(directory=ROOT / "frontend" / "dist", html=True))
        key_file, cert_file = certificate()
        SCHEMA_RECORD.write_text(SCHEMA, encoding="ascii")
        uvicorn.run(
            app,
            host="127.0.0.1",
            port=8447,
            ssl_keyfile=str(key_file),
            ssl_certfile=str(cert_file),
            access_log=False,
        )
    finally:
        store.engine.dispose()
        with admin.begin() as connection:
            connection.execute(sa.text(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE"))
        admin.dispose()
        if (
            SCHEMA_RECORD.exists()
            and SCHEMA_RECORD.read_text(encoding="ascii").strip() == SCHEMA
        ):
            SCHEMA_RECORD.unlink()


if __name__ == "__main__":
    cleanup_recorded_schema() if sys.argv[1:] == ["--cleanup"] else main()
