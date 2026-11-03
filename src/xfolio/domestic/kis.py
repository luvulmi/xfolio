"""KIS 조회 전용 클라이언트. 토큰은 메모리, 실패 원문은 경계 밖으로 내보내지 않는다."""

import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation

import httpx
from dotenv import dotenv_values
from pydantic import ValidationError

from xfolio.domestic.calendar import KST, completed_sessions, parse_holidays
from xfolio.domestic.models import (
    DAILY_PATH,
    HOLIDAY_PATH,
    CloseQuote,
    Collection,
    DayClose,
    DomesticError,
    utc,
)

BASE_URL = "https://openapi.koreainvestment.com:9443"


@dataclass(frozen=True)
class KisSettings:
    app_key: str = field(repr=False)
    app_secret: str = field(repr=False)
    base_url: str = BASE_URL

    def __post_init__(self):
        if self.base_url != BASE_URL or not self.app_key or not self.app_secret:
            raise DomesticError("invalid_real_kis_settings")

    @classmethod
    def from_env_file(cls, path):
        values = dotenv_values(path, interpolate=False)
        try:
            return cls(
                values.get("KIS_APP_KEY") or "",
                values.get("KIS_APP_SECRET") or "",
                (values.get("KIS_BASE_URL") or "").rstrip("/"),
            )
        except DomesticError:
            raise DomesticError("invalid_real_kis_settings") from None


def decimal_value(value, *, positive=False):
    import re

    if not isinstance(value, str) or not re.fullmatch(
        r"-?[0-9]{1,12}(?:\.[0-9]{1,8})?", value
    ):
        raise DomesticError("invalid_numeric_field")
    try:
        result = Decimal(value)
    except InvalidOperation:
        raise DomesticError("invalid_numeric_field") from None
    if not result.is_finite() or (positive and result <= 0):
        raise DomesticError("invalid_price")
    return result


def normalize_quote(
    body: dict, code: str, sessions, retrieved_at: datetime
) -> CloseQuote:
    try:
        if (
            not isinstance(body.get("output1"), dict)
            or body["output1"].get("stck_shrn_iscd") != code
        ):
            raise DomesticError("symbol_mismatch")
        rows = body.get("output2")
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise DomesticError("invalid_quote_rows")
        days = []
        for session in sessions:
            matches = [
                r
                for r in rows
                if r.get("stck_bsop_date") == session.trade_date.strftime("%Y%m%d")
            ]
            if len(matches) != 1:
                raise DomesticError("missing_or_duplicate_session")
            row = matches[0]
            for key in ("flng_cls_code", "mod_yn", "revl_issu_reas"):
                if not isinstance(row.get(key), str):
                    raise DomesticError("missing_event_metadata")
            import re

            if not re.fullmatch(r"[0-9]{2}", row["flng_cls_code"]) or not re.fullmatch(
                r"[0-9]{0,8}", row["revl_issu_reas"]
            ):
                raise DomesticError("invalid_event_metadata")
            days.append(
                DayClose(
                    trade_date=session.trade_date,
                    close=decimal_value(row["stck_clpr"], positive=True),
                    scheduled_close=session.scheduled_close,
                    price_as_of=None,
                    flng_cls_code=row["flng_cls_code"],
                    split_rate=decimal_value(row["prtt_rate"]),
                    modification=row["mod_yn"],
                    revaluation_reason=row["revl_issu_reas"],
                    provider_change=decimal_value(row["prdy_vrss"])
                    if row.get("prdy_vrss") not in (None, "")
                    else None,
                )
            )
        if len(days) != 2:
            raise DomesticError("two_sessions_required")
        quote = CloseQuote(
            code=code, previous=days[0], latest=days[1], retrieved_at=utc(retrieved_at)
        )
        # Adopt the numeric raw-price basis, never infer 'no distribution'.
        return CloseQuote.model_validate(
            quote.model_dump() | {"basis_verified": quote.numeric_basis_matches}
        )
    except DomesticError:
        raise
    except (ValueError, TypeError, KeyError, ValidationError):
        raise DomesticError("invalid_quote") from None


class KisClient:
    def __init__(
        self,
        settings: KisSettings,
        *,
        client=None,
        clock=lambda: datetime.now(UTC),
        pause=time.sleep,
        minimum_interval=1.1,
        calendar_cache=None,
    ):
        if minimum_interval < 1.1:
            raise DomesticError("unsafe_call_interval")
        self.settings = settings
        self.client = client or httpx.Client(
            timeout=20, follow_redirects=False, trust_env=False
        )
        self._owns_client = client is None
        self.clock, self.pause, self.minimum_interval = clock, pause, minimum_interval
        self._token = None
        self._expires_at = None
        self._last_call = None
        self._lock = threading.RLock()
        self._holiday_day = None
        self._holiday_rows = None
        self._holiday_error = None
        self.calendar_cache = calendar_cache

    def close(self):
        self._token = None
        self._expires_at = None
        if self._owns_client:
            self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def _request(self, method, path, *, headers=None, **kwargs):
        # The outer caller also holds this lock: no concurrent quote/token burst.
        with self._lock:
            if self._last_call is not None:
                self.pause(
                    max(0, self.minimum_interval - (time.monotonic() - self._last_call))
                )
            self._last_call = time.monotonic()
            try:
                response = self.client.request(
                    method, self.settings.base_url + path, headers=headers, **kwargs
                )
            except httpx.TimeoutException:
                raise DomesticError("timeout") from None
            except httpx.RequestError:
                raise DomesticError("network_error") from None
            if response.status_code in (401, 403):
                self._token = None
                raise DomesticError("authentication_failed")
            if response.status_code == 429:
                raise DomesticError("rate_limited")
            if response.status_code != 200:
                raise DomesticError("http_error")
            try:
                body = response.json()
            except ValueError:
                raise DomesticError("invalid_json") from None
            if not isinstance(body, dict):
                raise DomesticError("invalid_response")
            if path != "/oauth2/tokenP" and body.get("rt_cd") != "0":
                if body.get("msg_cd") == "EGW00201":
                    raise DomesticError("rate_limited")
                if body.get("msg_cd") in ("EGW00121", "EGW00123"):
                    self._token = None
                    raise DomesticError("authentication_failed")
                raise DomesticError("provider_error")
            return body

    def _headers(self, tr_id):
        with self._lock:
            now = utc(self.clock())
            if (
                self._token is None
                or self._expires_at is None
                or self._expires_at <= now + timedelta(seconds=60)
            ):
                body = self._request(
                    "POST",
                    "/oauth2/tokenP",
                    json={
                        "grant_type": "client_credentials",
                        "appkey": self.settings.app_key,
                        "appsecret": self.settings.app_secret,
                    },
                )
                token, expires_in = body.get("access_token"), body.get("expires_in")
                if (
                    not isinstance(token, str)
                    or not token
                    or type(expires_in) is not int
                    or not 60 < expires_in <= 86400
                ):
                    raise DomesticError("authentication_failed")
                self._token = token
                self._expires_at = utc(self.clock()) + timedelta(seconds=expires_in)
            return {
                "authorization": "Bearer " + self._token,
                "appkey": self.settings.app_key,
                "appsecret": self.settings.app_secret,
                "custtype": "P",
                "tr_id": tr_id,
            }

    def holidays(self, as_of: datetime) -> dict[date, bool]:
        with self._lock:
            day = utc(as_of).astimezone(KST).date()
            if self._holiday_day == day:
                if self._holiday_error:
                    raise DomesticError(self._holiday_error)
                return dict(self._holiday_rows)
            # Durable cache is optional for independent read-only adapter use.
            if self.calendar_cache is not None:
                cached = self.calendar_cache.load_calendar(day)
                if cached is not None:
                    self._holiday_day, self._holiday_rows, self._holiday_error = (
                        day,
                        cached,
                        None,
                    )
                    return dict(cached)
            self._holiday_day, self._holiday_rows, self._holiday_error = day, None, None
            claimed = False
            try:
                headers = self._headers("CTCA0903R")
                if (
                    self.calendar_cache is not None
                    and not self.calendar_cache.claim_calendar(day, self.clock())
                ):
                    raise DomesticError("calendar_fetch_already_attempted")
                claimed = self.calendar_cache is not None
                body = self._request(
                    "GET",
                    HOLIDAY_PATH,
                    headers=headers,
                    params={
                        "BASS_DT": (day - timedelta(days=14)).strftime("%Y%m%d"),
                        "CTX_AREA_FK": "",
                        "CTX_AREA_NK": "",
                    },
                )
                self._holiday_rows = parse_holidays(body)
                if self.calendar_cache is not None:
                    self.calendar_cache.save_calendar(
                        self._holiday_rows, utc(self.clock())
                    )
            except DomesticError as exc:
                self._holiday_error = str(exc)
                if self.calendar_cache is not None and claimed:
                    self.calendar_cache.fail_calendar(day, str(exc))
                raise
            return dict(self._holiday_rows)

    def collect(
        self, codes, *, as_of=None, watchlist_revision=0, overrides=None
    ) -> Collection:
        with self._lock:
            codes = tuple(codes)
            import re

            if (
                not 1 <= len(codes) <= 10
                or len(set(codes)) != len(codes)
                or any(
                    not isinstance(c, str) or not re.fullmatch(r"[0-9]{6}", c)
                    for c in codes
                )
            ):
                raise DomesticError("invalid_requested_codes")
            started = utc(self.clock())
            reference = utc(as_of) if as_of is not None else started
            if reference > started:
                raise DomesticError("future_collection_reference")
            quotes, errors = [], {}
            try:
                sessions = completed_sessions(
                    reference, self.holidays(reference), overrides=overrides
                )
            except DomesticError as exc:
                return Collection(
                    started_at=started,
                    finished_at=utc(self.clock()),
                    requested_codes=codes,
                    watchlist_revision=watchlist_revision,
                    errors={code: str(exc) for code in codes},
                )
            terminal = None
            for code in codes:
                if terminal:
                    errors[code] = terminal
                    continue
                try:
                    body = self._request(
                        "GET",
                        DAILY_PATH,
                        headers=self._headers("FHKST03010100"),
                        params={
                            "FID_COND_MRKT_DIV_CODE": "J",
                            "FID_INPUT_ISCD": code,
                            "FID_INPUT_DATE_1": sessions[0].trade_date.strftime(
                                "%Y%m%d"
                            ),
                            "FID_INPUT_DATE_2": sessions[1].trade_date.strftime(
                                "%Y%m%d"
                            ),
                            "FID_PERIOD_DIV_CODE": "D",
                            "FID_ORG_ADJ_PRC": "1",
                        },
                    )
                    quotes.append(normalize_quote(body, code, sessions, self.clock()))
                except DomesticError as exc:
                    errors[code] = str(exc)
                    if str(exc) in {"authentication_failed", "rate_limited"}:
                        terminal = str(exc)
            return Collection(
                started_at=started,
                finished_at=utc(self.clock()),
                requested_codes=codes,
                watchlist_revision=watchlist_revision,
                quotes=tuple(quotes),
                errors=errors,
            )
