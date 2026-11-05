"""뉴스레터 관리자 읽기·설정 API. 외부 수집/송신과 DDL 실행 없음."""

import os
import re
from contextlib import nullcontext
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Annotated

import sqlalchemy as sa
from fastapi import Query, Request
from pydantic import Field, StrictBool, ValidationError

from xfolio.api.models import StrictModel
from xfolio.api.store import ApiError
from xfolio.db.domestic import (
    calendar_days,
    instruments,
    market_runs,
    price_snapshots,
    watchlist,
)
from xfolio.db.newsletter import editions
from xfolio.db.newsletter_news import items as news_items
from xfolio.db.newsletter_news import runs as news_runs
from xfolio.db.schema import operations_events, usage_ledger
from xfolio.domestic.calendar import KST, completed_sessions
from xfolio.domestic.models import CloseQuote, DomesticError
from xfolio.domestic.store import DomesticStore
from xfolio.newsletter import MorningSettings, NewsletterError, at
from xfolio.newsletter_news import aware
from xfolio.newsletter_store import NewsletterStore
from xfolio.notification_settings import (
    NotificationSettingsError,
    NotificationSettingsStore,
    record_audit,
)


class SettingsChange(StrictModel):
    expected_revision: int = Field(ge=1, strict=True)
    morning_enabled: StrictBool | None = None
    paused: StrictBool | None = None
    intraday_enabled: StrictBool | None = None
    close_enabled: StrictBool | None = None


class WatchlistChange(StrictModel):
    expected_revision: int = Field(ge=1, strict=True)
    codes: list[str] = Field(min_length=1, max_length=10)


class _TransactionEngine:
    """T02 서비스를 기존 트랜잭션에 묶어 변경·감사를 함께 commit한다."""

    def __init__(self, conn):
        self.conn, self.dialect = conn, conn.dialect

    def begin(self):
        return nullcontext(self.conn)


class NewsletterAdminStore:
    def __init__(self, engine):
        self.engine = engine
        self.domestic = DomesticStore(engine)
        self.settings = NotificationSettingsStore(engine)

    def get_settings(self):
        return self.settings.get()

    def update_settings(self, **kwargs):
        return self.settings.update(**kwargs)

    def search(self, query):
        return [i.model_dump(mode="json") for i in self.domestic.search(query)]

    def get_watchlist(self):
        with self.engine.connect() as conn:
            row = conn.execute(sa.select(watchlist)).mappings().one_or_none()
            if row is None:
                raise ApiError("WATCHLIST_NOT_INITIALIZED", 503)
            values = {
                r["code"]: dict(r)
                for r in conn.execute(
                    sa.select(instruments).where(instruments.c.code.in_(row["codes"]))
                ).mappings()
            }
            return {
                "revision": row["revision"],
                "codes": row["codes"],
                "items": [values[c] for c in row["codes"] if c in values],
                "max_active": 10,
            }

    def update_watchlist(self, *, expected_revision, codes, actor, now):
        with self.engine.begin() as conn:
            before = (
                conn.execute(
                    sa.select(watchlist).where(watchlist.c.id == 1).with_for_update()
                )
                .mappings()
                .one_or_none()
            )
            if before is None:
                raise ApiError("WATCHLIST_NOT_INITIALIZED", 503)
            revision = DomesticStore(_TransactionEngine(conn)).replace_watchlist(
                codes, expected_revision=expected_revision, now=now
            )
            if revision != before["revision"]:
                record_audit(
                    conn,
                    actor=actor,
                    kind="watchlist",
                    before={"codes": before["codes"]},
                    after={"codes": codes},
                    revision=revision,
                    now=now,
                )
        return self.get_watchlist()

    def list_newsletters(self, *, now, day=None, status=None, limit=50):
        query = sa.select(editions).where(
            editions.c.created_at <= now, editions.c.expires_at > now
        )
        if day:
            query = query.where(editions.c.target_date == day)
        if status:
            query = query.where(editions.c.status == status)
        with self.engine.connect() as conn:
            return [
                self._edition_summary(r)
                for r in conn.execute(
                    query.order_by(editions.c.target_date.desc(), editions.c.id).limit(
                        limit
                    )
                ).mappings()
            ]

    @staticmethod
    def _edition_summary(row):
        result = NewsletterStore._decode(row)
        return {
            "id": result.key,
            "target_date": result.target_date,
            "slot": result.slot,
            "status": result.status,
            "price_count": result.price_count,
            "news_count": result.news_count,
            "news_state": result.news_state,
            "market_open": result.market_open,
            "created_at": result.created_at,
            "expires_at": result.expires_at,
            "reasons": result.reasons,
            "settings_revision": result.settings.revision,
            "watchlist_revision": result.watchlist_revision,
            "mode": result.mode,
            "synthetic": result.synthetic,
        }

    def get_newsletter(self, key, *, now):
        result = NewsletterStore(self.engine).get(key, now=now)
        if result is None:
            raise ApiError("NEWSLETTER_NOT_FOUND", 404)
        return {"id": result.key, **result.model_dump(mode="json")}

    def list_deliveries(self, *, now, limit=50):
        try:
            from xfolio.jobs.outbox import TelegramOutboxStore
        except ModuleNotFoundError as exc:
            if exc.name not in {"xfolio.jobs", "xfolio.jobs.outbox"}:
                raise
            raise ApiError("DELIVERIES_NOT_CONNECTED", 503) from None
        return TelegramOutboxStore(self.engine).list_deliveries(now=now, limit=limit)

    def get_delivery(self, key, *, now):
        try:
            from xfolio.jobs.outbox import TelegramOutboxStore
        except ModuleNotFoundError as exc:
            if exc.name not in {"xfolio.jobs", "xfolio.jobs.outbox"}:
                raise
            raise ApiError("DELIVERIES_NOT_CONNECTED", 503) from None
        result = TelegramOutboxStore(self.engine).get_delivery(key, now=now)
        if result is None:
            raise ApiError("DELIVERY_NOT_FOUND", 404)
        return result

    def summary(self, *, now):
        now = aware(now)
        today = now.astimezone(KST).date()
        current_watchlist = self.get_watchlist()
        with self.engine.connect() as conn:
            opened = conn.scalar(
                sa.select(calendar_days.c.is_open).where(
                    calendar_days.c.observed_on == today,
                    calendar_days.c.trade_date == today,
                    calendar_days.c.retrieved_at <= now,
                )
            )
            if today.weekday() >= 5:
                opened = False
            budget = self._budget(conn, now)
            prices = self._price_freshness(conn, now, current_watchlist)
            news = self._news_collection(conn, now)
            worker = (
                conn.execute(
                    sa.select(operations_events)
                    .where(
                        operations_events.c.kind.in_(
                            ("newsletter_worker", "newsletter_prepare")
                        ),
                        operations_events.c.created_at <= now,
                        sa.or_(
                            operations_events.c.expires_at.is_(None),
                            operations_events.c.expires_at > now,
                        ),
                    )
                    .order_by(
                        operations_events.c.created_at.desc(), operations_events.c.id
                    )
                    .limit(1)
                )
                .mappings()
                .first()
            )
        recent = self.list_deliveries(now=now, limit=10)
        return {
            "target_date": today,
            "checked_at": now,
            "market_open": opened,
            "settings": self.get_settings(),
            "watchlist": current_watchlist,
            "newsletters": self.list_newsletters(now=now, day=today),
            "budget": budget,
            "price_freshness": prices,
            "news_collection": news,
            "deliveries": {
                "status": "observed" if recent else "not_observed",
                "recent": recent,
                "attention": [
                    r
                    for r in recent
                    if r["status"]
                    in {"failed", "partial", "unknown", "retryable_failure"}
                ],
                "scope": "latest_10_retained_deliveries",
            },
            "worker": {
                "stage": "preparation"
                if worker["kind"] == "newsletter_prepare"
                else "dispatch",
                "status": worker["payload"].get("status")
                if worker["payload"].get("status")
                in ("running", "ready", "partial", "complete", "failed", "skipped")
                else "unknown",
                "reason": self._safe_code(worker["payload"]["reason"])
                if worker["payload"].get("reason") is not None
                else None,
                "recorded_at": worker["created_at"],
            }
            if worker
            else {"status": "not_observed"},
        }

    @staticmethod
    def _safe_code(value):
        return (
            value
            if isinstance(value, str) and re.fullmatch(r"[a-zA-Z0-9_:-]{1,100}", value)
            else "unavailable_error_code"
        )

    @staticmethod
    def _budget(conn, now):
        month = now.astimezone(KST).strftime("%Y-%m")
        rows = conn.execute(
            sa.select(
                usage_ledger.c.state,
                sa.func.sum(usage_ledger.c.amount_krw),
                sa.func.count(),
            )
            .where(usage_ledger.c.month == month)
            .group_by(usage_ledger.c.state)
        ).all()
        totals = dict.fromkeys(
            ("estimated", "reserved", "confirmed", "released"), Decimal(0)
        )
        for state, amount, _count in rows:
            totals[state] = amount
        raw_limit = os.environ.get("XFOLIO_MONTHLY_BUDGET_KRW", "50000")
        try:
            limit = Decimal(raw_limit)
            if not limit.is_finite() or not 0 < limit <= 50000:
                raise ValueError
        except (InvalidOperation, ValueError):
            limit = None
        ledger_valid = all(
            value.is_finite() and value >= 0 for value in totals.values()
        )
        committed = (
            totals["confirmed"] + totals["reserved"] + totals["estimated"]
            if ledger_valid
            else None
        )
        return {
            "month": month,
            "status": "invalid_configuration"
            if limit is None
            else "invalid_ledger"
            if not ledger_valid
            else "over_limit"
            if committed > limit
            else "observed"
            if rows
            else "not_measured",
            "limit_krw": limit,
            "limit_source": "server_configuration"
            if "XFOLIO_MONTHLY_BUDGET_KRW" in os.environ
            else "policy_default",
            **{
                f"{state}_krw": value if ledger_valid else None
                for state, value in totals.items()
            },
            "committed_krw": committed,
            "remaining_krw": max(Decimal(0), limit - committed)
            if limit is not None and committed is not None
            else None,
            "record_count": sum(row[2] for row in rows),
            "scope": "recorded_usage_ledger_only",
            "billing_reconciled": False,
        }

    def _price_freshness(self, conn, now, current):
        today = now.astimezone(KST).date()
        calendar = {
            r["trade_date"]: r["is_open"]
            for r in conn.execute(
                sa.select(calendar_days).where(
                    calendar_days.c.observed_on == today,
                    calendar_days.c.retrieved_at <= now,
                )
            ).mappings()
        }
        try:
            previous, latest = completed_sessions(now, calendar)
        except DomesticError as exc:
            return {
                "status": "calendar_unverified",
                "reason": self._safe_code(str(exc)),
                "items": [],
                "reference_at": now,
            }
        run = (
            conn.execute(
                sa.select(market_runs)
                .where(
                    market_runs.c.watchlist_revision == current["revision"],
                    market_runs.c.finished_at <= now,
                )
                .order_by(market_runs.c.finished_at.desc(), market_runs.c.id)
                .limit(1)
            )
            .mappings()
            .first()
        )
        result = {
            "status": "not_observed",
            "expected_trade_date": latest.trade_date,
            "comparison_trade_date": previous.trade_date,
            "reference_at": now,
            "items": [],
        }
        if run is None:
            return result
        provenance = self._run_provenance(conn, now, "market_run_id", run["id"])
        observations = {o["code"]: o for o in run["observations"]}
        for code in current["codes"]:
            observation = observations.get(code)
            row = (
                conn.execute(
                    sa.select(price_snapshots).where(
                        price_snapshots.c.id == observation["snapshot_id"]
                    )
                )
                .mappings()
                .one_or_none()
                if observation
                else None
            )
            item = {"code": code, "status": "missing", "provenance": provenance}
            if row is None:
                result["items"].append(item)
                continue
            if row["expires_at"] <= now:
                item["status"] = "expired"
                result["items"].append(item)
                continue
            try:
                quote = CloseQuote.model_validate(row["payload"])
                retrieved_at = aware(
                    datetime.fromisoformat(observation["retrieved_at"])
                )
                if (
                    quote.code != code
                    or quote.content_hash != row["content_hash"]
                    or quote.latest.trade_date != row["trade_date"]
                    or quote.latest.price_as_of != row["price_as_of"]
                    or quote.latest.scheduled_close != row["scheduled_close"]
                    or not row["first_stored_at"] <= now
                    or not run["started_at"] <= retrieved_at <= run["finished_at"]
                ):
                    raise ValueError
                item.update(
                    trade_date=row["trade_date"],
                    comparison_trade_date=quote.previous.trade_date,
                    price_as_of=row["price_as_of"],
                    scheduled_close=row["scheduled_close"],
                    retrieved_at=retrieved_at,
                    version=row["version"],
                    change_available=row["change_pct"] is not None,
                    delay_status="not_measured",
                    source="KIS",
                )
                max_version = conn.scalar(
                    sa.select(sa.func.max(price_snapshots.c.version)).where(
                        price_snapshots.c.code == code,
                        price_snapshots.c.trade_date == row["trade_date"],
                        price_snapshots.c.first_stored_at <= now,
                    )
                )
                item["status"] = (
                    "superseded"
                    if row["version"] != max_version
                    else "stale"
                    if row["trade_date"] != latest.trade_date
                    or quote.previous.trade_date != previous.trade_date
                    or quote.latest.scheduled_close != latest.scheduled_close
                    or quote.previous.scheduled_close != previous.scheduled_close
                    else "corrected"
                    if row["version"] > 1
                    else "current"
                )
            except (ValidationError, ValueError, KeyError, TypeError):
                item = {"code": code, "status": "invalid", "provenance": provenance}
            result["items"].append(item)
        statuses = [item["status"] for item in result["items"]]
        result.update(
            status="synthetic"
            if provenance == "synthetic"
            else "provenance_unverified"
            if provenance != "live"
            else "current"
            if all(s == "current" for s in statuses)
            else "attention",
            collection_status=run["status"],
            run_id=run["id"],
            finished_at=run["finished_at"],
            provenance=provenance,
        )
        return result

    @staticmethod
    def _run_provenance(conn, now, field, run_id):
        row = (
            conn.execute(
                sa.select(editions)
                .where(
                    editions.c.payload[field].astext == run_id,
                    editions.c.created_at <= now,
                    editions.c.expires_at > now,
                )
                .order_by(editions.c.created_at.desc())
                .limit(1)
            )
            .mappings()
            .first()
        )
        if row is None:
            return "unverified"
        try:
            edition = NewsletterStore._decode(row)
        except (NewsletterError, ValidationError):
            return "unverified"
        return (
            "synthetic"
            if edition.synthetic
            else "live"
            if edition.mode == "live"
            else "dry_run"
        )

    @staticmethod
    def _news_collection(conn, now):
        run = (
            conn.execute(
                sa.select(news_runs)
                .where(news_runs.c.finished_at <= now, news_runs.c.expires_at > now)
                .order_by(news_runs.c.finished_at.desc(), news_runs.c.id)
                .limit(1)
            )
            .mappings()
            .first()
        )
        if run is None:
            return {"status": "not_observed", "sources": []}
        payload = run["payload"]
        selected = payload.get("selected", [])
        metadata = (
            conn.execute(
                sa.select(news_items.c.payload).where(
                    news_items.c.id.in_(selected), news_items.c.expires_at > now
                )
            )
            .scalars()
            .all()
        )
        current = run["as_of"] == at(now.astimezone(KST).date(), 7, 50)
        return {
            "status": run["status"],
            "current": current,
            "run_id": run["id"],
            "as_of": run["as_of"],
            "finished_at": run["finished_at"],
            "normal_zero": run["status"] == "complete" and len(selected) == 0,
            "selected_count": len(selected),
            "retained_selected_count": len(metadata),
            "synthetic": any(row.get("synthetic") is True for row in metadata),
            "provenance": NewsletterAdminStore._run_provenance(
                conn, now, "news_run_id", run["id"]
            ),
            "sources": [
                {
                    "provider": source.get("provider"),
                    "status": source.get("status"),
                    "errors": [
                        NewsletterAdminStore._safe_code(error)
                        for error in source.get("errors", [])
                    ],
                }
                for source in payload.get("sources", [])
            ],
            "excluded": {
                NewsletterAdminStore._safe_code(key): count
                for key, count in payload.get("excluded", {}).items()
                if type(count) is int and count >= 0
            },
        }


def install_routes(app, *, session, clock, store):
    def ready(request, change=False):
        operator = session(request, change=change)
        if store is None:
            raise ApiError("NEWSLETTER_ADMIN_NOT_CONNECTED", 503)
        return operator

    @app.exception_handler(NotificationSettingsError)
    async def settings_error(request, exc):
        from fastapi.responses import JSONResponse

        code = str(exc)
        status = (
            409
            if code in {"revision_conflict", "afternoon_not_accepted"}
            else 503
            if code == "settings_not_initialized"
            else 422
        )
        return JSONResponse(
            {
                "error": {
                    "code": code.upper(),
                    "message": "설정과 최신 버전을 확인한 뒤 다시 시도하세요.",
                }
            },
            status_code=status,
        )

    @app.exception_handler(NewsletterError)
    async def newsletter_error(request, exc):
        from fastapi.responses import JSONResponse

        return JSONResponse(
            {
                "error": {
                    "code": "NEWSLETTER_INTEGRITY_ERROR",
                    "message": "뉴스레터 저장 자료를 확인할 수 없습니다.",
                }
            },
            status_code=503,
        )

    @app.exception_handler(DomesticError)
    async def domestic_error(request, exc):
        from fastapi.responses import JSONResponse

        return JSONResponse(
            {
                "error": {
                    "code": str(exc).upper(),
                    "message": "종목 지원 여부·한도·최신 버전을 확인하세요.",
                }
            },
            status_code=409,
        )

    @app.get("/api/notification-settings", response_model=MorningSettings)
    def get_settings(request: Request):
        ready(request)
        return store.get_settings()

    @app.patch("/api/notification-settings", response_model=MorningSettings)
    def update_settings(request: Request, body: SettingsChange):
        operator = ready(request, True)
        changes = body.model_dump(exclude={"expected_revision"}, exclude_unset=True)
        return store.update_settings(
            expected_revision=body.expected_revision,
            changes=changes,
            actor=operator["email"],
            now=clock(),
        )

    @app.get("/api/instruments")
    def search(request: Request, q: str = Query(min_length=1, max_length=120)):
        ready(request)
        return {"items": store.search(q)}

    @app.get("/api/watchlist")
    def get_watchlist(request: Request):
        ready(request)
        return store.get_watchlist()

    @app.put("/api/watchlist")
    def update_watchlist(request: Request, body: WatchlistChange):
        operator = ready(request, True)
        return store.update_watchlist(
            expected_revision=body.expected_revision,
            codes=body.codes,
            actor=operator["email"],
            now=clock(),
        )

    @app.get("/api/newsletters")
    def list_newsletters(
        request: Request,
        day: Annotated[date | None, Query(alias="date")] = None,
        status: Annotated[
            str | None, Query(pattern="^(ready|partial|failed|skipped)$")
        ] = None,
        limit: int = Query(default=50, ge=1, le=50),
    ):
        ready(request)
        return {
            "items": store.list_newsletters(
                now=clock(), day=day, status=status, limit=limit
            )
        }

    @app.get("/api/newsletters/{key}")
    def detail(request: Request, key: str):
        ready(request)
        return store.get_newsletter(key, now=clock())

    @app.get("/api/deliveries")
    def deliveries(request: Request, limit: int = Query(default=50, ge=1, le=50)):
        ready(request)
        return {"items": store.list_deliveries(now=clock(), limit=limit)}

    @app.get("/api/deliveries/{key}")
    def delivery(request: Request, key: str):
        ready(request)
        return store.get_delivery(key, now=clock())

    @app.get("/api/newsletter-operations/summary")
    def summary(request: Request):
        ready(request)
        return store.summary(now=clock())
