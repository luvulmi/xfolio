"""KIS 개장일과 로컬 마감 달력을 대조한다. 미확인 특수일은 보류한다."""

from datetime import date, datetime, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo

import pandas_market_calendars as mcal

from xfolio.domestic.models import DomesticError, Session, utc

KST = ZoneInfo("Asia/Seoul")


@lru_cache(maxsize=1)
def local_calendar():
    calendar = mcal.get_calendar("XKRX")
    for field in ("break_start", "break_end"):
        if field in calendar.regular_market_times:
            calendar.remove_time(field)
    return calendar


def parse_holidays(body: dict) -> dict[date, bool]:
    rows = body.get("output")
    if not isinstance(rows, list) or not rows:
        raise DomesticError("missing_calendar")
    result = {}
    for row in rows:
        try:
            if not isinstance(row, dict) or row.get("opnd_yn") not in ("Y", "N"):
                raise ValueError
            raw = row["bass_dt"]
            if (
                not isinstance(raw, str)
                or len(raw) != 8
                or not raw.isascii()
                or not raw.isdigit()
            ):
                raise ValueError
            day = date.fromisoformat(raw[:4] + "-" + raw[4:6] + "-" + raw[6:])
            if day in result:
                raise ValueError
            result[day] = row["opnd_yn"] == "Y"
        except (ValueError, KeyError, TypeError):
            raise DomesticError("invalid_calendar") from None
    return result


def completed_sessions(
    as_of: datetime,
    opened: dict[date, bool],
    *,
    overrides: dict[date, Session] | None = None,
) -> tuple[Session, Session]:
    utc(as_of)
    today = as_of.astimezone(KST).date()
    start = today - timedelta(days=14)
    overrides = overrides or {}
    if any((start + timedelta(days=i)) not in opened for i in range(15)):
        raise DomesticError("calendar_coverage_missing")
    schedule = local_calendar().schedule(start_date=start, end_date=today)
    sessions = []
    for offset in range(15):
        day = start + timedelta(days=offset)
        if day in overrides:
            session = overrides[day]
            if (
                session.trade_date != day
                or not session.source.startswith("https://")
                or not opened[day]
            ):
                raise DomesticError("invalid_session_override")
        else:
            local = schedule.loc[schedule.index.date == day]
            if opened[day] != (len(local) == 1):
                raise DomesticError("calendar_disagreement")
            if not opened[day]:
                continue
            session = Session(
                trade_date=day,
                scheduled_close=local["market_close"].iloc[0].to_pydatetime(),
            )
        if session.scheduled_close <= as_of:
            sessions.append(session)
    if len(sessions) < 2:
        raise DomesticError("insufficient_completed_sessions")
    return tuple(sessions[-2:])
