"""Offline checks for the public master identity probe; no quote claims."""

import io
import json
import runpy
import zipfile
from datetime import datetime
from decimal import Decimal

import httpx
import pandas as pd
import pytest

from tests.support.paths import ROOT

PROBE = runpy.run_path(str(ROOT / "scripts/experiments/kis_market_probe.py"))


def master_zip(codes):
    rows = "".join(f"{code:<9}KR{code}0000{'ETF':<12}{'0' * 227}\n" for code in codes)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("kospi_code.mst", rows.encode("cp949"))
    return buffer.getvalue()


def test_selects_only_three_requested_codes():
    rows = PROBE["select_rows"](master_zip(["005930", "360750", "379810", "458730"]))
    assert [row["code"] for row in rows] == ["360750", "379810", "458730"]
    assert all(row["name"] == "ETF" for row in rows)


@pytest.mark.parametrize(
    "codes", [["360750"], ["360750", "379810", "458730", "458730"]]
)
def test_missing_or_duplicate_identity_is_rejected(codes):
    with pytest.raises(ValueError, match="exactly three"):
        PROBE["select_rows"](master_zip(codes))


# Every response below is synthetic; no provider calls or real credentials.
NOW = datetime.fromisoformat("2026-11-03T22:55:00+09:00")
SESSIONS = PROBE["completed_korean_sessions"](NOW)
ERROR = PROBE["ProbeError"]
SETTINGS = PROBE["Settings"](
    "synthetic-app-key", "synthetic-secret", PROBE["BASE_URLS"]["real"], "real"
)


def daily(code="360750", *, event="00", previous="10000", latest="10125"):
    return {
        "rt_cd": "0",
        "output1": {"stck_shrn_iscd": code, "prdy_ctrt": "99.9"},
        "output2": [
            {
                "stck_bsop_date": "20261103",
                "stck_clpr": latest,
                "flng_cls_code": event,
                "prtt_rate": "0.00",
                "mod_yn": "N",
                "revl_issu_reas": "00",
            },
            {"stck_bsop_date": "20261102", "stck_clpr": previous},
        ],
    }


def holiday():
    return {
        "rt_cd": "0",
        "output": [
            {
                "bass_dt": day,
                "bzdy_yn": flag,
                "tr_day_yn": flag,
                "opnd_yn": flag,
                "sttl_day_yn": flag,
            }
            for day, flag in [
                ("20261030", "Y"),
                ("20261031", "N"),
                ("20261101", "N"),
                ("20261102", "Y"),
                ("20261103", "Y"),
            ]
        ],
    }


def transport_response(request):
    if request.url.path == "/oauth2/tokenP":
        return httpx.Response(200, json={"access_token": "synthetic-bearer-token"})
    if request.url.path == PROBE["HOLIDAY_PATH"]:
        return httpx.Response(200, json=holiday())
    return httpx.Response(200, json=daily(request.url.params["FID_INPUT_ISCD"]))


def run(handler):
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        return PROBE["run_close_probe"](
            SETTINGS, client, as_of=NOW, clock=lambda: NOW, pause=lambda _: None
        )


def test_success_minimal_requests_and_no_auth_material_in_evidence():
    seen = []

    def handler(request):
        seen.append(request)
        if request.url.path == PROBE["DAILY_PATH"]:
            assert request.url.params["FID_ORG_ADJ_PRC"] == "1"
            assert request.url.params["FID_PERIOD_DIV_CODE"] == "D"
            assert request.url.params["FID_COND_MRKT_DIV_CODE"] == "J"
            assert request.url.params["FID_INPUT_DATE_1"] == "20261102"
            assert request.url.params["FID_INPUT_DATE_2"] == "20261103"
        return transport_response(request)

    report = run(handler)
    assert report["status"] == "success"
    assert report["requests_attempted"] == len(seen) == 5
    assert len(report["quotes"]) == 3
    assert report["holiday"]["matches_selected_sessions"]
    assert "synthetic" not in json.dumps(report)
    assert all("account" not in str(r.url) and "order" not in str(r.url) for r in seen)


def test_holiday_and_incomplete_current_session_use_prior_completed_dates():
    before_close = datetime.fromisoformat("2026-11-03T08:00:00+09:00")
    assert [
        s["trade_date"] for s in PROBE["completed_korean_sessions"](before_close)
    ] == ["2026-10-30", "2026-11-02"]
    # Hangul Day, an actual calendar holiday; quotes themselves remain synthetic.
    holiday_morning = datetime.fromisoformat("2026-10-09T08:00:00+09:00")
    assert [
        s["trade_date"] for s in PROBE["completed_korean_sessions"](holiday_morning)
    ] == ["2026-10-07", "2026-10-08"]
    weekend = datetime.fromisoformat("2026-11-01T20:00:00+09:00")
    assert PROBE["completed_korean_sessions"](weekend)[-1]["trade_date"] == "2026-10-30"


def test_special_delayed_close_and_timezone_are_not_replaced_with_query_time():
    schedule = pd.DataFrame(
        {
            "market_close": pd.to_datetime(
                ["2026-11-02T06:30:00Z", "2026-11-03T07:30:00Z", "2026-11-04T06:30:00Z"]
            )
        },
        index=pd.to_datetime(["2026-11-02", "2026-11-03", "2026-11-04"]),
    )
    with pytest.raises(ERROR, match="insufficient"):
        PROBE["completed_korean_sessions"](
            datetime.fromisoformat("2026-11-03T16:00:00+09:00"), schedule
        )
    sessions = PROBE["completed_korean_sessions"](NOW, schedule)
    assert sessions[-1]["scheduled_market_close_at"].endswith("16:30:00+09:00")
    with pytest.raises(ERROR, match="timezone"):
        PROBE["completed_korean_sessions"](NOW.replace(tzinfo=None))


def test_decimal_computes_raw_price_change_independent_of_supplier_return():
    quote = PROBE["normalize_quote"](daily(), "360750", SESSIONS, NOW)
    assert Decimal(quote["raw_close_change_pct"]) == Decimal("1.25")
    assert quote["raw_close_change_pct_display"] == "1.25"
    assert quote["currency"] == "KRW"
    assert quote["publishable_change_pct"] is None
    assert all(r["price_as_of"] is None for r in quote["rows"])
    assert quote["retrieved_at"] != quote["rows"][-1]["scheduled_market_close_at"]


@pytest.mark.parametrize("event", ["01", "05", "99", ""])
def test_ex_distribution_or_unknown_event_never_uses_supplier_rate(event):
    quote = PROBE["normalize_quote"](daily(event=event), "360750", SESSIONS, NOW)
    assert quote["raw_close_change_pct_display"] == "1.25"
    assert quote["publishable_change_pct"] is None
    assert quote["event_basis_status"] == "review_required"


def test_split_keeps_diagnostic_separate_from_publishable_return():
    body = daily(previous="10000", latest="5000")
    body["output2"][0].update({"prtt_rate": "2.00", "mod_yn": "Y"})
    quote = PROBE["normalize_quote"](body, "360750", SESSIONS, NOW)
    assert quote["raw_close_change_pct_display"] == "-50.00"
    assert quote["publishable_change_pct"] is None


def test_recorded_live_sample_replayed_offline_with_exact_decimal_results():
    path = ROOT / (
        "tasks/verification/assets/market/"
        "kis_close_2026-11-03T225345459055KST/close_probe.json"
    )
    sample = json.loads(path.read_text(encoding="utf-8"))
    expected = {"360750": "-1.36", "379810": "-2.56", "458730": "0.20"}
    for quote in sample["quotes"]:
        body = {
            "output1": {"stck_shrn_iscd": quote["code"]},
            "output2": [r["provider_fields"] for r in quote["rows"]],
        }
        replayed = PROBE["normalize_quote"](
            body, quote["code"], sample["sessions"], NOW
        )
        assert replayed["raw_close_change_pct_display"] == expected[quote["code"]]
    # Actual holiday response: tr_day_yn is not sufficient to identify open days.
    weekend = next(r for r in sample["holiday"]["rows"] if r["bass_dt"] == "20261031")
    assert weekend["tr_day_yn"] == "Y" and weekend["opnd_yn"] == "N"


@pytest.mark.parametrize("stage,count", [("holiday", 2), ("quote", 3)])
def test_expired_auth_during_probe_stops_remaining_calls(stage, count):
    def handler(request):
        target = PROBE["HOLIDAY_PATH"] if stage == "holiday" else PROBE["DAILY_PATH"]
        if request.url.path == target:
            return httpx.Response(401, json={"msg1": "synthetic-secret"})
        return transport_response(request)

    report = run(handler)
    assert report["requests_attempted"] == count
    assert report["status"] != "success"
    assert report["errors"][-1]["reason"] == "authentication_failed"


@pytest.mark.parametrize("price", ["0", "-1", "NaN", "Infinity", "", "1e4"])
def test_invalid_price_rejected(price):
    with pytest.raises(ERROR):
        PROBE["normalize_quote"](daily(latest=price), "360750", SESSIONS, NOW)


@pytest.mark.parametrize("case", ["missing", "duplicate", "old", "symbol"])
def test_missing_rows_never_fall_back_to_stale_or_wrong_symbol(case):
    body = daily()
    if case == "missing":
        body["output2"].pop(0)
    elif case == "duplicate":
        body["output2"].append(body["output2"][0])
    elif case == "old":
        body["output2"][0]["stck_bsop_date"] = "20261030"
    else:
        body["output1"]["stck_shrn_iscd"] = "379810"
    with pytest.raises(ERROR):
        PROBE["normalize_quote"](body, "360750", SESSIONS, NOW)


@pytest.mark.parametrize(
    "status,body,reason",
    [
        (401, {}, "authentication_failed"),
        (403, {}, "authentication_failed"),
        (429, {}, "rate_limited"),
        (500, {}, "authentication_failed"),
        (200, {"error_description": "synthetic-secret"}, "authentication_failed"),
    ],
)
def test_auth_failure_stops_all_followup_calls(status, body, reason):
    report = run(lambda r: httpx.Response(status, json=body))
    assert report["requests_attempted"] == 1
    assert report["quotes"] == []
    assert report["errors"] == [{"stage": "auth", "reason": reason}]
    assert "synthetic" not in json.dumps(report)


@pytest.mark.parametrize(
    "failure,reason",
    [
        ("429", "rate_limited"),
        ("timeout", "timeout"),
        ("empty", "missing_or_duplicate_session"),
        ("provider_429", "rate_limited"),
    ],
)
def test_partial_symbol_failure_does_not_retry_or_hide_success(failure, reason):
    def handler(request):
        if request.url.params.get("FID_INPUT_ISCD") == "379810":
            if failure == "timeout":
                raise httpx.ReadTimeout("synthetic-secret", request=request)
            if failure == "429":
                return httpx.Response(429, json={"msg1": "synthetic-secret"})
            if failure == "provider_429":
                return httpx.Response(200, json={"rt_cd": "1", "msg_cd": "EGW00201"})
            body = daily("379810")
            body["output2"] = []
            return httpx.Response(200, json=body)
        return transport_response(request)

    report = run(handler)
    assert report["status"] == "partial"
    assert [q["code"] for q in report["quotes"]] == ["360750", "458730"]
    assert report["errors"] == [{"stage": "quote", "code": "379810", "reason": reason}]
    assert report["requests_attempted"] == 5
    assert "synthetic" not in json.dumps(report)


def test_holiday_mismatch_prevents_full_success():
    def handler(request):
        if request.url.path == PROBE["HOLIDAY_PATH"]:
            body = holiday()
            body["output"][-1]["opnd_yn"] = "N"
            return httpx.Response(200, json=body)
        return transport_response(request)

    report = run(handler)
    assert report["status"] == "partial"
    assert not report["holiday"]["matches_selected_sessions"]


def test_morning_holiday_crosscheck_excludes_not_yet_completed_open_day():
    as_of = datetime.fromisoformat("2026-11-03T08:00:00+09:00")
    sessions = PROBE["completed_korean_sessions"](as_of)
    evidence = PROBE["holiday_evidence"](holiday(), sessions, "2026-11-03")
    assert evidence["matches_selected_sessions"]
    assert sessions[-1]["trade_date"] == "2026-11-02"


@pytest.mark.parametrize("case", ["holiday_date", "holiday_flag", "event_flag"])
def test_malformed_optional_fields_raise_structured_failure(case):
    if case.startswith("holiday"):
        body = holiday()
        body["output"][0]["bass_dt" if case == "holiday_date" else "opnd_yn"] = None
        with pytest.raises(ERROR):
            PROBE["holiday_evidence"](body, SESSIONS, "2026-11-03")
    else:
        body = daily()
        body["output2"][0]["mod_yn"] = {}
        with pytest.raises(ERROR):
            PROBE["normalize_quote"](body, "360750", SESSIONS, NOW)


def test_unknown_provider_fields_are_not_persisted():
    body = daily()
    body["account"] = "synthetic-account-number"
    body["output1"]["access_token"] = "synthetic-bearer-token"
    body["output2"][0]["appkey"] = "synthetic-app-key"
    quote = PROBE["normalize_quote"](body, "360750", SESSIONS, NOW)
    assert "synthetic" not in json.dumps(quote)


@pytest.mark.parametrize(
    "base,environment,valid",
    [
        (PROBE["BASE_URLS"]["real"], "real", True),
        (PROBE["BASE_URLS"]["demo"], "demo", True),
        (PROBE["BASE_URLS"]["demo"], "real", False),
        ("https://example.com:9443", "real", False),
        (PROBE["BASE_URLS"]["real"] + "/elsewhere", "real", False),
    ],
)
def test_settings_environment_url_validation_without_leaking_values(
    tmp_path, base, environment, valid
):
    path = tmp_path / ".env"
    path.write_text(
        f"KIS_APP_KEY=synthetic-app-key\nKIS_APP_SECRET=synthetic-secret\nKIS_BASE_URL={base}\n",
        encoding="utf-8",
    )
    if valid:
        settings = PROBE["load_settings"](path, environment)
        assert settings.base_url == base
        assert "synthetic" not in repr(settings)
    else:
        with pytest.raises(ERROR, match="environment_url_mismatch"):
            PROBE["load_settings"](path, environment)
