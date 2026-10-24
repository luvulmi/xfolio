"""시장 수집 결과의 공통 출력 모델."""

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class IndexClose(BaseModel):
    """원본 종가와 출처·거래일을 보존한 지수 한 건."""

    model_config = ConfigDict(frozen=True)

    index_id: Literal["sp500", "nasdaq100"]
    symbol: Literal["^GSPC", "^NDX"]
    name: str
    trade_date: date
    previous_trade_date: date
    close: Decimal = Field(gt=0, allow_inf_nan=False)
    previous_close: Decimal = Field(gt=0, allow_inf_nan=False)
    change_pct: Decimal = Field(allow_inf_nan=False)
    provider: Literal["Yahoo Finance"] = "Yahoo Finance"
    collector: Literal["yfinance"] = "yfinance"
    source_url: str
    retrieved_at: AwareDatetime
    market_closed_at: AwareDatetime


class MarketSnapshot(BaseModel):
    """같은 완료 거래일에 해당하는 두 지수의 조회 결과."""

    model_config = ConfigDict(frozen=True)

    as_of: AwareDatetime
    trade_date: date
    indices: tuple[IndexClose, IndexClose]
