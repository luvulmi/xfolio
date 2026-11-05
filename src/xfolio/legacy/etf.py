"""SPY·QQQ·DIA USD Close 수집. legacy 두 지수 모델과 구분한다."""

import json
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

import pandas as pd
import yfinance as yf
from pydantic import AwareDatetime, Field, field_validator, model_validator

from xfolio.legacy.market import (
    CENT,
    MarketDataError,
    _close_on,
    completed_sessions,
    display_number,
)
from xfolio.news.contracts import digest
from xfolio.news.input import InputContract, InputRights

SYMBOLS = ("SPY", "QQQ", "DIA")


class ETFPrice(InputContract):
    symbol: Literal["SPY", "QQQ", "DIA"]
    currency: Literal["USD"] = "USD"
    price_basis: Literal["Close"] = "Close"
    trade_date: date
    previous_trade_date: date
    close: Decimal = Field(gt=0, allow_inf_nan=False)
    previous_close: Decimal = Field(gt=0, allow_inf_nan=False)
    change_pct: Decimal = Field(allow_inf_nan=False)
    dividend: Decimal = Field(default=Decimal(0), ge=0, allow_inf_nan=False)
    previous_dividend: Decimal = Field(default=Decimal(0), ge=0, allow_inf_nan=False)
    source_url: str
    market_closed_at: AwareDatetime
    retrieved_at: AwareDatetime

    @field_validator("market_closed_at", "retrieved_at")
    @classmethod
    def utc_time(cls, value):
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def price_integrity(self):
        expected = ((self.close / self.previous_close - 1) * 100).quantize(
            CENT, rounding=ROUND_HALF_UP
        )
        if self.change_pct != expected or self.previous_trade_date >= self.trade_date:
            raise ValueError("ETF_PRICE_CONTEXT_INVALID")
        if (
            self.source_url != f"https://finance.yahoo.com/quote/{self.symbol}/"
            or self.market_closed_at > self.retrieved_at
        ):
            raise ValueError("ETF_SOURCE_OR_TIME_INVALID")
        return self


class ETFSnapshot(InputContract):
    schema_version: Literal["etf_snapshot_v1"] = "etf_snapshot_v1"
    as_of: AwareDatetime
    trade_date: date
    prices: tuple[ETFPrice, ETFPrice, ETFPrice]
    provider: Literal["Yahoo Finance"] = "Yahoo Finance"
    collector: Literal["yfinance"] = "yfinance"
    supersedes: str | None = None
    synthetic: bool = False
    data_origin: Literal["live_capture", "permitted_fixture", "synthetic_fixture"] = (
        "live_capture"
    )
    rights: InputRights = Field(default_factory=InputRights)

    @field_validator("as_of")
    @classmethod
    def utc_time(cls, value):
        return value.astimezone(UTC)

    @property
    def content_hash(self):
        values = [
            p.model_dump(mode="json", exclude={"retrieved_at"}) for p in self.prices
        ]
        return digest(json.dumps(values, sort_keys=True, separators=(",", ":")))

    @property
    def retrieved_at(self):
        return max(p.retrieved_at for p in self.prices)

    @model_validator(mode="after")
    def same_completed_session(self):
        if self.synthetic != (self.data_origin == "synthetic_fixture"):
            raise ValueError("ETF_DATA_ORIGIN_MISMATCH")
        if tuple(p.symbol for p in self.prices) != SYMBOLS:
            raise ValueError("ETF_SYMBOL_SET_REQUIRED")
        previous, expected, closed = completed_sessions(self.as_of, "NYSE")
        if self.trade_date != expected or any(
            p.trade_date != expected
            or p.previous_trade_date != previous
            or p.market_closed_at != closed
            for p in self.prices
        ):
            raise ValueError("ETF_SESSION_MISMATCH")
        if self.supersedes == self.content_hash:
            raise ValueError("ETF_REVISION_MISMATCH")
        return self


def load_etf_history(symbol, start, end):
    try:
        ticker = yf.Ticker(symbol)
        history = ticker.history(
            start=start.isoformat(),
            end=end.isoformat(),
            interval="1d",
            auto_adjust=False,
            back_adjust=False,
            repair=False,
            rounding=False,
            actions=True,
            keepna=True,
            timeout=15,
            raise_errors=True,
        )
        return history, ticker.get_history_metadata()
    except Exception as exc:
        raise MarketDataError(f"ETF 조회 실패({symbol}): {type(exc).__name__}") from exc


def collect_etf_closes(
    *,
    as_of=None,
    history_loader=None,
    clock=lambda: datetime.now(UTC),
    previous: ETFSnapshot | None = None,
    rights: InputRights | None = None,
    synthetic=False,
) -> ETFSnapshot:
    reference = as_of if as_of is not None else clock()
    previous_day, trade_day, closed_at = completed_sessions(reference, "NYSE")
    loader = history_loader or load_etf_history
    prices = []
    for symbol in SYMBOLS:
        try:
            history, metadata = loader(
                symbol, previous_day, trade_day + timedelta(days=1)
            )
            if (
                not isinstance(metadata, dict)
                or metadata.get("currency") != "USD"
                or metadata.get("instrumentType") != "ETF"
            ):
                raise MarketDataError("ETF_METADATA_INVALID")
            close, previous_close = (
                _close_on(history, d, symbol) for d in (trade_day, previous_day)
            )
            # corporate actions는 0이 유효하므로 종가의 양수 검사를 재사용하지 않는다.
            actions = {}
            for column in ("Dividends", "Stock Splits"):
                if column not in history or not isinstance(
                    history.index, pd.DatetimeIndex
                ):
                    raise MarketDataError("ETF_ACTIONS_REQUIRED")
                days = (
                    history.index.tz_convert("America/New_York").date
                    if history.index.tz
                    else history.index.date
                )
                values = []
                for day in (previous_day, trade_day):
                    value = Decimal(str(history.loc[days == day, column].iloc[0]))
                    if not value.is_finite() or value < 0:
                        raise MarketDataError("ETF_ACTIONS_INVALID")
                    values.append(value)
                actions[column] = values
            if any(actions["Stock Splits"]):
                raise MarketDataError("ETF_SPLIT_REVIEW_REQUIRED")
            prices.append(
                ETFPrice(
                    symbol=symbol,
                    trade_date=trade_day,
                    previous_trade_date=previous_day,
                    close=close,
                    previous_close=previous_close,
                    change_pct=((close / previous_close - 1) * 100).quantize(
                        CENT, rounding=ROUND_HALF_UP
                    ),
                    dividend=actions["Dividends"][1],
                    previous_dividend=actions["Dividends"][0],
                    source_url=f"https://finance.yahoo.com/quote/{symbol}/",
                    market_closed_at=closed_at,
                    retrieved_at=clock(),
                )
            )
        except MarketDataError:
            raise
        except Exception as exc:
            raise MarketDataError("ETF_RESPONSE_INVALID") from exc
    result = ETFSnapshot(
        as_of=reference,
        trade_date=trade_day,
        prices=tuple(prices),
        rights=rights or InputRights(),
        synthetic=synthetic,
        data_origin="synthetic_fixture" if synthetic else "live_capture",
    )
    if (
        previous
        and previous.trade_date == result.trade_date
        and previous.content_hash != result.content_hash
    ):
        result = ETFSnapshot.model_validate(
            result.model_dump() | {"supersedes": previous.content_hash}
        )
    return result


def etf_post_text(snapshot: ETFSnapshot):
    parts = []
    for p in snapshot.prices:
        sign = "+" if p.change_pct > 0 else ""
        parts.append(
            f"{p.symbol} {display_number(p.close)} ({sign}{display_number(p.change_pct)}%)"
        )
    return (
        f"미국 {snapshot.trade_date} ETF 종가 (USD, 분배금 미포함). "
        + "; ".join(parts)
        + ". 출처: Yahoo Finance"
    )
