"""T04 신규0005·원본 대조·멱등·경쟁·90일·직전 재검사를 격리 PG에서 검증."""

import os
import secrets
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from runpy import run_path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.schema import CreateTable
from test_newsletter import DAY, PREPARED, SEND, context, inputs

from xfolio.db.domestic import price_snapshots
from xfolio.db.newsletter import editions
from xfolio.db.newsletter_news import deliveries, items
from xfolio.db.schema import publication_jobs
from xfolio.domestic.store import DomesticStore
from xfolio.newsletter import MorningInputs, NewsletterError, at
from xfolio.newsletter_news_store import NewsletterNewsStore
from xfolio.newsletter_store import NewsletterStore


@pytest.fixture
def store():
    url = os.environ.get("XFOLIO_TEST_DATABASE_URL")
    if not url:
        pytest.skip("explicit isolated PostgreSQL required")
    base = NewsletterStore.from_url(url)
    schema = "xf_t04_" + secrets.token_hex(8)
    with base.engine.begin() as conn:
        conn.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    engine = sa.create_engine(
        base.engine.url,
        hide_parameters=True,
        connect_args={"options": f"-csearch_path={schema}"},
    )
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    try:
        with engine.begin() as conn:
            config.attributes["connection"] = conn
            command.upgrade(config, "head")
        yield NewsletterStore(engine), config
    finally:
        engine.dispose()
        with base.engine.begin() as conn:
            conn.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        base.engine.dispose()


def seed(db, *, data=None, now=PREPARED):
    data = data or inputs(live=True)
    domestic = DomesticStore(db.engine)
    domestic.bootstrap(data.frozen_at - timedelta(days=1))
    domestic.save_calendar(data.calendar_opened, data.frozen_at)
    saved = domestic.save_collection(data.market, now=now)
    NewsletterNewsStore(db.engine).save_result(data.news, now=now)
    return MorningInputs.model_validate(
        data.model_dump() | {"market_run_id": saved["run_id"]}
    )


def test_0005_snapshot_upgrade_downgrade_and_preserve_existing_rows(store):
    db, config = store
    data = seed(db)
    db.save(data, now=PREPARED)
    with db.engine.begin() as conn:
        assert "newsletter_editions" in sa.inspect(conn).get_table_names()
        assert conn.scalar(sa.select(sa.func.count()).select_from(price_snapshots)) == 3
        config.attributes["connection"] = conn
        command.downgrade(config, "0004_newsletter_news")
        assert "newsletter_editions" not in sa.inspect(conn).get_table_names()
        assert conn.scalar(sa.select(sa.func.count()).select_from(price_snapshots)) == 3
        assert conn.scalar(sa.select(sa.func.count()).select_from(items)) == 3
        assert "publication_jobs" in sa.inspect(conn).get_table_names()
        command.upgrade(config, "head")
    snapshot = run_path(str(Path(__file__).parents[1] / "migrations/schema_0005.py"))
    assert str(CreateTable(editions).compile(dialect=db.engine.dialect)) == str(
        CreateTable(snapshot["editions"]).compile(dialect=db.engine.dialect)
    )


def test_save_is_idempotent_immutable_and_does_not_mark_delivery(store):
    db, _ = store
    data = seed(db)
    first = db.save(data, now=PREPARED)
    second = db.save(data, now=SEND)
    assert first == second
    assert db.get(first.key, now=SEND) == first
    assert db.check(first.key, context()).can_send
    assert len(first.price_snapshot_ids) == 3
    with db.engine.connect() as conn:
        assert conn.scalar(sa.select(sa.func.count()).select_from(editions)) == 1
        assert conn.scalar(sa.select(sa.func.count()).select_from(deliveries)) == 0
        assert (
            conn.scalar(sa.select(sa.func.count()).select_from(publication_jobs)) == 0
        )
        payload = conn.scalar(sa.select(editions.c.payload))
        assert payload["body"] == first.body
        assert "evidence_span" not in str(payload) and '"facts"' not in str(payload)
    changed = MorningInputs.model_validate(
        data.model_dump() | {"settings": {"revision": 2}}
    )
    with pytest.raises(NewsletterError, match="edition_input_conflict"):
        db.save(changed, now=SEND)
    with pytest.raises(sa.exc.DBAPIError), db.engine.begin() as conn:
        conn.execute(editions.update().values(status="failed"))


def test_concurrent_same_edition_returns_one_immutable_row(store):
    db, _ = store
    data = seed(db)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: db.save(data, now=PREPARED), range(2)))
    assert results[0] == results[1]
    with db.engine.connect() as conn:
        assert conn.scalar(sa.select(sa.func.count()).select_from(editions)) == 1


@pytest.mark.parametrize(
    "scenario,status", [("partial", "partial"), ("failed", "failed"), ("zero", "ready")]
)
def test_partial_failed_zero_states_are_persisted(store, scenario, status):
    db, _ = store
    data = seed(db, data=inputs(live=True, scenario=scenario))
    result = db.save(data, now=PREPARED)
    assert result.status == status and db.get(result.key, now=PREPARED) == result
    assert db.check(result.key, context()).can_send == (status != "failed")


@pytest.mark.parametrize(
    "change", ["price", "news", "market_run", "instrument", "calendar"]
)
def test_cannot_store_different_source_or_version_under_existing_id(store, change):
    db, _ = store
    data = seed(db).model_dump()
    if change == "price":
        data["market"]["quotes"][0]["basis_verified"] = False
    elif change == "news":
        data["news"]["selected"][0]["summary_ko"] = "GDP 99%"
    elif change == "market_run":
        data["market_run_id"] = "missing"
    elif change == "instrument":
        data["instruments"][0]["name"] = "wrong-instrument-name"
    else:
        data["calendar_opened"][DAY] = False
    with pytest.raises(NewsletterError):
        db.save(MorningInputs.model_validate(data), now=PREPARED)
    with db.engine.connect() as conn:
        assert conn.scalar(sa.select(sa.func.count()).select_from(editions)) == 0


def test_retention_uses_earliest_original_expiry_and_exact_boundary(store):
    db, _ = store
    data = seed(db, now=at(DAY, 7, 52))
    result = db.save(data, now=PREPARED)
    expiry = at(DAY, 7, 51) + timedelta(days=90)
    assert result.expires_at == expiry
    assert db.get(result.key, now=expiry - timedelta(microseconds=1)) is not None
    assert db.get(result.key, now=expiry) is None
    with pytest.raises(NewsletterError, match="expired"):
        db.save(data, now=expiry)
    assert db.purge_expired(now=expiry) == 1
    with db.engine.connect() as conn:
        assert conn.scalar(sa.select(sa.func.count()).select_from(editions)) == 0


def test_send_rechecks_database_watchlist_even_if_context_is_stale(store):
    db, _ = store
    data = seed(db)
    result = db.save(data, now=PREPARED)
    DomesticStore(db.engine).replace_watchlist(
        data.codes[:2], expected_revision=1, now=SEND
    )
    decision = db.check(result.key, context())
    assert not decision.can_send and "watchlist_changed_in_database" in decision.reasons


def correction(data):
    quote = data.market.quotes[0]
    day = quote.latest.model_copy(
        update={
            "close": quote.latest.close + 10,
            "provider_change": quote.latest.provider_change + 10,
        }
    )
    fixed = quote.model_copy(update={"latest": day, "retrieved_at": PREPARED})
    return data.market.model_copy(
        update={
            "started_at": PREPARED,
            "finished_at": PREPARED,
            "quotes": (fixed, *data.market.quotes[1:]),
        }
    )


def test_superseded_price_blocks_existing_edition_and_old_input_save(store):
    db, _ = store
    data = seed(db)
    result = db.save(data, now=PREPARED)
    DomesticStore(db.engine).save_collection(correction(data), now=PREPARED)
    decision = db.check(result.key, context())
    assert (
        not decision.can_send
        and "price_missing_expired_or_superseded" in decision.reasons
    )
    other = data.model_copy(update={"recipient_scope": "other"})
    with pytest.raises(NewsletterError, match="price_superseded"):
        db.save(other, now=PREPARED)


def test_corrected_snapshot_price_can_be_shown_but_return_is_held(store):
    db, _ = store
    data = seed(db)
    market = correction(data)
    saved = DomesticStore(db.engine).save_collection(market, now=PREPARED)
    updated = MorningInputs.model_validate(
        data.model_dump() | {"market_run_id": saved["run_id"], "market": market}
    )
    result = db.save(updated, now=PREPARED)
    assert result.status == "partial" and "정정 가격" in result.body


@pytest.mark.parametrize("state", ["confirmed", "unknown"])
def test_news_delivered_or_unknown_cannot_be_sent_again(store, state):
    db, _ = store
    data = seed(db)
    result = db.save(data, now=PREPARED)
    NewsletterNewsStore(db.engine).record_delivery(
        data.news.selected[0],
        recipient_scope="self",
        status=state,
        message_id="synthetic-message" if state == "confirmed" else None,
        now=SEND,
    )
    decision = db.check(result.key, context())
    assert (
        not decision.can_send
        and "news_already_delivered_or_unknown" in decision.reasons
    )


def test_source_deleted_or_missing_current_calendar_blocks_send(store):
    db, _ = store
    data = seed(db)
    result = db.save(data, now=PREPARED)
    from xfolio.db.domestic import calendar_days

    with db.engine.begin() as conn:
        conn.execute(items.delete())
        conn.execute(price_snapshots.delete())
        conn.execute(calendar_days.delete())
    decision = db.check(result.key, context())
    assert not decision.can_send
    assert "price_missing_expired_or_superseded" in decision.reasons
    assert "news_item_missing_or_expired" in decision.reasons
    assert "market_closed_or_unverified_in_database" in decision.reasons
