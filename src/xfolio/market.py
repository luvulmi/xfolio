"""yfinance로 두 지수의 최근 완료 거래일 종가를 수집한다."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from urllib.parse import quote
from zoneinfo import ZoneInfo

import pandas as pd
import pandas_market_calendars as mcal
import yfinance as yf

from xfolio.models import IndexClose, MarketSnapshot

NEW_YORK = ZoneInfo("America/New_York")
CENT = Decimal("0.01")


class MarketDataError(Exception):
    """날짜·가격 검증 또는 제공처 조회 실패."""


@dataclass(frozen=True)
class IndexSpec:
    index_id: str
    symbol: str
    name: str
    calendar: str


INDICES = (
    IndexSpec("sp500", "^GSPC", "S&P 500", "NYSE"),
    IndexSpec("nasdaq100", "^NDX", "Nasdaq-100", "NASDAQ"),
)


def completed_sessions(
    as_of: datetime, calendar_name: str
) -> tuple[date, date, datetime]:
    """달력에서 기준 시각까지 마감한 직전·최근 거래일을 구한다."""
    if as_of.utcoffset() is None:
        raise ValueError("기준 시각에는 시간대가 필요합니다.")
    local_date = as_of.astimezone(NEW_YORK).date()
    try:
        schedule = mcal.get_calendar(calendar_name).schedule(
            start_date=local_date - timedelta(days=32), end_date=local_date
        )
    except Exception as exc:
        raise MarketDataError(f"거래소 달력 조회 실패: {calendar_name}") from exc
    completed = schedule.loc[schedule["market_close"] <= as_of]
    if len(completed) < 2:
        raise MarketDataError("마감한 거래일 두 개를 확인할 수 없습니다.")
    return (
        completed.index[-2].date(),
        completed.index[-1].date(),
        completed["market_close"].iloc[-1].to_pydatetime().astimezone(UTC),
    )


def load_yahoo_history(symbol: str, start: date, end: date) -> pd.DataFrame:
    """단일 심볼을 조회하며 종료 날짜는 포함하지 않는다."""
    try:
        return yf.Ticker(symbol).history(
            start=start.isoformat(),
            end=end.isoformat(),
            interval="1d",
            auto_adjust=False,
            back_adjust=False,
            repair=False,
            rounding=False,
            actions=False,
            keepna=True,
            timeout=15,
            raise_errors=True,
        )
    except Exception as exc:
        raise MarketDataError(
            f"지수 조회 실패({symbol}): {type(exc).__name__}"
        ) from exc


def _close_on(history: pd.DataFrame, day: date, symbol: str) -> Decimal:
    if not isinstance(history, pd.DataFrame) or history.empty or "Close" not in history:
        raise MarketDataError(f"종가 응답이 비어 있습니다: {symbol}")
    if not isinstance(history.index, pd.DatetimeIndex) or history.index.hasnans:
        raise MarketDataError(f"거래일 형식이 올바르지 않습니다: {symbol}")
    dates = history.index
    if dates.tz is not None:
        dates = dates.tz_convert(NEW_YORK)
    rows = history.loc[dates.date == day, "Close"]
    if not isinstance(rows, pd.Series) or len(rows) != 1:
        raise MarketDataError(f"필수 거래일 종가가 없거나 중복입니다: {symbol} {day}")
    try:
        value = Decimal(str(rows.iloc[0]))
    except InvalidOperation as exc:
        raise MarketDataError(f"종가가 숫자가 아닙니다: {symbol} {day}") from exc
    if not value.is_finite() or value <= 0:
        raise MarketDataError(f"종가가 유효하지 않습니다: {symbol} {day}")
    return value


def display_number(value: Decimal) -> str:
    rounded = value.quantize(CENT, rounding=ROUND_HALF_UP)
    return format(abs(rounded) if rounded == 0 else rounded, ".2f")


def collect_index_closes(
    *,
    as_of: datetime | None = None,
    history_loader: Callable[[str, date, date], pd.DataFrame] | None = None,
) -> MarketSnapshot:
    """두 지수가 모두 같은 완료 거래일에 유효할 때만 결과를 반환한다."""
    reference_time = as_of if as_of is not None else datetime.now(UTC)
    if reference_time.utcoffset() is None:
        raise ValueError("기준 시각에는 시간대가 필요합니다.")
    reference_time = reference_time.astimezone(UTC)
    loader = history_loader or load_yahoo_history
    results = []
    for spec in INDICES:
        previous_day, trade_day, closed_at = completed_sessions(
            reference_time, spec.calendar
        )
        if results and results[0].trade_date != trade_day:
            raise MarketDataError("두 지수의 최근 완료 거래일이 다릅니다.")
        history = loader(spec.symbol, previous_day, trade_day + timedelta(days=1))
        retrieved_at = datetime.now(UTC)
        close = _close_on(history, trade_day, spec.symbol)
        previous_close = _close_on(history, previous_day, spec.symbol)
        change = ((close / previous_close - 1) * 100).quantize(
            CENT, rounding=ROUND_HALF_UP
        )
        results.append(
            IndexClose(
                index_id=spec.index_id,
                symbol=spec.symbol,
                name=spec.name,
                trade_date=trade_day,
                previous_trade_date=previous_day,
                close=close,
                previous_close=previous_close,
                change_pct=abs(change) if change == 0 else change,
                source_url=f"https://finance.yahoo.com/quote/{quote(spec.symbol, safe='')}/",
                retrieved_at=retrieved_at,
                market_closed_at=closed_at,
            )
        )
    return MarketSnapshot(
        as_of=reference_time, trade_date=results[0].trade_date, indices=tuple(results)
    )
