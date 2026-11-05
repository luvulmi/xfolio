"""서버 설정과 날짜별 DB claim으로 T02→T03→T04 실제 수집을 연결한다."""

import os
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import httpx
import sqlalchemy as sa

from xfolio.db.domestic import instruments, watchlist
from xfolio.db.newsletter import editions
from xfolio.db.newsletter_news import deliveries, items
from xfolio.db.notification_settings import settings as settings_table
from xfolio.db.schema import operations_events, usage_ledger
from xfolio.db.telegram import outbox
from xfolio.domestic.calendar import KST
from xfolio.domestic.kis import KisClient, KisSettings
from xfolio.domestic.models import Instrument
from xfolio.domestic.store import DomesticStore
from xfolio.news_generation import OpenAIGenerationClient
from xfolio.news_workflow import GenerationLimits, SQLWorkflowStore, WorkflowError
from xfolio.newsletter import MorningInputs, MorningSettings, at, fingerprint
from xfolio.newsletter_news import NewsError, aware, collect, summarize
from xfolio.newsletter_news_store import NewsletterNewsStore
from xfolio.newsletter_store import NewsletterStore
from xfolio.notification_settings import NotificationSettingsStore


class CollectionError(ValueError):
    """원문·키·연결 문자열 없는 고정 오류 코드."""


@dataclass(frozen=True)
class LiveCollectionSettings:
    kis: KisSettings = field(repr=False)
    finnhub_key: str = field(repr=False)
    openai_key: str = field(repr=False)
    limits: GenerationLimits
    recipient_scope: str = "self"
    monthly_limit: Decimal = Decimal(50000)

    @classmethod
    def from_env(cls):
        try:
            limits_file = os.environ.get("XFOLIO_GENERATION_LIMITS_FILE", "")
            if not limits_file:
                raise CollectionError("generation_limits_file_required")
            limits = GenerationLimits.model_validate_json(
                Path(limits_file).read_text(encoding="utf-8")
            )
            value = cls(
                kis=KisSettings(
                    os.environ.get("KIS_APP_KEY", ""),
                    os.environ.get("KIS_APP_SECRET", ""),
                    os.environ.get(
                        "KIS_BASE_URL", "https://openapi.koreainvestment.com:9443"
                    ).rstrip("/"),
                ),
                finnhub_key=os.environ.get("FINNHUB_API_KEY", ""),
                openai_key=os.environ.get("OPENAI_API_KEY", ""),
                limits=limits,
                recipient_scope=os.environ.get("XFOLIO_RECIPIENT_SCOPE", "self"),
                monthly_limit=Decimal(
                    os.environ.get("XFOLIO_MONTHLY_BUDGET_KRW", "50000")
                ),
            )
            value.validate(datetime.now(UTC))
            return value
        except CollectionError:
            raise
        except (OSError, ValueError, ArithmeticError):
            raise CollectionError("collection_configuration_invalid") from None

    def validate(self, now):
        if not self.finnhub_key.strip() or not self.openai_key.strip():
            raise CollectionError("news_and_summary_keys_required")
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", self.recipient_scope):
            raise CollectionError("recipient_scope_invalid")
        if not self.monthly_limit.is_finite() or not 0 < self.monthly_limit <= 50000:
            raise CollectionError("monthly_limit_invalid")
        if self.limits.prices_valid_until <= aware(now):
            raise CollectionError("generation_prices_expired")


class PreparationStore:
    """07:50 설정 고정과 외부 호출 전 단일 claim. 자동 재수집은 하지 않는다."""

    def __init__(
        self, engine, *, recipient_scope="self", clock=lambda: datetime.now(UTC)
    ):
        self.engine, self.recipient_scope, self.clock = engine, recipient_scope, clock

    def key(self, day):
        return fingerprint(
            ["newsletter_prepare", self.recipient_scope, day.isoformat(), "morning"]
        )

    def claim(self, day):
        key, cutoff = self.key(day), at(day, 7, 50)
        with self.engine.begin() as conn:
            conn.execute(sa.text("SELECT pg_advisory_xact_lock(718435909)"))
            old = (
                conn.execute(
                    sa.select(operations_events)
                    .where(operations_events.c.id == key)
                    .with_for_update()
                )
                .mappings()
                .one_or_none()
            )
            if old is not None:
                return dict(old["payload"]), False
            now = aware(self.clock())
            if now < cutoff:
                return {"status": "failed", "reason": "before_freeze_window"}, False
            reason = None
            snapshot = {}
            if day.weekday() >= 5:
                reason = "weekend"
            elif not cutoff <= now < cutoff + timedelta(minutes=1):
                reason = "freeze_window_missed"
            else:
                current = NotificationSettingsStore(self.engine).get(
                    conn=conn, for_update=True
                )
                settings_at = conn.scalar(
                    sa.select(settings_table.c.updated_at).where(
                        settings_table.c.id == 1
                    )
                )
                row = (
                    conn.execute(
                        sa.select(watchlist)
                        .where(watchlist.c.id == 1)
                        .with_for_update()
                    )
                    .mappings()
                    .one_or_none()
                )
                if row is None:
                    reason = "watchlist_not_initialized"
                elif settings_at > cutoff or row["updated_at"] > cutoff:
                    reason = "configuration_changed_after_freeze"
                elif not current.morning_enabled or current.paused:
                    reason = "disabled_or_paused"
                else:
                    rows = (
                        conn.execute(
                            sa.select(instruments)
                            .where(instruments.c.code.in_(row["codes"]))
                            .order_by(instruments.c.code)
                            .with_for_update()
                        )
                        .mappings()
                        .all()
                    )
                    catalogue = {
                        r["code"]: Instrument.model_validate(dict(r)) for r in rows
                    }
                    if any(
                        c not in catalogue
                        or not catalogue[c].eligible
                        or catalogue[c].retrieved_at > cutoff
                        for c in row["codes"]
                    ):
                        reason = "instrument_unverified_at_freeze"
                    else:
                        snapshot = {
                            "settings": current.model_dump(mode="json"),
                            "watchlist_revision": row["revision"],
                            "codes": list(row["codes"]),
                            "instruments": [
                                catalogue[c].model_dump(mode="json")
                                for c in row["codes"]
                            ],
                        }
            now = aware(self.clock())
            if not reason and not cutoff <= now < cutoff + timedelta(minutes=1):
                reason, snapshot = "freeze_window_missed", {}
            payload = {
                "target_date": day.isoformat(),
                "frozen_at": cutoff.isoformat(),
                "claimed_at": now.isoformat(),
                "status": "running"
                if reason is None
                else "skipped"
                if reason in {"weekend", "disabled_or_paused"}
                else "failed",
                "reason": reason,
                **snapshot,
            }
            conn.execute(
                operations_events.insert().values(
                    id=key,
                    kind="newsletter_prepare",
                    scope=self.recipient_scope,
                    unique_key=day.isoformat(),
                    created_at=now,
                    expires_at=now + timedelta(days=90),
                    payload=payload,
                )
            )
            return payload, reason is None

    def finish(self, day, result):
        with self.engine.begin() as conn:
            row = (
                conn.execute(
                    sa.select(operations_events)
                    .where(operations_events.c.id == self.key(day))
                    .with_for_update()
                )
                .mappings()
                .one()
            )
            payload = dict(row["payload"])
            payload.update(result)
            payload["finished_at"] = aware(self.clock()).isoformat()
            conn.execute(
                operations_events.update()
                .where(operations_events.c.id == row["id"])
                .values(payload=payload)
            )
            return payload

    def purge_expired(self, *, now):
        with self.engine.begin() as conn:
            return conn.execute(
                operations_events.delete().where(
                    operations_events.c.kind == "newsletter_prepare",
                    operations_events.c.expires_at <= aware(now),
                )
            ).rowcount


class CappedWorkflowStore(SQLWorkflowStore):
    """기존 비용 원장을 사용하며 서버의 더 낮은 월 한도도 같은 잠금으로 검사."""

    def __init__(self, engine, monthly_limit):
        super().__init__(engine)
        self.monthly_limit = monthly_limit

    def reserve(self, request_id, limits, now):
        with self.engine.begin() as conn:
            conn.execute(sa.text("SELECT pg_advisory_xact_lock(718435902)"))
            month = aware(now).astimezone(KST).strftime("%Y-%m")
            used = conn.scalar(
                sa.select(
                    sa.func.coalesce(sa.func.sum(usage_ledger.c.amount_krw), 0)
                ).where(
                    usage_ledger.c.month == month,
                    usage_ledger.c.state.in_(["estimated", "reserved", "confirmed"]),
                )
            )
            if used + limits.maximum_cost > self.monthly_limit:
                raise WorkflowError("MONTHLY_BUDGET_EXCEEDED")
            conn.execute(
                usage_ledger.insert().values(
                    id=request_id,
                    provider="OpenAI",
                    month=month,
                    state="reserved",
                    amount_krw=limits.maximum_cost,
                    payload={
                        "purpose": "news_generation",
                        "model": limits.model,
                        "price_basis": limits.price_basis,
                        "max_output_tokens": limits.max_output_tokens,
                    },
                )
            )


class LiveMorningPreparation:
    def __init__(
        self,
        engine,
        *,
        kis,
        news_client,
        summary,
        settings,
        outbox_store,
        news_collector=collect,
        clock=lambda: datetime.now(UTC),
    ):
        self.engine, self.kis, self.news_client = engine, kis, news_client
        self.summary, self.settings, self.outbox_store = summary, settings, outbox_store
        self.news_collector, self.clock = news_collector, clock
        self.preparations = PreparationStore(
            engine, recipient_scope=settings.recipient_scope, clock=clock
        )
        self.domestic, self.news = DomesticStore(engine), NewsletterNewsStore(engine)
        self.newsletters = NewsletterStore(engine)

    def calendar(self, day, now):
        # Reuse the verified same-day KIS cache; no news or price call occurs here.
        try:
            return self.kis.holidays(now).get(day)
        except ValueError:
            return None

    def _seen(self, cutoff):
        with self.engine.connect() as conn:
            rows = conn.scalars(
                sa.select(items.c.identity_keys)
                .join(deliveries)
                .where(
                    deliveries.c.recipient_scope == self.settings.recipient_scope,
                    deliveries.c.status.in_(["confirmed", "unknown"]),
                    deliveries.c.recorded_at <= cutoff,
                    items.c.expires_at > cutoff,
                )
            )
            keys = frozenset(k for row in rows for k in row)
            last = conn.scalar(
                sa.select(
                    sa.func.max(
                        sa.cast(
                            editions.c.payload["frozen_at"].astext,
                            sa.DateTime(timezone=True),
                        )
                    )
                )
                .join(outbox, outbox.c.edition_id == editions.c.id)
                .where(
                    outbox.c.recipient_scope == self.settings.recipient_scope,
                    outbox.c.transport_mode == "live",
                    outbox.c.status == "confirmed",
                    outbox.c.updated_at <= cutoff,
                )
            )
        return keys, last

    def prepare(self):
        now = aware(self.clock())
        day = now.astimezone(KST).date()
        snapshot, fresh = self.preparations.claim(day)
        if not fresh:
            return {
                k: v
                for k, v in snapshot.items()
                if k in {"status", "reason", "edition_id", "outbox_id"}
            } | {"reused": True}
        try:
            self.settings.validate(self.clock())
            opened = self.kis.holidays(now)
            self.domestic.save_calendar(opened, self.clock())
            if opened.get(day) is not True:
                return self.preparations.finish(
                    day,
                    {
                        "status": "skipped" if opened.get(day) is False else "failed",
                        "reason": "market_closed"
                        if opened.get(day) is False
                        else "calendar_unverified",
                    },
                )
            cutoff = at(day, 7, 50)
            market = self.kis.collect(
                tuple(snapshot["codes"]),
                as_of=cutoff,
                watchlist_revision=snapshot["watchlist_revision"],
            )
            market_row = self.domestic.save_collection(market, now=self.clock())
            if aware(self.clock()) >= at(day, 8, 10):
                raise CollectionError("preparation_deadline_passed")
            seen, last_success = self._seen(cutoff)
            news = self.news_collector(
                self.news_client,
                api_key=self.settings.finnhub_key,
                as_of=cutoff,
                clock=self.clock,
                seen_keys=seen,
                last_success=last_success,
                summary=self.summary,
            )
            self.news.save_result(news, now=self.clock())
            inputs = MorningInputs(
                target_date=day,
                recipient_scope=self.settings.recipient_scope,
                frozen_at=cutoff,
                settings=MorningSettings.model_validate(snapshot["settings"]),
                watchlist_revision=snapshot["watchlist_revision"],
                instruments=tuple(snapshot["instruments"]),
                market_run_id=market_row["run_id"],
                market=market,
                calendar_opened=opened,
                news=news,
                mode="live",
                synthetic=False,
            )
            edition = self.newsletters.save(inputs, now=self.clock())
            outbox_id = (
                self.outbox_store.enqueue(edition.key, now=self.clock(), mode="live")
                if edition.status in {"ready", "partial"}
                else None
            )
            return self.preparations.finish(
                day,
                {
                    "status": edition.status,
                    "reason": None,
                    "edition_id": edition.key,
                    "outbox_id": outbox_id,
                    "market_status": market.status,
                    "news_status": news.status,
                },
            )
        except Exception:  # noqa: BLE001 -- paid/request outcome may be unknown; never recollect automatically.
            self.preparations.finish(
                day,
                {"status": "failed", "reason": "preparation_failed_no_automatic_retry"},
            )
            return {
                "status": "failed",
                "reason": "preparation_failed_no_automatic_retry",
            }


class LiveCollectionResources:
    """클라이언트는 서버 환경에서만 생성하며 생성 시점에는 외부 요청하지 않는다."""

    def __init__(
        self, engine, *, settings, outbox_store, clock=lambda: datetime.now(UTC)
    ):
        from openai import OpenAI

        self.http = httpx.Client(timeout=20, follow_redirects=False, trust_env=False)
        self.kis = KisClient(
            settings.kis, clock=clock, calendar_cache=DomesticStore(engine)
        )
        self.ai = OpenAI(
            api_key=settings.openai_key,
            base_url="https://api.openai.com/v1",
            timeout=30,
            max_retries=0,
        )
        ai = OpenAIGenerationClient(self.ai)
        usage = CappedWorkflowStore(engine, settings.monthly_limit)

        def summary(item):
            now = aware(clock())
            if now >= at(now.astimezone(KST).date(), 8, 10):
                raise NewsError("summary_send_deadline_passed")
            return summarize(
                item, client=ai, store=usage, limits=settings.limits, now=now
            )

        self.preparation = LiveMorningPreparation(
            engine,
            kis=self.kis,
            news_client=self.http,
            summary=summary,
            settings=settings,
            outbox_store=outbox_store,
            clock=clock,
        )

    def close(self):
        self.kis.close()
        self.http.close()
        self.ai.close()
