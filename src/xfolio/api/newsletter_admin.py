"""뉴스레터 관리자 읽기·설정 API. 외부 수집/송신과 DDL 실행 없음."""

from contextlib import nullcontext
from datetime import date
from typing import Annotated

import sqlalchemy as sa
from fastapi import Query, Request
from pydantic import Field, StrictBool

from xfolio.api.models import StrictModel
from xfolio.api.store import ApiError
from xfolio.db.domestic import calendar_days, instruments, watchlist
from xfolio.db.newsletter import editions
from xfolio.domestic.calendar import KST
from xfolio.domestic.models import DomesticError
from xfolio.domestic.store import DomesticStore
from xfolio.newsletter import MorningSettings, NewsletterError
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
        today = now.astimezone(KST).date()
        with self.engine.connect() as conn:
            opened = conn.scalar(
                sa.select(calendar_days.c.is_open).where(
                    calendar_days.c.observed_on == today,
                    calendar_days.c.trade_date == today,
                    calendar_days.c.retrieved_at <= now,
                )
            )
        return {
            "target_date": today,
            "market_open": opened,
            "settings": self.get_settings(),
            "watchlist": self.get_watchlist(),
            "newsletters": self.list_newsletters(now=now, day=today),
            "budget": {"status": "not_connected"},
            "price_freshness": {"status": "not_observed"},
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
