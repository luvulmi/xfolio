"""T05 관리 변경→T06 점유/이력→T08 복원 gate의 실제 공용 DB 연결."""

from datetime import timedelta
from pathlib import Path
from runpy import run_path

from test_newsletter import SEND
from test_telegram_outbox_postgres import FakeLive
from test_telegram_outbox_postgres import db as db  # noqa: PLC0414

from xfolio.api.newsletter_admin import NewsletterAdminStore
from xfolio.jobs.outbox import dispatch
from xfolio.jobs.telegram import MockTelegramTransport

MAINTENANCE = Path(__file__).parents[1] / "deploy/newsletter/maintenance.py"


def test_admin_pause_is_read_by_worker_and_visible_in_history(db):
    outbox, edition, _ = db
    admin = NewsletterAdminStore(outbox.engine)
    key = outbox.enqueue(edition.key, now=SEND, mode="live")
    saved = admin.update_settings(
        expected_revision=1, changes={"paused": True}, actor="operator", now=SEND
    )
    assert saved.revision == 2 and saved.paused
    transport = FakeLive()
    result = dispatch(outbox, key, transport, clock=lambda: SEND)
    assert result["status"] == "skipped" and not transport.calls
    history = admin.get_delivery(key, now=SEND)
    assert history["error_code"] == "disabled_or_paused"
    assert history["transport_mode"] == "live" and not history["attempts"]


def test_history_separates_mock_live_and_hides_expired_body(db):
    outbox, edition, _ = db
    admin = NewsletterAdminStore(outbox.engine)
    mock_key = outbox.enqueue(edition.key, now=SEND)
    live_key = outbox.enqueue(edition.key, now=SEND, mode="live")
    dispatch(outbox, mock_key, MockTelegramTransport(), clock=lambda: SEND)
    dispatch(outbox, live_key, FakeLive(), clock=lambda: SEND)
    rows = admin.list_deliveries(now=SEND)
    assert {r["transport_mode"] for r in rows} == {"mock", "live"}
    assert {r["status"] for r in rows} == {"confirmed"}
    detail = admin.get_delivery(live_key, now=SEND)
    assert detail["body"] == edition.body
    assert detail["parts"][0]["message_id"]
    expired_detail = admin.get_delivery(live_key, now=edition.expires_at)
    assert expired_detail["body"] is None
    assert expired_detail["parts"][0]["message_id"]


def test_restore_gate_purges_sources_and_keeps_price_free_history(db):
    outbox, edition, _ = db
    key = outbox.enqueue(edition.key, now=SEND)
    dispatch(outbox, key, MockTelegramTransport(), clock=lambda: SEND)
    tools = run_path(str(MAINTENANCE))
    after_expiry = SEND + timedelta(days=91)
    assert tools["verify"](outbox.engine, now=after_expiry)["can_resume"] is False
    result = tools["purge"](outbox.engine, now=after_expiry)
    assert result["can_resume"] is True
    assert not any(result["expired_rows"].values())
    history = NewsletterAdminStore(outbox.engine).get_delivery(key, now=after_expiry)
    assert history["status"] == "confirmed" and history["body"] is None
    assert history["parts"][0]["message_id"].startswith("mock-")
