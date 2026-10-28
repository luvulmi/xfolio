"""XFolio 8개 관리자 API. 환경 설정 전에는 503으로 차단한다."""

import secrets
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Literal

import httpx
from authlib.common.errors import AuthlibBaseError
from fastapi import FastAPI, Header, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from itsdangerous import BadSignature, URLSafeTimedSerializer
from sqlalchemy.exc import SQLAlchemyError

from xfolio.api.auth import GoogleProvider, Settings, new_session
from xfolio.api.models import (
    DecisionRequest,
    DecisionResult,
    DraftDetail,
    DraftList,
    DraftSummary,
    Me,
    OperationsSummary,
    Status,
)
from xfolio.api.store import ApiError, PostgresStore

COOKIE = "xfolio_session"
FLOW_COOKIE = "xfolio_oidc_flow"


def create_app(settings=None, store=None, provider=None, clock=None):
    settings = settings or Settings.from_env()
    if store is None and settings.database_url:
        store = PostgresStore(settings.database_url)
    provider = provider or GoogleProvider(settings)
    clock = clock or (lambda: datetime.now(UTC))
    app = FastAPI(title="XFolio 관리자 API", version="0.1.0")
    app.state.store = store

    @app.middleware("http")
    async def private_response(request, call_next):
        try:
            response = await call_next(request)
        except SQLAlchemyError:
            response = JSONResponse(
                {
                    "error": {
                        "code": "STORAGE_UNAVAILABLE",
                        "message": "저장소를 확인할 수 없습니다.",
                    }
                },
                status_code=503,
            )
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.exception_handler(ApiError)
    async def api_error(request, exc):
        return JSONResponse(
            {
                "error": {
                    "code": exc.code,
                    "message": "요청을 처리할 수 없습니다. 최신 상태를 확인하세요.",
                }
            },
            status_code=exc.status,
        )

    def ready():
        if store is None or not settings.auth_ready:
            raise ApiError("CONFIGURATION_REQUIRED", 503)

    def session(request, change=False):
        ready()
        token = request.cookies.get(COOKIE)
        data = store.get_session(token, clock()) if token else None
        if not data:
            raise ApiError("AUTH_REQUIRED", 401)
        if data["email"].casefold() not in {
            x.casefold() for x in settings.allowed_emails
        }:
            raise ApiError("OPERATOR_FORBIDDEN", 403)
        if change and (
            request.headers.get("origin") != settings.origin
            or not secrets.compare_digest(
                request.headers.get("x-csrf-token", ""), data["csrf_token"]
            )
        ):
            raise ApiError("CSRF_FAILED", 403)
        return data

    @app.get("/api/auth/login", response_class=RedirectResponse)
    async def login():
        ready()
        state, nonce, flow = (secrets.token_urlsafe(32) for _ in range(3))
        store.put_event(
            "oidc",
            state,
            {"nonce": nonce, "flow": flow},
            clock(),
            clock() + timedelta(minutes=10),
        )
        response = RedirectResponse(await provider.authorize(state, nonce))
        response.set_cookie(
            FLOW_COOKIE,
            flow,
            max_age=600,
            secure=True,
            httponly=True,
            samesite="lax",
            path="/api/auth",
        )
        return response

    @app.get("/api/auth/callback", response_class=RedirectResponse)
    async def callback(
        request: Request,
        state: str = Query(min_length=1),
        code: str = Query(min_length=1),
    ):
        ready()
        data = store.take_event("oidc", state, clock())
        if not data or not secrets.compare_digest(
            request.cookies.get(FLOW_COOKIE, ""), data["flow"]
        ):
            raise ApiError("OIDC_STATE_INVALID", 403)
        try:
            claims = await provider.verify(code, data["nonce"], clock())
            token = new_session(store, settings, claims, clock())
        except ApiError:
            raise
        except (AuthlibBaseError, httpx.HTTPError, KeyError, ValueError):
            raise ApiError("OIDC_VERIFICATION_FAILED", 403) from None
        response = RedirectResponse("/")
        response.delete_cookie(
            FLOW_COOKIE, path="/api/auth", secure=True, httponly=True, samesite="lax"
        )
        response.set_cookie(
            COOKIE,
            token,
            max_age=43200,
            secure=True,
            httponly=True,
            samesite="lax",
            path="/api",
        )
        return response

    @app.get("/api/auth/me", response_model=Me)
    def me(request: Request):
        data = session(request)
        return {
            "operator": {"email": data["email"], "display_name": data["display_name"]},
            "mode": settings.mode,
            "csrf_token": data["csrf_token"],
            "allowed_actions": ["approve", "hold"]
            if settings.mode == "reviewed"
            else ["hold"],
        }

    @app.post("/api/auth/logout", status_code=204)
    def logout(request: Request):
        session(request, change=True)
        store.take_event("session", request.cookies[COOKIE], clock())
        response = Response(status_code=204)
        response.delete_cookie(
            COOKIE, path="/api", secure=True, httponly=True, samesite="lax"
        )
        return response

    @app.get("/api/drafts", response_model=DraftList)
    def drafts(
        request: Request,
        date_filter: Annotated[date | None, Query(alias="date")] = None,
        edition: Literal["AM", "PM"] | None = None,
        status: Status | None = None,
        limit: int = Query(default=20, ge=1, le=50),
        cursor: str | None = None,
    ):
        session(request)
        signer = URLSafeTimedSerializer(settings.cursor_secret, salt="draft-page")
        filters = [str(date_filter), edition, status]
        after = None
        if cursor:
            try:
                page = signer.loads(cursor, max_age=3600)
                if page["filters"] != filters or len(page["after"]) != 3:
                    raise ValueError
                after = page["after"]
                date.fromisoformat(after[0])
                if after[1] not in {"AM", "PM"} or not isinstance(after[2], str):
                    raise ValueError
            except (BadSignature, ValueError, KeyError, TypeError):
                raise ApiError("CURSOR_INVALID", 422) from None
        rows = store.list_drafts(
            settings.mode, date_filter, edition, status, after, limit + 1
        )
        items = [
            DraftSummary.model_validate(
                {
                    key: value
                    for key, value in row.items()
                    if key in DraftSummary.model_fields
                }
            )
            for row in rows[:limit]
        ]
        next_cursor = (
            signer.dumps(
                {
                    "filters": filters,
                    "after": [
                        str(rows[limit - 1]["target_date"]),
                        rows[limit - 1]["edition"],
                        rows[limit - 1]["id"],
                    ],
                }
            )
            if limit < len(rows)
            else None
        )
        return {"items": items, "next_cursor": next_cursor}

    @app.get("/api/drafts/{id}", response_model=DraftDetail)
    def detail(id: str, request: Request):
        session(request)
        return store.detail(id, settings.mode)

    @app.post("/api/drafts/{id}/decision", response_model=DecisionResult)
    def decision(
        id: str,
        request: Request,
        body: DecisionRequest,
        idempotency_key: Annotated[str, Header(min_length=1, max_length=128)],
    ):
        data = session(request, change=True)
        return store.decide(
            id, data["email"], idempotency_key, body, settings.mode, clock()
        )

    @app.get("/api/operations/summary", response_model=OperationsSummary)
    def summary(request: Request):
        session(request)
        return store.summary()

    return app


app = create_app()
