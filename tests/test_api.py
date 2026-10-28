"""외부 호출 없는 인증/조회 API 시험. 저장/동시성은 PostgreSQL 시험과 별도다."""

from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from xfolio.api.app import COOKIE, FLOW_COOKIE, create_app
from xfolio.api.auth import Settings
from xfolio.api.store import token_hash

NOW = datetime(2026, 10, 28, 8, 50, tzinfo=UTC)


class AuthStoreDouble:
    def __init__(self):
        self.events = {}

    def put_event(self, kind, key, payload, now, expires):
        self.events[kind, token_hash(key)] = (dict(payload), expires)

    def take_event(self, kind, key, now):
        item = self.events.pop((kind, token_hash(key)), None)
        return item[0] if item and item[1] > now else None

    def get_session(self, key, now):
        item = self.events.get(("session", token_hash(key)))
        if not item or item[1] <= now:
            return None
        data = item[0]
        if datetime.fromisoformat(data["last_seen"]) + timedelta(minutes=30) <= now:
            return None
        data["last_seen"] = now.isoformat()
        return data

    def list_drafts(self, *args):
        return []


class GoogleDouble:
    def __init__(self):
        self.claims = {
            "iss": "https://accounts.google.com",
            "sub": "test-operator",
            "email": "owner@example.invalid",
            "email_verified": True,
            "exp": NOW.timestamp() + 3600,
            "name": "Operator",
        }
        self.last_nonce = None

    async def authorize(self, state, nonce):
        self.last_nonce = nonce
        return f"https://accounts.google.com/test?state={state}"

    async def verify(self, code, nonce, now):
        assert code == "code" and nonce == self.last_nonce
        return self.claims


@pytest.fixture
def api():
    settings = Settings(
        origin="https://testserver",
        google_client_id="id",
        google_client_secret="secret",
        allowed_emails=("owner@example.invalid",),
        cursor_secret="c" * 32,
    )
    store, google = AuthStoreDouble(), GoogleDouble()
    current = [NOW]
    with TestClient(
        create_app(settings, store, google, lambda: current[0]),
        base_url=settings.origin,
    ) as client:
        yield client, store, google, current


def sign_in(client):
    result = client.get("/api/auth/login", follow_redirects=False)
    assert result.status_code == 307
    state = parse_qs(urlsplit(result.headers["location"]).query)["state"][0]
    response = client.get(
        "/api/auth/callback",
        params={"state": state, "code": "code"},
        follow_redirects=False,
    )
    return response, state


def test_default_app_is_closed():
    with TestClient(create_app(Settings()), base_url="https://testserver") as client:
        assert client.get("/api/auth/login").status_code == 503
        assert client.get("/api/drafts").status_code == 503


def test_login_session_me_csrf_logout(api):
    client, store, _, _ = api
    assert client.get("/api/auth/me").status_code == 401
    response, state = sign_in(client)
    assert response.status_code == 307
    cookie = response.headers["set-cookie"]
    assert "Secure" in cookie and "HttpOnly" in cookie and "SameSite=lax" in cookie
    me = client.get("/api/auth/me")
    assert me.status_code == 200 and me.headers["cache-control"] == "no-store"
    assert me.json()["operator"]["email"] == "owner@example.invalid"
    assert not any("id_token" in str(value) for value in store.events.values())
    assert client.get("/api/drafts").json() == {"items": [], "next_cursor": None}
    assert client.post("/api/auth/logout").status_code == 403
    assert (
        client.post(
            "/api/auth/logout",
            headers={
                "Origin": "https://evil.invalid",
                "X-CSRF-Token": me.json()["csrf_token"],
            },
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/auth/logout",
            headers={
                "Origin": "https://testserver",
                "X-CSRF-Token": me.json()["csrf_token"],
            },
        ).status_code
        == 204
    )
    assert client.get("/api/auth/me").status_code == 401
    assert (
        client.get(
            "/api/auth/callback", params={"state": state, "code": "code"}
        ).status_code
        == 403
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("email_verified", False),
        ("email", "other@example.invalid"),
        ("iss", "https://evil.invalid"),
        ("exp", 0),
    ],
)
def test_disallowed_google_claims(api, field, value):
    client, _, google, _ = api
    google.claims[field] = value
    response, _ = sign_in(client)
    assert response.status_code == 403
    assert COOKIE not in client.cookies


def test_oauth_flow_browser_binding(api):
    client, _, _, _ = api
    response = client.get("/api/auth/login", follow_redirects=False)
    state = parse_qs(urlsplit(response.headers["location"]).query)["state"][0]
    client.cookies.clear()
    assert (
        client.get(
            "/api/auth/callback", params={"state": state, "code": "code"}
        ).status_code
        == 403
    )


def test_session_idle_expiry_and_cursor_validation(api):
    client, _, _, current = api
    sign_in(client)
    assert client.get("/api/drafts?cursor=tampered").status_code == 422
    assert client.get("/api/drafts?limit=51").status_code == 422
    current[0] += timedelta(minutes=30)
    assert client.get("/api/auth/me").status_code == 401


def test_missing_state_or_flow_cookie_cannot_login(api):
    client, _, _, _ = api
    client.cookies.set(FLOW_COOKIE, "fake")
    assert client.get("/api/auth/callback?state=fake&code=code").status_code == 403


@pytest.mark.parametrize(
    "origin",
    [
        "http://testserver",
        "https://testserver/path",
        "https://u:p@testserver",
        "https://testserver?x=1",
    ],
)
def test_public_origin_is_strict(origin):
    config = Settings(
        origin=origin,
        google_client_id="id",
        google_client_secret="secret",
        allowed_emails=("owner",),
        cursor_secret="c" * 32,
    )
    assert not config.auth_ready


def test_openapi_has_exact_eight_routes():
    schema = create_app(Settings()).openapi()
    assert len(schema["paths"]) == 8
    assert schema["paths"]["/api/drafts/{id}/decision"]["post"]["requestBody"]


def test_committed_openapi_matches_runtime():
    import json
    from pathlib import Path

    saved = json.loads(
        (Path(__file__).parents[1] / "contracts/openapi.json").read_text(
            encoding="utf-8"
        )
    )
    assert saved == create_app(Settings()).openapi()
