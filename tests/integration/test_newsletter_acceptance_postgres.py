"""T07 real API/DB integration with injected providers and Telegram, no external calls."""

from datetime import timedelta
from runpy import run_path

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from tests.api.test_api import AuthStoreDouble, GoogleDouble, sign_in
from tests.jobs.test_telegram_outbox_postgres import FakeLive
from tests.jobs.test_worker_collection_postgres import db as db  # noqa: PLC0414
from tests.jobs.test_worker_collection_postgres import setup
from tests.support.paths import ROOT
from xfolio.api.app import create_app
from xfolio.api.auth import Settings
from xfolio.api.newsletter_admin import NewsletterAdminStore
from xfolio.db.newsletter_news import deliveries
from xfolio.db.schema import operations_events
from xfolio.domestic.models import Instrument
from xfolio.domestic.store import DomesticStore
from xfolio.jobs.outbox import TelegramOutboxStore
from xfolio.jobs.telegram import SendResult
from xfolio.jobs.worker import MorningWorker
from xfolio.newsletter.edition import at
from xfolio.newsletter.store import NewsletterStore


def api_client(engine, clock):
    settings = Settings(
        origin="https://testserver",
        google_client_id="test-id",
        google_client_secret="test-secret",
        allowed_emails=("owner@example.invalid",),
        cursor_secret="c" * 32,
    )
    provider = GoogleDouble()
    provider.claims["exp"] = (clock[0] + timedelta(hours=2)).timestamp()
    return TestClient(
        create_app(
            settings,
            AuthStoreDouble(),
            provider,
            clock=lambda: clock[0],
            admin_store=NewsletterAdminStore(engine),
        ),
        base_url=settings.origin,
    )


def change_headers(client):
    return {
        "Origin": "https://testserver",
        "X-CSRF-Token": client.get("/api/auth/me").json()["csrf_token"],
    }


def worker_for(service, clock, transport):
    return MorningWorker(
        calendar=service.calendar,
        collect_inputs=None,
        preparation=service,
        newsletter_store=NewsletterStore(service.engine),
        outbox_store=TelegramOutboxStore(service.engine),
        transport=transport,
        clock=lambda: clock[0],
    )


def test_maximum_ten_instruments_flow_through_api_collection_and_delivery(db):
    service, clock, _calls, _ai = setup(db)
    day = db[1].target_date
    clock[0] = at(day, 7, 49)
    extra = tuple(
        Instrument(
            code=f"60000{i}",
            isin=f"KR{60000 + i:010d}",
            name=f"Synthetic ETF {i}",
            retrieved_at=at(day, 7),
            eligible=True,
            eligibility_basis="https://example.invalid/test-overseas-etf",
        )
        for i in range(8)
    )
    DomesticStore(db[0]).import_catalogue(extra)
    collect_original = service.kis.collect

    def collect_ten(codes, **kwargs):
        result = collect_original(codes[:3], **kwargs)
        return result.model_copy(
            update={
                "requested_codes": tuple(codes),
                "quotes": tuple(
                    result.quotes[i % 3].model_copy(update={"code": code})
                    for i, code in enumerate(codes)
                ),
            }
        )

    service.kis.collect = collect_ten
    with api_client(db[0], clock) as client:
        assert sign_in(client)[0].status_code == 307
        current = client.get("/api/watchlist").json()
        eleven = current["codes"] + [item.code for item in extra]
        too_many = client.put(
            "/api/watchlist",
            headers=change_headers(client),
            json={
                "expected_revision": current["revision"],
                "codes": eleven,
            },
        )
        assert too_many.status_code == 422
        ten = eleven[:10]
        changed = client.put(
            "/api/watchlist",
            headers=change_headers(client),
            json={
                "expected_revision": current["revision"],
                "codes": ten,
            },
        )
        assert changed.status_code == 200 and changed.json()["codes"] == ten
        clock[0] = at(day, 7, 50) + timedelta(seconds=5)
        transport = FakeLive()
        worker = worker_for(service, clock, transport)
        prepared = worker.prepare()
        assert prepared["status"] == "ready"
        detail = client.get("/api/newsletters/" + prepared["edition_id"]).json()
        assert detail["codes"] == ten and detail["price_count"] == 10
        clock[0] = at(day, 8)
        assert worker.send()["status"] == "confirmed"
        text = "".join(transport.calls)
        assert all(code in text for code in ten)
        summary = client.get("/api/newsletter-operations/summary").json()
        assert summary["price_freshness"]["status"] == "current"
        assert len(summary["price_freshness"]["items"]) == 10


def test_api_watchlist_freeze_collection_summary_send_history_and_dedup(db):
    service, clock, calls, ai = setup(db)
    day = db[1].target_date
    clock[0] = at(day, 7, 49)
    with api_client(db[0], clock) as client:
        assert sign_in(client)[0].status_code == 307
        old = client.get("/api/watchlist").json()
        ordered = list(reversed(old["codes"]))
        changed = client.put(
            "/api/watchlist",
            headers=change_headers(client),
            json={"expected_revision": old["revision"], "codes": ordered},
        )
        assert changed.status_code == 200 and changed.json()["revision"] == 2
        clock[0] = at(day, 7, 50) + timedelta(seconds=5)
        transport = FakeLive()
        worker = worker_for(service, clock, transport)
        ready = worker.prepare()
        assert ready["status"] == "ready" and len(ai.calls) == 1
        detail = client.get("/api/newsletters/" + ready["edition_id"]).json()
        assert detail["watchlist_revision"] == 2 and detail["codes"] == ordered
        assert detail["news_count"] == 3 and detail["mode"] == "live"
        clock[0] = at(day, 8)
        sent = worker.send()
        assert sent["status"] == "confirmed" and transport.calls
        call_count = len(transport.calls)
        assert worker.send()["status"] == "confirmed"
        assert len(transport.calls) == call_count
        assert worker.prepare()["reused"] and len(ai.calls) == 1
        assert calls.count("market") == calls.count("news") == 1
        history = client.get("/api/deliveries/" + sent["outbox_id"]).json()
        assert history["status"] == "confirmed"
        assert all(part["message_id"] for part in history["parts"])
        summary = client.get("/api/newsletter-operations/summary").json()
        assert summary["budget"]["status"] == "observed"
        assert summary["budget"]["record_count"] == 1
        assert summary["price_freshness"]["status"] == "current"
        assert summary["news_collection"]["selected_count"] == 3
        assert summary["deliveries"]["recent"][0]["status"] == "confirmed"
        with db[0].connect() as conn:
            assert conn.scalar(sa.select(sa.func.count()).select_from(deliveries)) == 3


@pytest.mark.parametrize("cancel", ["pause", "watchlist"])
def test_api_change_after_preparation_prevents_send_and_is_visible(db, cancel):
    service, clock, _calls, _ai = setup(db)
    transport = FakeLive()
    worker = worker_for(service, clock, transport)
    ready = worker.prepare()
    clock[0] = at(db[1].target_date, 7, 59)
    with api_client(db[0], clock) as client:
        assert sign_in(client)[0].status_code == 307
        if cancel == "pause":
            response = client.patch(
                "/api/notification-settings",
                headers=change_headers(client),
                json={"expected_revision": 1, "paused": True},
            )
        else:
            old = client.get("/api/watchlist").json()
            response = client.put(
                "/api/watchlist",
                headers=change_headers(client),
                json={"expected_revision": old["revision"], "codes": old["codes"][:2]},
            )
        assert response.status_code == 200
        clock[0] = at(db[1].target_date, 8)
        assert worker.send()["status"] == "skipped" and not transport.calls
        history = client.get("/api/deliveries/" + ready["outbox_id"]).json()
        assert history["status"] == "skipped" and not history["attempts"]


@pytest.mark.parametrize("result", ["partial", "unknown"])
def test_partial_or_unknown_is_visible_and_not_blindly_retried(db, result, monkeypatch):
    service, clock, _calls, _ai = setup(db)
    # Force real product UTF-16 splitting using a smaller test-only transport limit.
    import xfolio.jobs.outbox as outbox_module
    from xfolio.jobs.telegram import split_text

    with monkeypatch.context() as patch:
        patch.setattr(
            outbox_module, "split_text", lambda body: split_text(body, limit=400)
        )
        ready = service.prepare()
        edition = NewsletterStore(db[0]).get(ready["edition_id"], now=clock[0])
        chunks = split_text(edition.body, limit=400)
        assert len(chunks) > 1
        transport = FakeLive(
            [
                SendResult("confirmed", message_id="42"),
                SendResult(
                    "failed" if result == "partial" else "unknown",
                    error_code="telegram_request_rejected"
                    if result == "partial"
                    else "telegram_result_unknown",
                ),
            ]
        )
        clock[0] = at(db[1].target_date, 8)
        worker = worker_for(service, clock, transport)
        assert worker.send()["status"] == result
        count = len(transport.calls)
        assert worker.send()["status"] == result and len(transport.calls) == count
        summary = NewsletterAdminStore(db[0]).summary(now=clock[0])
        assert summary["deliveries"]["attention"][0]["status"] == result


def test_closed_day_and_after_deadline_never_transmit(db):
    service, clock, calls, ai = setup(db, closed=True)
    transport = FakeLive()
    worker = worker_for(service, clock, transport)
    assert worker.prepare()["status"] == "skipped"
    assert calls == ["calendar"] and not ai.calls
    clock[0] = at(db[1].target_date, 8)
    assert worker.send()["status"] == "skipped" and not transport.calls
    clock[0] = at(db[1].target_date, 8, 10)
    assert worker.send()["status"] == "skipped" and not transport.calls


def test_expired_preparation_blocks_restore_until_owned_purge(db):
    service, clock, _calls, _ai = setup(db)
    assert service.prepare()["status"] == "ready"
    with db[0].begin() as conn:
        conn.execute(
            operations_events.insert().values(
                id="unrelated-expired-event",
                kind="auth_session",
                scope="self",
                unique_key="unrelated-expired-event",
                created_at=clock[0],
                expires_at=clock[0],
                payload={},
            )
        )
    tools = run_path(str(ROOT / "deploy/newsletter/maintenance.py"))
    after = clock[0] + timedelta(days=91)
    result = tools["verify"](db[0], now=after)
    assert result["expired_rows"]["operations_events.newsletter_prepare"] == 1
    assert result["can_resume"] is False
    result = tools["purge"](db[0], now=after)
    assert result["deleted"]["PreparationStore"] == 1 and result["can_resume"] is True
    with db[0].connect() as conn:
        assert (
            conn.scalar(
                sa.select(operations_events.c.id).where(
                    operations_events.c.kind == "auth_session"
                )
            )
            == "unrelated-expired-event"
        )
