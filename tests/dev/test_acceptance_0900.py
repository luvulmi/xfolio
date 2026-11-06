"""승인된 단발 송신 조립과 중복 marker를 외부 호출 없이 검사."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from scripts.dev import acceptance_0900 as trial
from xfolio.newsletter.edition import AcceptanceSchedule, at


def test_send_uses_real_clock_and_marker_blocks_repeat(monkeypatch, tmp_path):
    now = at(trial.DAY, 9).astimezone(UTC)

    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return now

    schedule = AcceptanceSchedule(
        target_date=trial.DAY,
        recipient_scope=trial.SCOPE,
        frozen_at=at(trial.DAY, 8, 55),
        send_at=at(trial.DAY, 9),
        deadline=at(trial.DAY, 9, 1),
    )
    config = tmp_path / "schedule.json"
    config.write_text(schedule.model_dump_json(), encoding="utf-8")
    monkeypatch.setattr(trial, "CONFIG", config)
    monkeypatch.setattr(trial, "datetime", FixedDatetime)
    monkeypatch.setattr(trial.runtime, "CACHE", tmp_path)
    monkeypatch.setattr(trial.runtime, "load_environment", lambda: None)
    monkeypatch.setattr(
        trial.runtime, "engine", lambda: SimpleNamespace(dispose=lambda: None)
    )
    monkeypatch.setenv("XFOLIO_TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("XFOLIO_TELEGRAM_CHAT_ID", "123")
    monkeypatch.setattr(
        trial,
        "NewsletterStore",
        lambda *a, **k: SimpleNamespace(
            get=lambda *a, **k: SimpleNamespace(key="edition", status="ready")
        ),
    )
    monkeypatch.setattr(
        trial,
        "TelegramOutboxStore",
        lambda *a, **k: SimpleNamespace(enqueue=lambda *a, **k: "outbox"),
    )
    monkeypatch.setattr(
        trial, "TelegramTransport", lambda **k: SimpleNamespace(close=lambda: None)
    )
    calls = []

    def send(store, key, transport, *, clock):
        assert clock() == now
        calls.append(key)
        return {"status": "confirmed", "transport_mode": "live"}

    monkeypatch.setattr(trial, "dispatch", send)
    assert trial.run("send")["status"] == "confirmed"
    with pytest.raises(FileExistsError):
        trial.run("send")
    assert calls == ["outbox"]
