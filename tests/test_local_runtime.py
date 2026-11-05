"""로컬 실실행의 날짜·시각 가드. 실패 시 키·DB·외부 호출 전에 차단한다."""

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
