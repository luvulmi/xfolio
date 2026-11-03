"""국내 ETF 원종가·출처·시각·부분 실패 계약."""

import hashlib
import json
import re
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal, localcontext
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

PRICE_RETENTION_DAYS = 90
DEFAULT_CODES = ("360750", "379810", "458730")
DAILY_PATH = "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"
HOLIDAY_PATH = "/uapi/domestic-stock/v1/quotations/chk-holiday"
MASTER_URL = "https://new.real.download.dws.co.kr/common/master/kospi_code.mst.zip"


class DomesticError(Exception):
    """키/응답 본문 없는 고정 진단 코드."""


class Contract(BaseModel):
    model_config = ConfigDict(
        extra="forbid", frozen=True, revalidate_instances="always"
    )


class Session(Contract):
    trade_date: date
    scheduled_close: AwareDatetime
    source: str = "pandas_market_calendars:XKRX"

    @model_validator(mode="after")
    def local_day(self):
        from zoneinfo import ZoneInfo

        if (
            self.scheduled_close.astimezone(ZoneInfo("Asia/Seoul")).date()
            != self.trade_date
        ):
            raise ValueError("SESSION_DATE_MISMATCH")
        return self


class Instrument(Contract):
    code: str = Field(pattern=r"^[0-9]{6}$")
    isin: str = Field(pattern=r"^[A-Z]{2}[0-9A-Z]{9}[0-9]$")
    name: str = Field(min_length=1, max_length=120)
    market: Literal["KRX"] = "KRX"
    currency: Literal["KRW"] = "KRW"
    master_source: Literal[MASTER_URL] = MASTER_URL
    retrieved_at: AwareDatetime
    eligible: bool = False
    eligibility_basis: str | None = None

    @model_validator(mode="after")
    def eligibility(self):
        if self.eligible and not self.eligibility_basis:
            raise ValueError("ELIGIBILITY_EVIDENCE_REQUIRED")
        return self


class DayClose(Contract):
    trade_date: date
    close: Decimal = Field(gt=0, max_digits=18, decimal_places=4, allow_inf_nan=False)
    scheduled_close: AwareDatetime
    price_as_of: AwareDatetime | None = None
    flng_cls_code: str = Field(max_length=4)
    split_rate: Decimal = Field(
        ge=0, max_digits=18, decimal_places=8, allow_inf_nan=False
    )
    modification: Literal["N", "Y"]
    revaluation_reason: str = Field(max_length=8)
    provider_change: Decimal | None = Field(
        default=None, max_digits=18, decimal_places=4, allow_inf_nan=False
    )

    @model_validator(mode="after")
    def time_integrity(self):
        Session(trade_date=self.trade_date, scheduled_close=self.scheduled_close)
        if self.price_as_of is not None:
            from zoneinfo import ZoneInfo

            if (
                self.price_as_of.astimezone(ZoneInfo("Asia/Seoul")).date()
                != self.trade_date
            ):
                raise ValueError("PRICE_DATE_MISMATCH")
        return self


def raw_return(latest: Decimal, previous: Decimal) -> Decimal:
    with localcontext() as context:
        context.prec = 28
        return ((latest / previous - 1) * 100).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )


class CloseQuote(Contract):
    code: str = Field(pattern=r"^[0-9]{6}$")
    currency: Literal["KRW"] = "KRW"
    market: Literal["KRX"] = "KRX"
    source: Literal["KIS"] = "KIS"
    source_url: Literal["https://openapi.koreainvestment.com:9443" + DAILY_PATH] = (
        "https://openapi.koreainvestment.com:9443" + DAILY_PATH
    )
    price_basis: Literal["unadjusted_regular_close"] = "unadjusted_regular_close"
    previous: DayClose
    latest: DayClose
    retrieved_at: AwareDatetime
    event_review: Literal["unverified", "none", "distribution", "split"] = "unverified"
    event_evidence: str | None = None
    basis_verified: bool = False

    @model_validator(mode="after")
    def integrity(self):
        if self.previous.trade_date >= self.latest.trade_date:
            raise ValueError("CLOSE_DATE_ORDER")
        if any(
            day.scheduled_close > self.retrieved_at
            for day in (self.previous, self.latest)
        ):
            raise ValueError("SESSION_NOT_COMPLETED")
        if any(
            day.price_as_of is not None and day.price_as_of > self.retrieved_at
            for day in (self.previous, self.latest)
        ):
            raise ValueError("FUTURE_PRICE_TIME")
        if self.event_review != "unverified" and not self.event_evidence:
            raise ValueError("EVENT_EVIDENCE_REQUIRED")
        if self.basis_verified and not self.numeric_basis_matches:
            raise ValueError("PRICE_BASIS_MISMATCH")
        return self

    @property
    def numeric_basis_matches(self):
        return (
            self.latest.provider_change == self.latest.close - self.previous.close
            and all(
                day.flng_cls_code == "00"
                and day.split_rate == 0
                and day.modification == "N"
                and day.revaluation_reason == ""
                for day in (self.previous, self.latest)
            )
        )

    @property
    def raw_change_pct(self):
        return raw_return(self.latest.close, self.previous.close)

    @property
    def change_pct(self):
        # Never decode unverified provider enum values into corporate actions.
        if (
            self.event_review not in {"none", "distribution"}
            and not self.basis_verified
        ):
            return None
        if self.event_review == "split":
            return None
        if self.latest.split_rate != 0 or self.latest.modification != "N":
            return None
        return self.raw_change_pct

    @property
    def change_reason(self):
        if self.change_pct is None:
            return "split_or_event_review_required"
        if self.event_review == "unverified":
            return "raw_price_change_actions_uninterpreted"
        return (
            "price_change_excludes_distribution"
            if self.event_review == "distribution"
            else "raw_price_change"
        )

    @property
    def content_hash(self):
        # Retrieval time is observation metadata, never a new price version.
        value = self.model_dump(mode="json", exclude={"retrieved_at"})
        for key, day in (("previous", self.previous), ("latest", self.latest)):
            for field in ("close", "split_rate", "provider_change"):
                number = getattr(day, field)
                value[key][field] = (
                    format(number.normalize(), "f") if number is not None else None
                )
        text = json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        return hashlib.sha256(text.encode()).hexdigest()


class Collection(Contract):
    started_at: AwareDatetime
    finished_at: AwareDatetime
    requested_codes: tuple[str, ...]
    watchlist_revision: int = Field(ge=0)
    quotes: tuple[CloseQuote, ...] = ()
    errors: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def coverage(self):
        if self.started_at > self.finished_at:
            raise ValueError("COLLECTION_TIME_ORDER")
        if not 1 <= len(self.requested_codes) <= 10 or len(
            set(self.requested_codes)
        ) != len(self.requested_codes):
            raise ValueError("ACTIVE_INSTRUMENT_LIMIT")
        if any(not re.fullmatch(r"[0-9]{6}", c) for c in self.requested_codes):
            raise ValueError("INVALID_CODE")
        if any(
            not re.fullmatch(r"[a-z_]{1,64}", reason) for reason in self.errors.values()
        ):
            raise ValueError("ERROR_CODE_REQUIRED")
        codes = [q.code for q in self.quotes]
        if len({(q.previous.trade_date, q.latest.trade_date) for q in self.quotes}) > 1:
            raise ValueError("COLLECTION_SESSION_MISMATCH")
        if len(codes) != len(set(codes)) or set(codes) & self.errors.keys():
            raise ValueError("DUPLICATE_RESULT")
        if set(codes) | self.errors.keys() != set(self.requested_codes):
            raise ValueError("RESULT_COVERAGE_REQUIRED")
        if any(q.retrieved_at > self.finished_at for q in self.quotes):
            raise ValueError("COLLECTION_TIME_ORDER")
        return self

    @property
    def status(self):
        return "complete" if not self.errors else "partial" if self.quotes else "failed"


def utc(value: datetime) -> datetime:
    if value.utcoffset() is None:
        raise DomesticError("timezone_required")
    return value.astimezone(UTC)
