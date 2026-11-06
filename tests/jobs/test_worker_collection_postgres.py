"""격리 PG에서07:50고정·단일준비·T02/T03/T04/outbox실제저장경계를 검증."""

import os
import secrets
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from tests.jobs.test_worker_collection import config
from tests.news.test_newsletter_news import FakeAI
from tests.support.paths import ROOT
from xfolio.ai.workflow import WorkflowError
from xfolio.db.domestic import watchlist
from xfolio.db.newsletter import editions
from xfolio.db.notification_settings import settings as settings_table
from xfolio.db.schema import operations_events, usage_ledger
from xfolio.domestic.models import Collection
from xfolio.domestic.store import DomesticStore
from xfolio.jobs.collection import (
    CappedWorkflowStore,
    LiveMorningPreparation,
    PreparationStore,
)
from xfolio.jobs.outbox import TelegramOutboxStore
from xfolio.news.collection import SourceResult, integrate, summarize
from xfolio.newsletter.demo import demo_inputs
from xfolio.newsletter.settings import NotificationSettingsStore
from xfolio.newsletter.store import NewsletterStore


@pytest.fixture
def db():
    url = os.environ.get("XFOLIO_TEST_DATABASE_URL")
    if not url:
        pytest.skip("explicit isolated PostgreSQL required")
    base = NewsletterStore.from_url(url)
    schema = "xf_collect_" + secrets.token_hex(8)
    with base.engine.begin() as conn:
        conn.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    engine = sa.create_engine(
        base.engine.url,
        hide_parameters=True,
        connect_args={"options": f"-csearch_path={schema}"},
    )
    try:
        cfg = Config(str(ROOT / "alembic.ini"))
        with engine.begin() as conn:
            cfg.attributes["connection"] = conn
            command.upgrade(cfg, "head")
        data = demo_inputs()
        cutoff = data.frozen_at
        DomesticStore(engine).bootstrap(cutoff - timedelta(days=1))
        with engine.begin() as conn:
            conn.execute(
                settings_table.update().values(updated_at=cutoff - timedelta(days=1))
            )
        yield engine, data
    finally:
        engine.dispose()
        with base.engine.begin() as conn:
            conn.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        base.engine.dispose()


def setup(db, *, closed=False, scenario="news", crash=False, failed_news=False):
    engine, data = db
    clock = [data.frozen_at + timedelta(seconds=5)]
    calls = []

    class Kis:
        def holidays(self, _now):
            calls.append("calendar")
            return data.calendar_opened | ({data.target_date: False} if closed else {})

        def collect(self, codes, *, as_of, watchlist_revision):
            calls.append("market")
            if crash:
                raise RuntimeError("secret-provided-error")
            template = demo_inputs(scenario)
            start = clock[0]
            clock[0] = data.frozen_at + timedelta(seconds=40)
            return Collection(
                started_at=start,
                finished_at=clock[0],
                requested_codes=codes,
                watchlist_revision=watchlist_revision,
                quotes=tuple(
                    q.model_copy(update={"retrieved_at": clock[0]})
                    for q in template.market.quotes
                ),
                errors=template.market.errors,
            )

    def news_collector(_client, **kwargs):
        calls.append("news")
        assert kwargs["as_of"] == data.frozen_at
        clock[0] = data.frozen_at + timedelta(seconds=90)
        sources = []
        for source in demo_inputs(scenario).news.sources:
            selected = tuple(
                i.model_copy(update={"retrieved_at": clock[0], "synthetic": False})
                for i in source.items
            )
            sources.append(
                SourceResult(
                    provider=source.provider,
                    status="failed" if failed_news else source.status,
                    requests=0,
                    errors=("test_failure",) if failed_news else source.errors,
                    items=selected,
                )
            )
        return integrate(
            sources,
            as_of=data.frozen_at,
            finished_at=clock[0],
            run_id=secrets.token_hex(8),
            summary=kwargs["summary"],
            seen_keys=kwargs["seen_keys"],
            last_success=kwargs["last_success"],
        )

    cfg = config(now=data.frozen_at)
    ai = FakeAI()
    budget = CappedWorkflowStore(engine, cfg.monthly_limit)
    service = LiveMorningPreparation(
        engine,
        kis=Kis(),
        news_client=None,
        summary=lambda item: summarize(
            item, client=ai, store=budget, limits=cfg.limits, now=clock[0]
        ),
        settings=cfg,
        outbox_store=TelegramOutboxStore(engine),
        news_collector=news_collector,
        clock=lambda: clock[0],
    )
    return service, clock, calls, ai


def test_live_collection_stores_real_contracts_and_is_idempotent(db):
    service, clock, calls, ai = setup(db)
    events = []
    service.observe = events.append
    result = service.prepare()
    assert (
        result["status"] == "ready"
        and result["market_status"] == result["news_status"] == "complete"
    )
    assert result["outbox_id"]
    assert [event["stage"] for event in events if event["status"] == "started"] == [
        "claim",
        "settings",
        "calendar",
        "calendar_save",
        "market_collect",
        "market_save",
        "news_history",
        "news_collect",
        "news_save",
        "edition_save",
        "outbox_enqueue",
        "finish",
    ]
    assert events[-1]["status"] == "finished"
    edition = NewsletterStore(db[0]).get(result["edition_id"], now=clock[0])
    assert edition.mode == "live" and not edition.synthetic and edition.news_count == 3
    assert len(ai.calls) == 1 and calls == ["calendar", "market", "news"]
    assert service.prepare()["reused"]
    assert calls == ["calendar", "market", "news"] and len(ai.calls) == 1
    with db[0].connect() as conn:
        assert set(conn.scalars(sa.select(usage_ledger.c.state))) == {"confirmed"}
        assert conn.scalar(sa.select(sa.func.count()).select_from(editions)) == 1


def test_concurrent_preparation_claims_only_one_external_collection(db):
    service, _clock, calls, _ai = setup(db)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: service.prepare(), range(2)))
    assert calls.count("market") == calls.count("news") == 1
    assert sum(bool(r.get("reused")) for r in results) == 1


def test_holiday_has_no_prices_news_or_paid_calls(db):
    service, _clock, calls, ai = setup(db, closed=True)
    result = service.prepare()
    assert result["status"] == "skipped" and result["reason"] == "market_closed"
    assert calls == ["calendar"] and not ai.calls


@pytest.mark.parametrize("field", ["settings", "watchlist"])
def test_configuration_changed_after_0750_is_never_backdated(db, field):
    service, _clock, calls, ai = setup(db)
    table = settings_table if field == "settings" else watchlist
    if field == "watchlist":
        DomesticStore(db[0]).replace_watchlist(
            tuple(reversed(db[1].codes)),
            expected_revision=1,
            now=db[1].frozen_at + timedelta(seconds=1),
        )
    else:
        with db[0].begin() as conn:
            conn.execute(
                table.update().values(updated_at=db[1].frozen_at + timedelta(seconds=1))
            )
    result = service.prepare()
    assert (
        result["reason"] == "configuration_changed_after_freeze"
        and not calls
        and not ai.calls
    )


def test_pause_before_freeze_blocks_provider_calls(db):
    service, _clock, calls, _ai = setup(db)
    NotificationSettingsStore(db[0]).update(
        expected_revision=1,
        changes={"paused": True},
        actor="test",
        now=db[1].frozen_at - timedelta(seconds=1),
    )
    assert service.prepare()["reason"] == "disabled_or_paused" and not calls


def test_missed_grace_and_early_call_do_not_replay_clock(db):
    service, clock, calls, _ai = setup(db)
    clock[0] = db[1].frozen_at - timedelta(seconds=1)
    assert service.prepare()["reason"] == "before_freeze_window"
    with db[0].connect() as conn:
        assert (
            conn.scalar(sa.select(sa.func.count()).select_from(operations_events)) == 0
        )
    clock[0] = db[1].frozen_at + timedelta(minutes=1)
    assert service.prepare()["reason"] == "freeze_window_missed" and not calls


def test_failure_is_sanitized_and_never_paid_recollected(db):
    service, _clock, calls, _ai = setup(db, crash=True)
    events = []
    service.observe = events.append
    result = service.prepare()
    assert result["status"] == "failed" and "secret" not in str(result)
    assert result["failed_stage"] == "market_collect"
    assert result["exception_type"] == "RuntimeError"
    assert result["frames"][-1]["function"] == "collect"
    assert events[-1]["status"] == "failed"
    assert events[-1]["stage"] == "market_collect"
    assert "secret" not in str(events)
    with db[0].connect() as conn:
        payload = conn.scalar(
            sa.select(operations_events.c.payload).where(
                operations_events.c.kind == "newsletter_prepare"
            )
        )
    assert payload["status"] == "failed"
    assert payload["failed_stage"] == "market_collect"
    assert payload["finished_at"]
    assert service.prepare()["reused"] and calls == ["calendar", "market"]


def test_claim_failure_is_logged_before_any_provider_call(db, monkeypatch):
    service, _clock, calls, ai = setup(db)
    events = []
    service.observe = events.append

    def fail(_day):
        raise RuntimeError("private-storage-details")

    monkeypatch.setattr(service.preparations, "claim", fail)
    result = service.prepare()
    assert result["status"] == "failed"
    assert result["failed_stage"] == "claim"
    assert events[-1]["exception_type"] == "RuntimeError"
    assert not calls and not ai.calls
    assert "private" not in str(events)


def test_restart_after_claim_does_not_repeat_unknown_side_effects(db):
    service, _clock, calls, _ai = setup(db)
    row, fresh = service.preparations.claim(db[1].target_date)
    assert fresh and row["status"] == "running"
    assert service.prepare()["status"] == "running" and not calls


@pytest.mark.parametrize(
    "scenario,failed_news,status",
    [
        ("zero", False, "ready"),
        ("partial", False, "partial"),
        ("failed", True, "failed"),
    ],
)
def test_normal_zero_partial_total_failure_are_preserved(
    db, scenario, failed_news, status
):
    service, _clock, _calls, _ai = setup(db, scenario=scenario, failed_news=failed_news)
    result = service.prepare()
    assert result["status"] == status
    if status == "failed":
        assert result["outbox_id"] is None


def test_expired_summary_prices_block_before_any_external_request(db):
    service, _clock, calls, _ai = setup(db)
    service.settings = replace(
        service.settings,
        limits=service.settings.limits.model_copy(
            update={"prices_valid_until": db[1].frozen_at}
        ),
    )
    assert service.prepare()["status"] == "failed" and not calls


def test_custom_monthly_budget_uses_shared_ledger(db):
    engine, data = db
    store = CappedWorkflowStore(engine, Decimal(1))
    limits = config(now=data.frozen_at).limits
    with engine.begin() as conn:
        conn.execute(
            usage_ledger.insert().values(
                id="existing-cost",
                provider="test",
                month="2026-11",
                state="confirmed",
                amount_krw=1,
                payload={},
            )
        )
    with pytest.raises(WorkflowError, match="MONTHLY_BUDGET_EXCEEDED"):
        store.reserve("must-not-reserve", limits, data.frozen_at)
    with engine.connect() as conn:
        assert conn.scalar(sa.select(sa.func.count()).select_from(usage_ledger)) == 1


def test_claim_snapshot_is_fixed_while_later_changes_are_not_backdated(db):
    service, clock, _calls, _ai = setup(db)
    snapshot, fresh = service.preparations.claim(db[1].target_date)
    assert fresh and snapshot["settings"]["revision"] == 1
    NotificationSettingsStore(db[0]).update(
        expected_revision=1, changes={"paused": True}, actor="test", now=clock[0]
    )
    clock[0] += timedelta(seconds=1)
    reused, fresh = service.preparations.claim(db[1].target_date)
    assert not fresh and reused["settings"] == snapshot["settings"]
    assert service.preparations.purge_expired(now=clock[0] + timedelta(days=89)) == 0
    assert service.preparations.purge_expired(now=clock[0] + timedelta(days=90)) == 1


def test_configuration_lock_wait_crossing_grace_fails_before_collection(db):
    engine, data = db
    times = iter(
        [data.frozen_at + timedelta(seconds=5), data.frozen_at + timedelta(minutes=1)]
    )
    store = PreparationStore(engine, clock=lambda: next(times))
    result, fresh = store.claim(data.target_date)
    assert not fresh and result["reason"] == "freeze_window_missed"


def test_unknown_news_identity_is_passed_to_selection_exclusions(db):
    from xfolio.db.newsletter_news import deliveries
    from xfolio.news.collection_store import NewsletterNewsStore, item_id
    from xfolio.news.contracts import digest

    service, clock, _calls, _ai = setup(db)
    data = demo_inputs(target_date=db[1].target_date - timedelta(days=1))
    NewsletterNewsStore(db[0]).save_result(data.news, now=data.news.finished_at)
    item = data.news.selected[0]
    with db[0].begin() as conn:
        conn.execute(
            deliveries.insert().values(
                id=digest("self:" + item_id(item)),
                item_id=item_id(item),
                recipient_scope="self",
                status="unknown",
                recorded_at=data.news.finished_at + timedelta(seconds=1),
            )
        )
    keys, _last = service._seen(clock[0])
    assert set(item.keys) <= keys


def test_last_success_uses_previous_news_cutoff_not_delivery_time(db):
    from xfolio.db.telegram import outbox

    service, clock, _calls, _ai = setup(db)
    result = service.prepare()
    with db[0].begin() as conn:
        conn.execute(
            outbox.update()
            .where(outbox.c.id == result["outbox_id"])
            .values(
                status="confirmed", updated_at=db[1].frozen_at + timedelta(minutes=12)
            )
        )
    _keys, last = service._seen(clock[0] + timedelta(days=1))
    assert last == db[1].frozen_at
