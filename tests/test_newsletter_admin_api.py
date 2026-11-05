"""외부 연결 없이 신규 관리자 세션·CSRF·revision·허용 입력 검사."""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from test_api import NOW, AuthStoreDouble, GoogleDouble, sign_in

from xfolio.api.app import create_app
from xfolio.api.auth import Settings
from xfolio.api.store import ApiError
from xfolio.newsletter import MorningSettings
from xfolio.notification_settings import NotificationSettingsError


class AdminDouble:
    def __init__(self):
        self.settings = MorningSettings(revision=1)
        self.changes = []

    def get_settings(self):
        return self.settings

    def update_settings(self, **kwargs):
        if kwargs["expected_revision"] != self.settings.revision:
            raise NotificationSettingsError("revision_conflict")
        if kwargs["changes"].get("intraday_enabled"):
            raise NotificationSettingsError("afternoon_not_accepted")
        self.changes.append(kwargs)
        self.settings = MorningSettings.model_validate(
            self.settings.model_dump()
            | kwargs["changes"]
            | {"revision": self.settings.revision + 1}
        )
        return self.settings

    def search(self, query):
        return [{"code": "360750", "name": "ETF", "eligible": True}]

    def get_watchlist(self):
        return {"revision": 1, "codes": ["360750"], "items": [], "max_active": 10}

    def list_newsletters(self, **kwargs):
        return []

    def get_newsletter(self, key, **kwargs):
        raise ApiError("NEWSLETTER_NOT_FOUND", 404)

    def list_deliveries(self, **kwargs):
        raise ApiError("DELIVERIES_NOT_CONNECTED", 503)


@pytest.fixture
def api():
    settings = Settings(
        origin="https://testserver",
        google_client_id="id",
        google_client_secret="secret",
        allowed_emails=("owner@example.invalid",),
        cursor_secret="c" * 32,
    )
    auth, admin, google = AuthStoreDouble(), AdminDouble(), GoogleDouble()
    current = [NOW]
    with TestClient(
        create_app(settings, auth, google, lambda: current[0], admin_store=admin),
        base_url=settings.origin,
    ) as client:
        yield client, admin, current


def headers(client):
    return {
        "Origin": "https://testserver",
        "X-CSRF-Token": client.get("/api/auth/me").json()["csrf_token"],
    }


@pytest.mark.parametrize(
    "path",
    [
        "/api/notification-settings",
        "/api/watchlist",
        "/api/instruments?q=ETF",
        "/api/newsletters",
        "/api/deliveries",
        "/api/newsletter-operations/summary",
    ],
)
def test_new_endpoints_require_session(api, path):
    client, _, _ = api
    assert client.get(path).status_code == 401


def test_settings_csrf_revision_and_current_server_values(api):
    client, admin, _ = api
    sign_in(client)
    assert client.get("/api/notification-settings").json()["revision"] == 1
    body = {"expected_revision": 1, "paused": True}
    assert client.patch("/api/notification-settings", json=body).status_code == 403
    result = client.patch(
        "/api/notification-settings", json=body, headers=headers(client)
    )
    assert result.status_code == 200 and result.json()["paused"] is True
    assert admin.changes[0]["actor"] == "owner@example.invalid"
    result = client.patch(
        "/api/notification-settings", json=body, headers=headers(client)
    )
    assert (
        result.status_code == 409
        and result.json()["error"]["code"] == "REVISION_CONFLICT"
    )


@pytest.mark.parametrize(
    "change", [{"paused": "true"}, {"paused": 1}, {"bot_token": "not-allowed"}]
)
def test_strict_new_settings_body(api, change):
    client, admin, _ = api
    sign_in(client)
    assert (
        client.patch(
            "/api/notification-settings",
            json={"expected_revision": 1, **change},
            headers=headers(client),
        ).status_code
        == 422
    )
    assert not admin.changes


def test_afternoon_missing_and_unconnected_states(api):
    client, _, current = api
    sign_in(client)
    assert (
        client.patch(
            "/api/notification-settings",
            json={"expected_revision": 1, "intraday_enabled": True},
            headers=headers(client),
        ).status_code
        == 409
    )
    assert client.get("/api/newsletters").json() == {"items": []}
    assert client.get("/api/newsletters/missing").status_code == 404
    assert client.get("/api/deliveries").status_code == 503
    assert client.get("/api/newsletters?status=published").status_code == 422
    current[0] += timedelta(minutes=31)
    assert client.get("/api/newsletters").status_code == 401
