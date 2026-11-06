"""외부 전송 없이 Telegram 계약·worker 휴장 경계·예약을 검증한다."""

import json
import socket
from datetime import date, timedelta

import httpx
import pytest

from xfolio.jobs.telegram import (
    MockTelegramTransport,
    TelegramTransport,
    slice_entities,
    split_text,
    text_units,
    validate_entities,
)
from xfolio.jobs.worker import MorningWorker, create_scheduler, main
from xfolio.newsletter.edition import at


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("external_network_forbidden")

    monkeypatch.setattr(socket.socket, "connect", forbidden)


def transport(handler):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return TelegramTransport(token="123:abc_DEF-xyz", chat_id="12345", client=client)


def test_split_preserves_all_unicode_text_and_telegram_units():
    body = ("한국어 😀 e\u0301\n" * 1500) + "end"
    values = split_text(body)
    assert "".join(values) == body
    assert len(values) > 1 and all(0 < text_units(t) <= 4000 for t in values)
    assert split_text("a" * 4096, limit=4096) == ("a" * 4096,)


@pytest.mark.parametrize("value", ["", None, 123])
def test_split_invalid(value):
    with pytest.raises(ValueError, match="telegram_text_invalid"):
        split_text(value)


def test_telegram_success_receipt_and_plaintext_request():
    def handler(request):
        body = json.loads(request.content)
        assert body["chat_id"] == "12345" and "parse_mode" not in body
        assert body["text"] == "<b>plain</b>"
        return httpx.Response(
            200,
            json={
                "ok": True,
                "result": {"message_id": 42, "chat": {"id": 12345, "type": "private"}},
            },
        )

    result = transport(handler).send("<b>plain</b>")
    assert result.status == "confirmed" and result.message_id == "42"


def test_native_entities_and_utf16_split_keep_links_and_unicode():
    text = "☀️ XFolio\n😀 원문 보기"
    start = text_units("☀️ XFolio\n😀 ")
    entities = (
        {
            "type": "text_link",
            "offset": start,
            "length": 5,
            "url": "https://example.org/story",
        },
    )

    def handler(request):
        body = json.loads(request.content)
        assert "parse_mode" not in body and body["entities"] == list(entities)
        return httpx.Response(
            200,
            json={
                "ok": True,
                "result": {"message_id": 42, "chat": {"id": 12345, "type": "private"}},
            },
        )

    assert transport(handler).send(text, entities=entities).status == "confirmed"
    chunks, offset, linked = split_text(text, limit=4), 0, ""
    for chunk in chunks:
        clipped = slice_entities(entities, offset, text_units(chunk))
        validate_entities(chunk, clipped)
        raw = chunk.encode("utf-16-le")
        for entity in clipped:
            linked += raw[
                entity["offset"] * 2 : (entity["offset"] + entity["length"]) * 2
            ].decode("utf-16-le")
        offset += text_units(chunk)
    assert linked == "원문 보기"


@pytest.mark.parametrize(
    "entity",
    [
        {"type": "bold", "offset": 1, "length": 1},
        {"type": "bold", "offset": 0, "length": 99},
        {"type": "text_link", "offset": 0, "length": 2, "url": "http://example.org"},
        {
            "type": "text_link",
            "offset": 0,
            "length": 2,
            "url": "https://secret@example.org",
        },
    ],
)
def test_bad_entities_fail_before_http(entity):
    def forbidden(_):
        raise AssertionError("http_must_not_be_called")

    assert (
        transport(forbidden).send("😀 link", entities=(entity,)).error_code
        == "telegram_entities_invalid"
    )


def test_source_attachment_uses_same_verified_private_receipt():
    def handler(request):
        assert request.url.path.endswith("/sendDocument")
        assert b'filename="telegram.py"' in request.content
        assert b"def send():" in request.content
        return httpx.Response(
            200,
            json={
                "ok": True,
                "result": {"message_id": 43, "chat": {"id": 12345, "type": "private"}},
            },
        )

    assert (
        transport(handler)
        .send_document(filename="telegram.py", content=b"def send(): pass")
        .status
        == "confirmed"
    )
    assert (
        transport(handler).send_document(filename=".env", content=b"secret").error_code
        == "telegram_document_invalid"
    )


@pytest.mark.parametrize(
    "status,body,expected",
    [
        (429, {"ok": False, "parameters": {"retry_after": 12}}, "retryable_failure"),
        (429, {"ok": False, "parameters": []}, "failed"),
        (429, {"ok": False, "parameters": {"retry_after": True}}, "failed"),
        (403, {"ok": False, "description": "secret response"}, "failed"),
        (503, {"ok": False}, "unknown"),
        (
            200,
            {
                "ok": True,
                "result": {"message_id": 42, "chat": {"id": -123, "type": "group"}},
            },
            "unknown",
        ),
        (
            200,
            {
                "ok": True,
                "result": {"message_id": 42, "chat": {"id": 999, "type": "private"}},
            },
            "unknown",
        ),
        (200, [], "unknown"),
    ],
)
def test_transport_safe_results(status, body, expected):
    result = transport(lambda _: httpx.Response(status, json=body)).send("hello")
    assert result.status == expected
    assert "secret" not in repr(result) and "abc_DEF" not in repr(result)


def test_timeout_and_invalid_json_are_unknown_without_retry():
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout("token secret", request=request)

    result = transport(handler).send("hello")
    assert result.status == "unknown" and len(calls) == 1
    assert "secret" not in repr(result)
    assert (
        transport(lambda _: httpx.Response(200, text="bad-json")).send("hello").status
        == "unknown"
    )


@pytest.mark.parametrize("chat", ["-12345", "@name", "0", "123,456"])
def test_only_one_positive_private_chat(chat):
    with pytest.raises(ValueError, match="private_recipient"):
        TelegramTransport(token="123:abc", chat_id=chat)


def test_worker_closed_or_unknown_never_calls_collection():
    for opened in (False, None):
        calls = []
        worker = MorningWorker(
            calendar=lambda *_, opened=opened: opened,
            collect_inputs=lambda calls=calls, **_: calls.append("collection"),
            newsletter_store=None,
            outbox_store=None,
            transport=MockTelegramTransport(),
            clock=lambda: at(date(2026, 11, 4), 7, 50),
        )
        result = worker.prepare()
        assert result["status"] == ("skipped" if opened is False else "failed")
        assert not calls


def test_worker_weekend_skips_even_calendar_call():
    def forbidden(*_):
        raise AssertionError("calendar_must_not_be_called")

    worker = MorningWorker(
        calendar=forbidden,
        collect_inputs=forbidden,
        newsletter_store=None,
        outbox_store=None,
        transport=MockTelegramTransport(),
        clock=lambda: at(date(2026, 11, 7), 7, 50),
    )
    assert worker.prepare()["status"] == "skipped"
    assert worker.send()["status"] == "skipped"


def test_worker_preparation_and_send_time_bounds():
    worker = MorningWorker(
        calendar=lambda *_: True,
        collect_inputs=None,
        newsletter_store=None,
        outbox_store=None,
        transport=MockTelegramTransport(),
        clock=lambda: at(date(2026, 11, 4), 7, 49),
    )
    assert worker.prepare()["reason"] == "outside_preparation_window"
    worker.clock = lambda: at(date(2026, 11, 4), 8, 10)
    assert worker.send()["reason"] == "outside_send_window"


def test_schedule_has_kst_freeze_and_safe_minute_retry():
    worker = type("Worker", (), {"prepare": lambda _: None, "send": lambda _: None})()
    scheduler = create_scheduler(worker)
    jobs = {j.id: j for j in scheduler.get_jobs()}
    now = at(date(2026, 11, 4), 7, 49)
    assert jobs["morning_prepare"].trigger.get_next_fire_time(
        None, now
    ) == now + timedelta(minutes=1)
    assert jobs["morning_send"].trigger.get_next_fire_time(None, now) == at(
        date(2026, 11, 4), 8
    )
    assert jobs["morning_send"].max_instances == 1


def test_cli_default_is_no_network_mock_and_live_fails_closed(capsys, monkeypatch):
    monkeypatch.delenv("XFOLIO_WORKER_LIVE_ACCEPTED", raising=False)
    assert main(["--once"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["mode"] == "mock" and result["network_requests"] == 0
    assert result["database_writes"] == 0 and not result["can_send"]
    assert main(["--live", "--once"]) == 1
    assert not json.loads(capsys.readouterr().out)["can_send"]
