"""대시보드 실제DB 집계·기준거래일·미관측/합성·만료·비밀비노출."""

import os
import secrets
from datetime import date, timedelta
from decimal import Decimal

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from tests.api.test_api import AuthStoreDouble, GoogleDouble, sign_in
from tests.newsletter.test_newsletter import DAY, PREPARED, SEND, inputs
from tests.newsletter.test_newsletter_postgres import seed
from tests.support.paths import ROOT
from xfolio.api.app import create_app
from xfolio.api.auth import Settings
from xfolio.api.newsletter_admin import NewsletterAdminStore
from xfolio.db.domestic import market_runs, price_snapshots
from xfolio.db.schema import operations_events, usage_ledger
from xfolio.domestic.calendar import local_calendar
from xfolio.domestic.models import Collection
from xfolio.domestic.store import DomesticStore
from xfolio.jobs.outbox import TelegramOutboxStore
from xfolio.newsletter.edition import at
from xfolio.newsletter.store import NewsletterStore


@pytest.fixture
def db():
    url = os.environ.get("XFOLIO_TEST_DATABASE_URL")
    if not url:
        pytest.skip("explicit isolated PostgreSQL required")
    base = sa.create_engine(url, hide_parameters=True)
    schema = "xf_t05_dashboard_" + secrets.token_hex(8)
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
        DomesticStore(engine).bootstrap(PREPARED - timedelta(days=1))
        yield engine, config
    finally:
        engine.dispose()
        with base.begin() as conn:
            conn.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        base.dispose()


def prepared(engine, *, live=True, scenario="news"):
    store = NewsletterStore(engine)
    data = seed(store, data=inputs(live=live, scenario=scenario))
    edition = store.save(data, now=PREPARED)
    return data, edition


def test_empty_dashboard_is_unobserved_and_does_not_claim_zero_actual_cost(db):
    engine, _ = db
    result = NewsletterAdminStore(engine).summary(now=SEND)
    assert result["market_open"] is None
    assert result["budget"]["status"] == "not_measured"
    assert result["budget"]["billing_reconciled"] is False
    assert result["budget"]["scope"] == "recorded_usage_ledger_only"
    assert result["price_freshness"]["status"] == "calendar_unverified"
    assert result["news_collection"]["status"] == "not_observed"
    assert result["deliveries"]["status"] == "not_observed"


def test_dashboard_real_sources_and_times_are_read_without_a_network(db):
    engine, _ = db
    data, _edition = prepared(engine)
    result = NewsletterAdminStore(engine).summary(now=SEND)
    assert result["market_open"] is True
    prices = result["price_freshness"]
    assert prices["status"] == "current" and prices["provenance"] == "live"
    assert prices["expected_trade_date"] == date(2026, 11, 3)
    assert all(
        p["status"] == "current"
        and p["price_as_of"] is None
        and p["delay_status"] == "not_measured"
        for p in prices["items"]
    )
    assert prices["items"][0]["retrieved_at"] == data.market.quotes[0].retrieved_at
    assert result["news_collection"]["selected_count"] == 3
    assert result["news_collection"]["current"] is True
    assert result["news_collection"]["provenance"] == "live"
    assert {s["provider"] for s in result["news_collection"]["sources"]} == {
        "Finnhub",
        "BLS",
        "BEA",
        "Board",
    }


@pytest.mark.parametrize(
    "scenario,expected,zero",
    [
        ("zero", "complete", True),
        ("partial", "partial", False),
        ("failed", "failed", False),
    ],
)
def test_news_zero_partial_and_failure_are_distinct(db, scenario, expected, zero):
    engine, _ = db
    prepared(engine, scenario=scenario)
    news = NewsletterAdminStore(engine).summary(now=SEND)["news_collection"]
    assert news["status"] == expected and news["normal_zero"] is zero
    assert len(news["sources"]) == 4


def test_synthetic_inputs_never_show_as_current_live_prices(db):
    engine, _ = db
    prepared(engine, live=False)
    result = NewsletterAdminStore(engine).summary(now=SEND)
    assert result["price_freshness"]["status"] == "synthetic"
    assert result["news_collection"]["synthetic"] is True
    assert result["news_collection"]["provenance"] == "synthetic"


def test_price_run_without_an_edition_is_not_inferred_to_be_live(db):
    engine, _ = db
    seed(NewsletterStore(engine), data=inputs(live=True))
    result = NewsletterAdminStore(engine).summary(now=SEND)
    assert result["price_freshness"]["status"] == "provenance_unverified"
    assert result["news_collection"]["provenance"] == "unverified"


def test_weekend_and_previous_news_are_shown_without_new_success(db):
    engine, _ = db
    prepared(engine)
    result = NewsletterAdminStore(engine).summary(now=at(date(2026, 11, 7), 8))
    assert result["market_open"] is False
    assert result["news_collection"]["current"] is False
    assert result["newsletters"] == []


def test_calendar_disagreement_never_marks_prices_current(db):
    from xfolio.db.domestic import calendar_days

    engine, _ = db
    prepared(engine)
    with engine.begin() as conn:
        conn.execute(
            calendar_days.update()
            .where(
                calendar_days.c.observed_on == DAY,
                calendar_days.c.trade_date == date(2026, 11, 3),
            )
            .values(is_open=False)
        )
    result = NewsletterAdminStore(engine).summary(now=SEND)["price_freshness"]
    assert (
        result["status"] == "calendar_unverified"
        and result["reason"] == "calendar_disagreement"
    )


def test_missing_price_and_superseded_correction_are_visible(db):
    engine, _ = db
    data, _edition = prepared(engine)
    quote = data.market.quotes[0]
    corrected = quote.model_copy(
        update={
            "latest": quote.latest.model_copy(update={"close": quote.latest.close + 1}),
            "basis_verified": False,
        }
    )
    collection = Collection.model_validate(
        data.market.model_dump() | {"quotes": (corrected, *data.market.quotes[1:])}
    )
    DomesticStore(engine).save_collection(collection, now=PREPARED)
    with engine.connect() as conn:
        # inspect the original edition-linked run before a subsequent re-collection.
        original = (
            conn.execute(
                sa.select(market_runs).where(market_runs.c.id == data.market_run_id)
            )
            .mappings()
            .one()
        )
        missing_id = original["observations"][-1]["snapshot_id"]
    with engine.begin() as conn:
        conn.execute(
            market_runs.update()
            .where(market_runs.c.id != data.market_run_id)
            .values(finished_at=SEND + timedelta(minutes=1))
        )
        conn.execute(price_snapshots.delete().where(price_snapshots.c.id == missing_id))
    result = NewsletterAdminStore(engine).summary(now=SEND)["price_freshness"]
    assert result["status"] == "attention"
    assert {p["status"] for p in result["items"]} == {
        "superseded",
        "current",
        "missing",
    }


def test_latest_completed_trade_day_changes_after_close(db):
    engine, _ = db
    prepared(engine)
    result = NewsletterAdminStore(engine).summary(now=at(DAY, 17))["price_freshness"]
    assert result["expected_trade_date"] == DAY
    assert result["status"] == "attention"
    assert all(p["status"] == "stale" for p in result["items"])


def test_ledger_uses_kst_month_and_tracks_reserved_estimated_confirmed(db, monkeypatch):
    engine, _ = db
    monkeypatch.setenv("XFOLIO_MONTHLY_BUDGET_KRW", "1000")
    with engine.begin() as conn:
        conn.execute(
            usage_ledger.insert(),
            [
                {
                    "id": str(i),
                    "provider": "OpenAI",
                    "month": month,
                    "state": state,
                    "amount_krw": amount,
                    "payload": {"api_key": "do-not-expose"},
                }
                for i, (month, state, amount) in enumerate(
                    [
                        ("2026-12", "confirmed", 600),
                        ("2026-12", "reserved", 300),
                        ("2026-12", "estimated", 200),
                        ("2026-12", "released", 999),
                        ("2026-11", "confirmed", 8000),
                    ]
                )
            ],
        )
    budget = NewsletterAdminStore(engine).summary(now=at(date(2026, 12, 1), 0))[
        "budget"
    ]
    assert budget["status"] == "over_limit" and budget["month"] == "2026-12"
    assert budget["committed_krw"] == Decimal(1100) and budget["remaining_krw"] == 0
    assert budget["released_krw"] == Decimal(999) and budget["record_count"] == 4
    assert "do-not-expose" not in str(budget)
    monkeypatch.setenv("XFOLIO_MONTHLY_BUDGET_KRW", "NaN")
    assert (
        NewsletterAdminStore(engine).summary(now=SEND)["budget"]["status"]
        == "invalid_configuration"
    )


def test_mixed_delivery_failures_and_worker_skip_are_visible(db):
    engine, _ = db
    _data, edition = prepared(engine)
    outbox = TelegramOutboxStore(engine)
    key = outbox.enqueue(edition.key, now=PREPARED, mode="live")
    from xfolio.db.telegram import outbox as table

    with engine.begin() as conn:
        conn.execute(
            table.update()
            .where(table.c.id == key)
            .values(
                status="unknown",
                error_code="telegram_result_unconfirmed",
                updated_at=SEND,
            )
        )
    outbox.record_worker_state(
        day=DAY, status="skipped", reason="outside_send_window", now=SEND
    )
    result = NewsletterAdminStore(engine).summary(now=SEND)
    assert result["deliveries"]["recent"][0]["transport_mode"] == "live"
    assert result["deliveries"]["attention"][0]["status"] == "unknown"
    assert (
        result["worker"]["status"] == "skipped"
        and result["worker"]["stage"] == "dispatch"
        and result["worker"]["reason"] == "outside_send_window"
    )
    assert "claim_token" not in result["deliveries"]["recent"][0]


@pytest.mark.parametrize(
    "status,reason,expected_status,expected_reason",
    [
        ("running", None, "running", None),
        (
            "failed",
            "preparation_failed_no_automatic_retry",
            "failed",
            "preparation_failed_no_automatic_retry",
        ),
        (
            "secret detail",
            "https://secret.invalid/token",
            "unknown",
            "unavailable_error_code",
        ),
    ],
)
def test_preparation_state_is_visible_before_send_and_only_safe_fields_are_exposed(
    db, status, reason, expected_status, expected_reason
):
    engine, _ = db
    TelegramOutboxStore(engine).record_worker_state(
        day=DAY - timedelta(days=1),
        status="skipped",
        reason="outside_send_window",
        now=PREPARED - timedelta(days=1),
    )
    with engine.begin() as conn:
        conn.execute(
            operations_events.insert(),
            [
                {
                    "id": "prepare",
                    "kind": "newsletter_prepare",
                    "created_at": PREPARED,
                    "expires_at": PREPARED + timedelta(days=90),
                    "payload": {
                        "status": status,
                        "reason": reason,
                        "api_key": "never-expose",
                    },
                },
                {
                    "id": "expired",
                    "kind": "newsletter_prepare",
                    "created_at": PREPARED + timedelta(seconds=1),
                    "expires_at": PREPARED + timedelta(seconds=2),
                    "payload": {"status": "failed", "reason": "expired_event"},
                },
            ],
        )
    result = NewsletterAdminStore(engine).summary(now=PREPARED + timedelta(seconds=30))[
        "worker"
    ]
    assert result == {
        "stage": "preparation",
        "status": expected_status,
        "reason": expected_reason,
        "recorded_at": PREPARED,
    }
    assert "never-expose" not in str(result)


def test_expired_price_payload_is_not_returned(db):
    engine, _ = db
    prepared(engine)
    later = SEND + timedelta(days=91)
    target = later.astimezone(at(DAY, 8).tzinfo).date()
    schedule = local_calendar().schedule(
        start_date=target - timedelta(days=14), end_date=target
    )
    opened = {
        target - timedelta(days=i): target - timedelta(days=i)
        in set(schedule.index.date)
        for i in range(15)
    }
    DomesticStore(engine).save_calendar(opened, later)
    result = NewsletterAdminStore(engine).summary(now=later)
    assert all(
        p["status"] == "expired" and "trade_date" not in p
        for p in result["price_freshness"]["items"]
    )
    assert result["news_collection"]["status"] == "not_observed"
    assert result["newsletters"] == []


def test_authenticated_summary_endpoint_serializes_db_decimals(db, monkeypatch):
    engine, _ = db
    monkeypatch.setenv("XFOLIO_MONTHLY_BUDGET_KRW", "12345.5")
    settings = Settings(
        origin="https://testserver",
        google_client_id="id",
        google_client_secret="secret",
        allowed_emails=("owner@example.invalid",),
        cursor_secret="s" * 32,
    )
    google = GoogleDouble()
    google.claims["exp"] = SEND.timestamp() + 3600
    app = create_app(
        settings,
        AuthStoreDouble(),
        google,
        lambda: SEND,
        admin_store=NewsletterAdminStore(engine),
    )
    with TestClient(app, base_url=settings.origin) as client:
        assert client.get("/api/newsletter-operations/summary").status_code == 401
        sign_in(client)
        result = client.get("/api/newsletter-operations/summary")
        assert result.status_code == 200
        assert str(result.json()["budget"]["limit_krw"]) == "12345.5"
        assert result.headers["cache-control"] == "no-store"
