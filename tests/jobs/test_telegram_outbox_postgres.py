"""독립 schema에서 원자점유·중복·부분/불명·예산/중지·보존을 검증."""

import os
import secrets
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from runpy import run_path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.schema import CreateTable

from tests.newsletter.test_newsletter import PREPARED, SEND
from tests.newsletter.test_newsletter_postgres import seed
from tests.support.paths import ROOT
from xfolio.db.domestic import calendar_days
from xfolio.db.newsletter_news import deliveries as news_deliveries
from xfolio.db.schema import usage_ledger
from xfolio.db.telegram import attempts, metadata, outbox, parts
from xfolio.jobs import outbox as outbox_module
from xfolio.jobs.outbox import TelegramOutboxStore, dispatch
from xfolio.jobs.telegram import (
    MockTelegramTransport,
    SendResult,
    split_text,
    validate_entities,
)
from xfolio.newsletter.settings import NotificationSettingsStore
from xfolio.newsletter.store import NewsletterStore


@pytest.fixture
def db():
    url = os.environ.get("XFOLIO_TEST_DATABASE_URL")
    if not url:
        pytest.skip("explicit isolated PostgreSQL required")
    base = NewsletterStore.from_url(url)
    schema = "xf_t06_" + secrets.token_hex(8)
    with base.engine.begin() as conn:
        conn.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    engine = sa.create_engine(
        base.engine.url,
        hide_parameters=True,
        connect_args={"options": f"-csearch_path={schema}"},
    )
    config = Config(str(ROOT / "alembic.ini"))
    try:
        with engine.begin() as conn:
            config.attributes["connection"] = conn
            command.upgrade(config, "head")
        newsletter = NewsletterStore(engine)
        inputs = seed(newsletter)
        edition = newsletter.save(inputs, now=PREPARED)
        yield TelegramOutboxStore(engine), edition, config
    finally:
        engine.dispose()
        with base.engine.begin() as conn:
            conn.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        base.engine.dispose()


class FakeLive:
    mode = "live"

    def __init__(self, results=None):
        self.calls = []
        self.results = list(results or [])

    def send(self, text, *, entities=()):
        self.calls.append(text)
        return (
            self.results.pop(0)
            if self.results
            else SendResult("confirmed", message_id=str(len(self.calls)))
        )


def test_0007_upgrade_downgrade_and_frozen_snapshot(db):
    store, _, config = db
    snapshot = run_path(str(ROOT / "migrations/schema_0007.py"))
    for table in metadata.sorted_tables:
        assert str(CreateTable(table).compile(dialect=store.engine.dialect)) == str(
            CreateTable(
                snapshot[
                    table.name.replace("telegram_outbox_parts", "parts")
                    .replace("telegram_send_attempts", "attempts")
                    .replace("telegram_outbox", "outbox")
                ]
            ).compile(dialect=store.engine.dialect)
        )
    with store.engine.begin() as conn:
        config.attributes["connection"] = conn
        command.downgrade(config, "0006_notification_settings")
        assert "telegram_outbox" not in sa.inspect(conn).get_table_names()
        assert "newsletter_editions" in sa.inspect(conn).get_table_names()
        command.upgrade(config, "head")
        assert "telegram_outbox" in sa.inspect(conn).get_table_names()


def test_enqueue_mock_live_are_separate_and_no_body_persisted(db):
    store, edition, _ = db
    mock = store.enqueue(edition.key, now=PREPARED)
    live = store.enqueue(edition.key, now=PREPARED, mode="live")
    assert mock != live and store.enqueue(edition.key, now=SEND) == mock
    with store.engine.connect() as conn:
        assert conn.scalar(sa.select(sa.func.count()).select_from(outbox)) == 2
        assert "body" not in outbox.c and "payload" not in outbox.c
        assert "text" not in parts.c and "text" not in attempts.c
    assert store.get_delivery(mock, now=SEND)["body"] == edition.body
    assert "claim_token" not in store.get_delivery(mock, now=SEND)


def test_atomic_claim_and_duplicate_dispatch(db):
    store, edition, _ = db
    key = store.enqueue(edition.key, now=PREPARED)
    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(lambda _: store.claim(key, now=SEND), range(2)))
    assert sum(c is not None for c in claims) == 1
    transport = MockTelegramTransport()
    assert dispatch(store, key, transport, clock=lambda: SEND)["status"] == "sending"
    assert not transport.sent


def test_mock_success_does_not_mark_news_delivered(db):
    store, edition, _ = db
    key = store.enqueue(edition.key, now=PREPARED)
    transport = MockTelegramTransport()
    assert dispatch(store, key, transport, clock=lambda: SEND)["status"] == "confirmed"
    assert len(transport.sent) == 1
    dispatch(store, key, transport, clock=lambda: SEND)
    assert len(transport.sent) == 1
    with store.engine.connect() as conn:
        assert conn.scalar(sa.select(sa.func.count()).select_from(news_deliveries)) == 0


def test_split_dispatch_preserves_entities_in_each_sent_chunk(db, monkeypatch):
    store, edition, _ = db
    monkeypatch.setattr(
        outbox_module, "split_text", lambda text: split_text(text, limit=300)
    )
    key = store.enqueue(edition.key, now=PREPARED)
    transport = MockTelegramTransport()
    result = dispatch(store, key, transport, clock=lambda: SEND)
    assert result["status"] == "confirmed" and len(transport.sent) > 1
    assert "".join(transport.sent) == edition.body
    urls = []
    for text, entities in zip(transport.sent, transport.entities, strict=True):
        validate_entities(text, entities)
        urls.extend(e["url"] for e in entities if e["type"] == "text_link")
    assert set(urls) == {e["url"] for e in edition.entities if e["type"] == "text_link"}


def test_fake_live_success_has_receipt_and_news_success(db):
    store, edition, _ = db
    key = store.enqueue(edition.key, now=PREPARED, mode="live")
    result = dispatch(store, key, FakeLive(), clock=lambda: SEND)
    assert result["status"] == "confirmed" and result["parts"][0]["message_id"] == "1"
    assert len(result["attempts"]) == 1
    with store.engine.connect() as conn:
        statuses = conn.scalars(sa.select(news_deliveries.c.status)).all()
        assert len(statuses) == edition.news_count and set(statuses) == {"confirmed"}


@pytest.mark.parametrize(
    "mutation,reason",
    [
        ("pause", "disabled_or_paused"),
        ("calendar", "market_closed_or_unverified"),
        ("budget", "monthly_budget_exceeded"),
        ("deadline", "outside_send_window"),
    ],
)
def test_current_server_guard_blocks_before_transport(db, mutation, reason):
    store, edition, _ = db
    key = store.enqueue(edition.key, now=PREPARED)
    if mutation == "pause":
        NotificationSettingsStore(store.engine).update(
            expected_revision=1, changes={"paused": True}, actor="test", now=SEND
        )
    elif mutation == "calendar":
        with store.engine.begin() as conn:
            conn.execute(
                calendar_days.update()
                .where(
                    calendar_days.c.observed_on == edition.target_date,
                    calendar_days.c.trade_date == edition.target_date,
                )
                .values(is_open=False)
            )
    elif mutation == "budget":
        with store.engine.begin() as conn:
            conn.execute(
                usage_ledger.insert().values(
                    id="test-budget",
                    provider="test",
                    month="2026-11",
                    state="confirmed",
                    amount_krw=50001,
                    payload={},
                )
            )
    now = SEND + timedelta(minutes=10) if mutation == "deadline" else SEND
    transport = MockTelegramTransport()
    result = dispatch(store, key, transport, clock=lambda: now)
    assert result["status"] == "skipped" and result["error_code"] == reason
    assert not transport.sent


def test_rate_limit_safe_retry_never_claims_early(db):
    store, edition, _ = db
    key = store.enqueue(edition.key, now=PREPARED, mode="live")
    transport = FakeLive(
        [
            SendResult(
                "retryable_failure", error_code="telegram_rate_limited", retry_after=30
            )
        ]
    )
    assert (
        dispatch(store, key, transport, clock=lambda: SEND)["status"]
        == "retryable_failure"
    )
    assert (
        dispatch(store, key, transport, clock=lambda: SEND + timedelta(seconds=10))[
            "status"
        ]
        == "retryable_failure"
    )
    assert len(transport.calls) == 1
    assert (
        dispatch(store, key, transport, clock=lambda: SEND + timedelta(seconds=30))[
            "status"
        ]
        == "confirmed"
    )
    assert len(transport.calls) == 2


def test_rate_limit_beyond_deadline_stops(db):
    store, edition, _ = db
    key = store.enqueue(edition.key, now=PREPARED, mode="live")
    transport = FakeLive(
        [
            SendResult(
                "retryable_failure", error_code="telegram_rate_limited", retry_after=60
            )
        ]
    )
    result = dispatch(store, key, transport, clock=lambda: SEND + timedelta(minutes=9))
    assert (
        result["status"] == "failed"
        and result["error_code"] == "retry_exceeds_deadline"
    )


def test_unknown_is_terminal_and_prevents_duplicate_news(db):
    store, edition, _ = db
    key = store.enqueue(edition.key, now=PREPARED, mode="live")
    transport = FakeLive([SendResult("unknown", error_code="telegram_result_unknown")])
    assert dispatch(store, key, transport, clock=lambda: SEND)["status"] == "unknown"
    assert dispatch(store, key, transport, clock=lambda: SEND)["status"] == "unknown"
    assert len(transport.calls) == 1
    with store.engine.connect() as conn:
        assert set(conn.scalars(sa.select(news_deliveries.c.status))) == {"unknown"}


def test_restart_after_unrecorded_result_becomes_unknown(db):
    store, edition, _ = db
    key = store.enqueue(edition.key, now=PREPARED, mode="live")
    token = store.claim(key, now=SEND)
    assert store.start_part(key, 1, token, now=SEND)
    assert store.recover_stale(now=SEND + timedelta(seconds=89)) == 0
    assert store.recover_stale(now=SEND + timedelta(seconds=90)) == 1
    result = store.get_delivery(key, now=SEND + timedelta(seconds=90))
    assert result["status"] == "unknown" and result["parts"][0]["status"] == "unknown"
    assert result["attempts"][0]["status"] == "unknown"
    assert store.claim(key, now=SEND + timedelta(seconds=91)) is None


def test_partial_is_terminal_and_pause_checked_between_parts(db, monkeypatch):
    store, edition, _ = db
    monkeypatch.setattr(
        outbox_module, "split_text", lambda text: split_text(text, limit=300)
    )
    key = store.enqueue(edition.key, now=PREPARED, mode="live")

    class PauseTransport(FakeLive):
        def send(self, text, *, entities=()):
            result = super().send(text)
            NotificationSettingsStore(store.engine).update(
                expected_revision=1, changes={"paused": True}, actor="test", now=SEND
            )
            return result

    transport = PauseTransport()
    result = dispatch(store, key, transport, clock=lambda: SEND)
    assert result["status"] == "partial" and len(transport.calls) == 1
    assert result["parts"][0]["status"] == "confirmed"
    assert result["error_code"] == "disabled_or_paused"


def test_expired_body_hidden_but_metadata_retained_then_purged(db):
    store, edition, _ = db
    key = store.enqueue(edition.key, now=PREPARED)
    later = PREPARED + timedelta(days=91)
    assert store.get_delivery(key, now=later)["body"] is None
    assert store.purge_expired(now=later) == 0
    assert store.purge_expired(now=PREPARED + timedelta(days=365)) == 1
    assert store.get_delivery(key, now=PREPARED + timedelta(days=365)) is None
    with store.engine.connect() as conn:
        assert conn.scalar(sa.select(sa.func.count()).select_from(parts)) == 0


def test_partial_429_then_pause_stays_partial_not_skipped(db, monkeypatch):
    store, edition, _ = db
    monkeypatch.setattr(
        outbox_module, "split_text", lambda text: split_text(text, limit=300)
    )
    key = store.enqueue(edition.key, now=PREPARED, mode="live")
    transport = FakeLive(
        [
            SendResult("confirmed", message_id="1"),
            SendResult(
                "retryable_failure", error_code="telegram_rate_limited", retry_after=30
            ),
        ]
    )
    assert (
        dispatch(store, key, transport, clock=lambda: SEND)["status"]
        == "retryable_failure"
    )
    NotificationSettingsStore(store.engine).update(
        expected_revision=1, changes={"paused": True}, actor="test", now=SEND
    )
    result = dispatch(store, key, transport, clock=lambda: SEND + timedelta(seconds=30))
    assert result["status"] == "partial" and len(transport.calls) == 2
    with store.engine.connect() as conn:
        assert set(conn.scalars(sa.select(news_deliveries.c.status))) == {"unknown"}


def test_worker_holiday_state_is_idempotent_and_contains_no_body(db):
    store, edition, _ = db
    from xfolio.db.schema import operations_events

    for _ in range(2):
        store.record_worker_state(
            day=edition.target_date, status="skipped", reason="market_closed", now=SEND
        )
    with store.engine.connect() as conn:
        rows = (
            conn.execute(
                sa.select(operations_events).where(
                    operations_events.c.kind == "newsletter_worker"
                )
            )
            .mappings()
            .all()
        )
        assert len(rows) == 1 and rows[0]["payload"]["reason"] == "market_closed"
        assert "body" not in rows[0]["payload"]
