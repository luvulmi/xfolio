"""로컬 실실행의 날짜·시각 가드. 실패 시 키·DB·외부 호출 전에 차단한다."""

import json
from datetime import UTC, date, datetime

import pytest

from scripts.dev import local_runtime as runtime


@pytest.mark.parametrize(
    "day,now,part",
    [
        (date(2026, 11, 7), datetime(2026, 11, 6, 22, 50, tzinfo=UTC), "prepare"),
        (date(2026, 11, 6), datetime(2026, 11, 4, 22, 50, tzinfo=UTC), "prepare"),
        (date(2026, 11, 6), datetime(2026, 11, 5, 22, 49, tzinfo=UTC), "prepare"),
        (date(2026, 11, 6), datetime(2026, 11, 5, 22, 51, tzinfo=UTC), "prepare"),
        (date(2026, 11, 6), datetime(2026, 11, 5, 22, 59, tzinfo=UTC), "send"),
        (date(2026, 11, 6), datetime(2026, 11, 5, 23, 10, tzinfo=UTC), "send"),
    ],
)
def test_wrong_date_and_time_do_not_load_credentials(monkeypatch, day, now, part):
    def forbidden():
        pytest.fail(
            "credentials/database must not be loaded outside authorized date/window"
        )

    monkeypatch.setattr(runtime, "load_environment", forbidden)
    assert runtime.phase(day, part, now=now)["status"] == "skipped"


def test_phase_logs_started_and_safe_exception_before_propagating(
    monkeypatch, tmp_path
):
    from xfolio.jobs import worker

    def crash(_args):
        raise RuntimeError("private-token-and-database-url")

    monkeypatch.setattr(runtime, "CACHE", tmp_path)
    monkeypatch.setattr(runtime, "load_environment", lambda: None)
    monkeypatch.setattr(worker, "main", crash)
    with pytest.raises(RuntimeError):
        runtime.phase(
            date(2026, 11, 6),
            "prepare",
            now=datetime(2026, 11, 5, 22, 50, tzinfo=UTC),
        )
    body = (tmp_path / "2026-11-06_prepare.log").read_text(encoding="utf-8")
    events = [json.loads(line) for line in body.splitlines()]
    assert events[0]["status"] == "started"
    assert events[-1]["status"] == "failed"
    assert events[-1]["exception_type"] == "RuntimeError"
    assert events[-1]["frames"][-1]["function"] == "crash"
    assert "private-token" not in body
