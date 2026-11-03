"""KIS identity/close acceptance probe; never request accounts or place orders."""

import argparse
import hashlib
import io
import json
import re
import time
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation, localcontext
from pathlib import Path
from urllib.request import urlopen
from zoneinfo import ZoneInfo

import httpx
import pandas_market_calendars as mcal
from dotenv import dotenv_values

URL = "https://new.real.download.dws.co.kr/common/master/kospi_code.mst.zip"
CODES = {"360750", "379810", "458730"}
OUTPUT_BASE = Path("tasks/verification/assets/market")
ROOT = Path(__file__).resolve().parents[2]
KST = ZoneInfo("Asia/Seoul")
BASE_URLS = {
    "real": "https://openapi.koreainvestment.com:9443",
    "demo": "https://openapivts.koreainvestment.com:29443",
}
DAILY_PATH = "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"
HOLIDAY_PATH = "/uapi/domestic-stock/v1/quotations/chk-holiday"
ROW_FIELDS = (
    "stck_bsop_date",
    "stck_clpr",
    "flng_cls_code",
    "prtt_rate",
    "mod_yn",
    "prdy_vrss_sign",
    "prdy_vrss",
    "revl_issu_reas",
)


class ProbeError(Exception):
    """Only fixed diagnostic labels may cross the evidence boundary."""


@dataclass(frozen=True)
class Settings:
    app_key: str = field(repr=False)
    app_secret: str = field(repr=False)
    base_url: str
    environment: str


def load_settings(path: Path, environment: str) -> Settings:
    # No environment overlay/interpolation: this run explicitly uses the root file.
    values = dotenv_values(path, interpolate=False)
    required = ("KIS_APP_KEY", "KIS_APP_SECRET", "KIS_BASE_URL")
    if any(not values.get(key) for key in required):
        raise ProbeError("missing_kis_setting")
    base_url = values["KIS_BASE_URL"].rstrip("/")
    if base_url != BASE_URLS[environment]:
        raise ProbeError("environment_url_mismatch")
    return Settings(
        values["KIS_APP_KEY"], values["KIS_APP_SECRET"], base_url, environment
    )


def completed_korean_sessions(as_of: datetime, schedule=None) -> list[dict]:
    if as_of.utcoffset() is None:
        raise ProbeError("timezone_required")
    if schedule is None:
        calendar = mcal.get_calendar("XKRX")
        # XKRX retains discontinued lunch fields; only the close is used here.
        for name in ("break_start", "break_end"):
            if name in calendar.regular_market_times:
                calendar.remove_time(name)
        today = as_of.astimezone(KST).date()
        schedule = calendar.schedule(
            start_date=today - timedelta(days=32), end_date=today
        )
    completed = schedule.loc[schedule["market_close"] <= as_of].tail(2)
    if len(completed) != 2:
        raise ProbeError("insufficient_completed_sessions")
    return [
        {
            "trade_date": day.date().isoformat(),
            "scheduled_market_close_at": row["market_close"]
            .to_pydatetime()
            .astimezone(KST)
            .isoformat(),
        }
        for day, row in completed.iterrows()
    ]


def request_json(client, method: str, url: str, *, auth=False, **kwargs) -> dict:
    try:
        response = client.request(method, url, **kwargs)
    except httpx.TimeoutException:
        raise ProbeError("timeout") from None
    except httpx.RequestError:
        raise ProbeError("network_error") from None
    if response.status_code == 429:
        raise ProbeError("rate_limited")
    if response.status_code in (401, 403):
        raise ProbeError("authentication_failed")
    if response.status_code != 200:
        raise ProbeError("authentication_failed" if auth else "http_error")
    try:
        body = response.json()
    except ValueError:
        raise ProbeError("invalid_json") from None
    if not isinstance(body, dict):
        raise ProbeError("invalid_response")
    if not auth and body.get("rt_cd") != "0":
        if body.get("msg_cd") == "EGW00201":
            raise ProbeError("rate_limited")
        if body.get("msg_cd") in ("EGW00121", "EGW00123"):
            raise ProbeError("authentication_failed")
        raise ProbeError("provider_error")
    return body


def number(value, *, positive=False) -> Decimal:
    if not isinstance(value, str) or not re.fullmatch(
        r"-?\d{1,12}(?:\.\d{1,8})?", value
    ):
        raise ProbeError("invalid_numeric_field")
    try:
        result = Decimal(value)
    except InvalidOperation:
        raise ProbeError("invalid_numeric_field") from None
    if not result.is_finite() or (positive and result <= 0):
        raise ProbeError("invalid_price")
    return result


def clean_row(row: dict) -> dict:
    result = {}
    for key in ROW_FIELDS:
        value = row.get(key, "")
        if key == "mod_yn" and isinstance(value, str) and value in {"Y", "N", ""}:
            result[key] = value
            continue
        if not isinstance(value, str) or not re.fullmatch(r"[0-9. +\-]{0,24}", value):
            raise ProbeError("invalid_market_field")
        result[key] = value
    return result


def normalize_quote(
    body: dict, code: str, sessions: list[dict], retrieved_at: datetime
) -> dict:
    summary = body.get("output1")
    rows = body.get("output2")
    if not isinstance(summary, dict) or summary.get("stck_shrn_iscd") != code:
        raise ProbeError("symbol_mismatch")
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ProbeError("invalid_rows")
    selected = []
    for session in sessions:
        day = session["trade_date"].replace("-", "")
        matches = [row for row in rows if row.get("stck_bsop_date") == day]
        if len(matches) != 1:
            raise ProbeError("missing_or_duplicate_session")
        row = clean_row(matches[0])
        price = number(row["stck_clpr"], positive=True)
        selected.append(
            {
                **session,
                "close": str(price),
                "price_as_of": None,
                "price_time_status": "daily_date_only",
                "provider_fields": row,
            }
        )
    previous, latest = selected
    with localcontext() as context:
        context.prec = 28
        rate = (Decimal(latest["close"]) / Decimal(previous["close"]) - 1) * 100
        display = rate.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    # Preserve event codes without inventing an enum mapping. This probe computes
    # the requested raw-close diagnostic; publication needs the T02 event policy.
    supplier_summary = {}
    for key in ("stck_prpr", "stck_prdy_clpr", "prdy_ctrt"):
        if summary.get(key) not in (None, ""):
            supplier_summary[key] = str(number(summary[key]))
    return {
        "code": code,
        "market": "KRX",
        "market_parameter": "J",
        "currency": "KRW",
        "source": "KIS",
        "endpoint": DAILY_PATH,
        "tr_id": "FHKST03010100",
        "retrieved_at": retrieved_at.isoformat(),
        "adjustment": "unadjusted",
        "rows": selected,
        "raw_close_change_pct": str(rate),
        "raw_close_change_pct_display": str(display),
        "publishable_change_pct": None,
        "event_basis_status": "review_required",
        "supplier_summary_not_used_for_return": supplier_summary,
    }


def holiday_evidence(body: dict, sessions: list[dict], end: str) -> dict:
    output = body.get("output")
    if not isinstance(output, list):
        raise ProbeError("invalid_holiday_rows")
    rows = []
    for row in output:
        if not isinstance(row, dict):
            raise ProbeError("invalid_holiday_rows")
        day = row.get("bass_dt", "")
        if not isinstance(day, str) or not re.fullmatch(r"\d{8}", day):
            raise ProbeError("invalid_holiday_date")
        if day > end.replace("-", ""):
            continue
        item = {"bass_dt": day}
        for key in ("bzdy_yn", "tr_day_yn", "opnd_yn", "sttl_day_yn"):
            if not isinstance(row.get(key), str) or row[key] not in {"Y", "N"}:
                raise ProbeError("invalid_holiday_flag")
            item[key] = row[key]
        rows.append(item)
    expected = {s["trade_date"].replace("-", "") for s in sessions}
    # An open day in today's calendar may not have completed yet (08:00 run).
    last_completed = sessions[-1]["trade_date"].replace("-", "")
    opened = sorted(
        r["bass_dt"]
        for r in rows
        if r["opnd_yn"] == "Y" and r["bass_dt"] <= last_completed
    )
    return {
        "source": "KIS",
        "endpoint": HOLIDAY_PATH,
        "tr_id": "CTCA0903R",
        "rows": rows,
        "matches_selected_sessions": set(opened[-2:]) == expected,
    }


def run_close_probe(
    settings: Settings, client, *, as_of: datetime, clock=None, pause=time.sleep
) -> dict:
    clock = clock or (lambda: datetime.now(KST))
    sessions = completed_korean_sessions(as_of)
    report = {
        "kind": "authenticated_daily_close_probe",
        "started_at": as_of.isoformat(),
        "environment": settings.environment,
        "base_url": settings.base_url,
        "calendar": "pandas_market_calendars:XKRX; scheduled close, not exchange timestamp",
        "sessions": sessions,
        "auth": "not_attempted",
        "requests_attempted": 0,
        "quotes": [],
        "errors": [],
        "holiday": None,
    }
    token = None
    try:
        report["requests_attempted"] += 1
        body = request_json(
            client,
            "POST",
            settings.base_url + "/oauth2/tokenP",
            auth=True,
            json={
                "grant_type": "client_credentials",
                "appkey": settings.app_key,
                "appsecret": settings.app_secret,
            },
        )
        token = body.get("access_token")
        if not isinstance(token, str) or not token:
            raise ProbeError("authentication_failed")
        report["auth"] = "success"
    except ProbeError as exc:
        report["auth"] = "failed"
        report["errors"].append({"stage": "auth", "reason": str(exc)})
        report["status"] = "failed"
        return report
    headers = {
        "authorization": f"Bearer {token}",
        "appkey": settings.app_key,
        "appsecret": settings.app_secret,
        "custtype": "P",
    }
    pause(1.1)
    try:
        report["requests_attempted"] += 1
        start = datetime.fromisoformat(sessions[0]["trade_date"]).date() - timedelta(
            days=3
        )
        body = request_json(
            client,
            "GET",
            settings.base_url + HOLIDAY_PATH,
            headers={**headers, "tr_id": "CTCA0903R"},
            params={
                "BASS_DT": start.strftime("%Y%m%d"),
                "CTX_AREA_FK": "",
                "CTX_AREA_NK": "",
            },
        )
        report["holiday"] = {
            **holiday_evidence(
                body, sessions, as_of.astimezone(KST).date().isoformat()
            ),
            "retrieved_at": clock().isoformat(),
        }
    except ProbeError as exc:
        report["errors"].append({"stage": "holiday", "reason": str(exc)})
        if str(exc) == "authentication_failed":
            report["status"] = "failed"
            return report
    for code in sorted(CODES):
        pause(1.1)
        try:
            report["requests_attempted"] += 1
            body = request_json(
                client,
                "GET",
                settings.base_url + DAILY_PATH,
                headers={**headers, "tr_id": "FHKST03010100"},
                params={
                    "FID_COND_MRKT_DIV_CODE": "J",
                    "FID_INPUT_ISCD": code,
                    "FID_INPUT_DATE_1": sessions[0]["trade_date"].replace("-", ""),
                    "FID_INPUT_DATE_2": sessions[1]["trade_date"].replace("-", ""),
                    "FID_PERIOD_DIV_CODE": "D",
                    "FID_ORG_ADJ_PRC": "1",
                },
            )
            report["quotes"].append(normalize_quote(body, code, sessions, clock()))
        except ProbeError as exc:
            report["errors"].append(
                {"stage": "quote", "code": code, "reason": str(exc)}
            )
            if str(exc) == "authentication_failed":
                break
    holiday_ok = report["holiday"] and report["holiday"]["matches_selected_sessions"]
    report["status"] = "success" if not report["errors"] and holiday_ok else "partial"
    # Never serialize arbitrary provider content or authentication material.
    serialized = json.dumps(report)
    if any(
        secret in serialized
        for secret in (settings.app_key, settings.app_secret, token)
    ):
        raise ProbeError("secret_in_evidence")
    return report


def select_rows(payload: bytes) -> list[dict[str, str]]:
    """Follow the official parser's 228-character fixed-width suffix contract."""
    selected = []
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        content = archive.read("kospi_code.mst").decode("cp949")
    for line in content.splitlines(keepends=True):
        identity = line[:-228]
        code = identity[:9].strip()
        if code in CODES:
            selected.append(
                {"code": code, "isin": identity[9:21], "name": identity[21:].strip()}
            )
    if {row["code"] for row in selected} != CODES or len(selected) != len(CODES):
        raise ValueError("Expected exactly three unique ETF master rows")
    return selected


def master_probe() -> None:
    with urlopen(URL, timeout=30) as response:
        payload = response.read()
    rows = select_rows(payload)
    output = OUTPUT_BASE / datetime.now(UTC).strftime("kis_%Y-%m-%dT%H%M%S%fZ")
    output.mkdir(parents=True, exist_ok=False)
    result = {
        "source": URL,
        "retrieved_at": datetime.now(UTC).isoformat(),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "kind": "public_master_identity_only",
        "authenticated_quotes_verified": False,
        "rows": rows,
    }
    (output / "selected_master.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=True))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode", choices=("master", "check-config", "close"), default="master"
    )
    parser.add_argument("--environment", choices=("real", "demo"), default="real")
    args = parser.parse_args()
    if args.mode == "master":
        master_probe()
        return
    try:
        settings = load_settings(ROOT / ".env", args.environment)
        if args.mode == "check-config":
            print(
                json.dumps(
                    {
                        "settings_present": True,
                        "environment": settings.environment,
                        "official_url_matches": True,
                        "key_environment": "unverified_until_auth",
                    }
                )
            )
            return
        if settings.environment != "real":
            raise ProbeError("real_quotes_require_real_environment")
        with httpx.Client(
            timeout=20, follow_redirects=False, trust_env=False
        ) as client:
            result = run_close_probe(settings, client, as_of=datetime.now(KST))
        output = (
            ROOT
            / OUTPUT_BASE
            / datetime.now(KST).strftime("kis_close_%Y-%m-%dT%H%M%S%fKST")
        )
        output.mkdir(parents=True, exist_ok=False)
        target = output / "close_probe.json"
        target.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(
            json.dumps(
                {
                    "status": result["status"],
                    "auth": result["auth"],
                    "requests_attempted": result["requests_attempted"],
                    "successful_symbols": len(result["quotes"]),
                    "errors": result["errors"],
                    "evidence": str(target.relative_to(ROOT)),
                }
            )
        )
        if result["status"] != "success":
            raise SystemExit(1)
    except ProbeError as exc:
        print(json.dumps({"status": "failed", "reason": str(exc)}))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
