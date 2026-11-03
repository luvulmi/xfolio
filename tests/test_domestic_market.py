"""국내 시세 무통신 계약·T01 실표본 재생. 모든 HTTP는 MockTransport다."""

import io
import json
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from xfolio.domestic.calendar import completed_sessions, local_calendar, parse_holidays
from xfolio.domestic.catalogue import (
    default_instruments,
    fetch_master,
    parse_master,
    search,
)
from xfolio.domestic.kis import KisClient, KisSettings, normalize_quote
from xfolio.domestic.models import (
    DAILY_PATH,
    DEFAULT_CODES,
    HOLIDAY_PATH,
    Collection,
    DomesticError,
    Session,
)

NOW = datetime(2026, 11, 3, 14, 0, tzinfo=UTC)
SETTINGS = KisSettings("test-app-key-never-output", "test-app-secret-never-output")
ROOT = Path(__file__).resolve().parents[1]
LIVE = json.loads(
    (
        ROOT
        / "tasks/verification/assets/market/kis_close_2026-11-03T225345459055KST/close_probe.json"
    ).read_text(encoding="utf-8")
)


def holidays():
    schedule = local_calendar().schedule(
        start_date=date(2026, 10, 20), end_date=date(2026, 11, 4)
    )
    opened = set(schedule.index.date)
    return {
        "rt_cd": "0",
        "output": [
            {
                "bass_dt": (date(2026, 10, 20) + timedelta(days=i)).strftime("%Y%m%d"),
                "opnd_yn": "Y"
                if date(2026, 10, 20) + timedelta(days=i) in opened
                else "N",
            }
            for i in range(16)
        ],
    }


def live_body(code):
    sample = next(q for q in LIVE["quotes"] if q["code"] == code)
    return {
        "rt_cd": "0",
        "output1": {"stck_shrn_iscd": code},
        "output2": [dict(r["provider_fields"]) for r in sample["rows"]],
    }


def response(request):
    if request.url.path == "/oauth2/tokenP":
        return httpx.Response(
            200,
            json={
                "access_token": "test-access-token-never-output",
                "expires_in": 86400,
            },
        )
    if request.url.path == HOLIDAY_PATH:
        return httpx.Response(200, json=holidays())
    return httpx.Response(200, json=live_body(request.url.params["FID_INPUT_ISCD"]))


def client(handler=response, clock=lambda: NOW, cache=None):
    return KisClient(
        SETTINGS,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        clock=clock,
        pause=lambda _: None,
        calendar_cache=cache,
    )


def sessions():
    return completed_sessions(NOW, parse_holidays(holidays()))


def quote(code="360750", now=NOW):
    return normalize_quote(live_body(code), code, sessions(), now)


def collection(quotes=None, *, now=NOW, revision=1, codes=DEFAULT_CODES):
    return Collection(
        started_at=now,
        finished_at=now,
        requested_codes=codes,
        watchlist_revision=revision,
        quotes=tuple(quote(c, now) for c in codes) if quotes is None else tuple(quotes),
    )


def test_actual_price_sample_replays_with_decimal_date_only_and_no_assumed_events():
    result = client().collect(DEFAULT_CODES)
    assert result.status == "complete"
    assert [q.raw_change_pct for q in result.quotes] == [
        Decimal("-1.36"),
        Decimal("-2.56"),
        Decimal("0.20"),
    ]
    assert all(
        q.latest.trade_date == date(2026, 11, 3) and q.latest.price_as_of is None
        for q in result.quotes
    )
    assert all(
        q.change_pct == q.raw_change_pct
        and q.event_review == "unverified"
        and q.basis_verified
        for q in result.quotes
    )
    assert all(
        q.currency == "KRW" and q.price_basis == "unadjusted_regular_close"
        for q in result.quotes
    )


def test_tokens_and_holidays_are_cached_during_parallel_collections():
    seen = []

    def handler(request):
        seen.append(request)
        return response(request)

    adapter = client(handler)
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda _: adapter.collect(DEFAULT_CODES), range(3)))
    assert all(r.status == "complete" for r in results)
    assert sum(r.url.path == "/oauth2/tokenP" for r in seen) == 1
    assert sum(r.url.path == HOLIDAY_PATH for r in seen) == 1
    assert sum(r.url.path == DAILY_PATH for r in seen) == 9
    for request in seen:
        if request.url.path == DAILY_PATH:
            assert request.url.params["FID_ORG_ADJ_PRC"] == "1"
            assert request.url.params["FID_COND_MRKT_DIV_CODE"] == "J"
    assert "test-app" not in repr(SETTINGS)
    assert "never-output" not in results[0].model_dump_json()


def test_expiring_token_is_refreshed_once_within_same_holiday_cache_day():
    now, seen = [NOW], []

    def handler(request):
        seen.append(request.url.path)
        body = response(request)
        if request.url.path == "/oauth2/tokenP":
            return httpx.Response(
                200,
                json={
                    "access_token": "test-access-token-never-output",
                    "expires_in": 120,
                },
            )
        return body

    adapter = client(handler, clock=lambda: now[0])
    adapter.collect(DEFAULT_CODES)
    now[0] += timedelta(seconds=65)
    adapter.collect(DEFAULT_CODES)
    assert seen.count("/oauth2/tokenP") == 2
    assert seen.count(HOLIDAY_PATH) == 1


@pytest.mark.parametrize(
    "failure,expected,count",
    [
        ("timeout", "timeout", 3),
        ("missing", "missing_or_duplicate_session", 3),
        ("429", "rate_limited", 2),
        ("auth", "authentication_failed", 2),
    ],
)
def test_partial_and_terminal_failures_are_explicit_without_retries(
    failure, expected, count
):
    seen = []

    def handler(request):
        if request.url.path == DAILY_PATH:
            seen.append(request.url.params["FID_INPUT_ISCD"])
        if request.url.params.get("FID_INPUT_ISCD") == "379810":
            if failure == "timeout":
                raise httpx.ReadTimeout("test-app-secret-never-output", request=request)
            if failure == "missing":
                body = live_body("379810")
                body["output2"] = []
                return httpx.Response(200, json=body)
            return httpx.Response(
                429 if failure == "429" else 401, text="test-app-secret-never-output"
            )
        return response(request)

    result = client(handler).collect(DEFAULT_CODES)
    assert result.status == "partial"
    assert result.errors["379810"] == expected
    assert len(seen) == count
    assert "never-output" not in result.model_dump_json()


def test_auth_failure_and_missing_calendar_stop_before_quotes_and_cache_failure():
    seen = []

    def handler(request):
        seen.append(request.url.path)
        return httpx.Response(403, text="test-app-secret-never-output")

    adapter = client(handler)
    assert adapter.collect(DEFAULT_CODES).status == "failed"
    assert adapter.collect(DEFAULT_CODES).status == "failed"
    assert seen == ["/oauth2/tokenP"]


def test_morning_holiday_disagreement_and_special_close_contract():
    opened = parse_holidays(holidays())
    morning = NOW.replace(hour=0)
    assert completed_sessions(morning, opened)[-1].trade_date == date(2026, 11, 2)
    opened[date(2026, 11, 3)] = False
    with pytest.raises(DomesticError, match="calendar_disagreement"):
        completed_sessions(NOW, opened)
    opened[date(2026, 11, 3)] = True
    special = Session(
        trade_date=date(2026, 11, 3),
        scheduled_close=NOW.replace(hour=7, minute=30),
        source="https://example.invalid/official-special-hours",
    )
    assert completed_sessions(
        NOW.replace(hour=7), opened, overrides={special.trade_date: special}
    )[-1].trade_date == date(2026, 11, 2)
    del opened[date(2026, 10, 20)]
    with pytest.raises(DomesticError, match="coverage"):
        completed_sessions(NOW, opened)


@pytest.mark.parametrize(
    "event,rate",
    [("none", Decimal("-1.36")), ("distribution", Decimal("-1.36")), ("split", None)],
)
def test_reviewed_actions_keep_raw_price_return_and_never_add_distribution(event, rate):
    q = quote()
    reviewed = q.model_validate(
        q.model_dump()
        | {
            "event_review": event,
            "event_evidence": "https://example.invalid/verified-action",
        }
    )
    assert reviewed.change_pct == rate
    assert reviewed.raw_change_pct == Decimal("-1.36")
    if event == "distribution":
        assert reviewed.change_reason == "price_change_excludes_distribution"
    with pytest.raises(ValidationError, match="EVENT_EVIDENCE"):
        q.model_validate(q.model_dump() | {"event_review": event})


@pytest.mark.parametrize(
    "field,value",
    [
        ("stck_clpr", "0"),
        ("stck_clpr", "NaN"),
        ("stck_clpr", "1e4"),
        ("mod_yn", {}),
        ("flng_cls_code", "unknown"),
        ("prtt_rate", None),
    ],
)
def test_bad_or_missing_market_metadata_does_not_leak_original_fields(field, value):
    body = live_body("360750")
    body["output2"][0][field] = value
    with pytest.raises(DomesticError):
        normalize_quote(body, "360750", sessions(), NOW)


def test_mismatched_provider_basis_or_unknown_action_blocks_automatic_return():
    for field, value in (
        ("prdy_vrss", "999"),
        ("flng_cls_code", "05"),
        ("mod_yn", "Y"),
        ("prtt_rate", "2.00"),
    ):
        body = live_body("360750")
        body["output2"][1][field] = value
        result = normalize_quote(body, "360750", sessions(), NOW)
        assert result.change_pct is None
        assert result.raw_change_pct == Decimal("-1.36")


def test_master_search_keeps_unreviewed_candidates_ineligible_and_public_requests_unauthenticated():
    rows = list(default_instruments(NOW))
    raw = "".join(f"{r.code:<9}{r.isin}{r.name}{'0' * 227}\n" for r in rows)
    raw += f"{'005930':<9}KR7005930003OTHER{'0' * 227}\n"
    raw += f"{'900140':<9}HK0000000001FOREIGN{'0' * 227}\n"
    raw += f"{'F70100034':<9}KR5701000345DERIVATIVE{'0' * 227}\n"
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("kospi_code.mst", raw.encode("cp949"))
    selected = parse_master(stream.getvalue(), NOW)
    assert [i.code for i in search(selected, "Ｍｉｓｓｉｎｇ")] == []
    assert [i.code for i in search(selected, " 미국 S&P500 ")] == ["360750"]
    assert not next(i for i in selected if i.code == "005930").eligible

    def handler(request):
        assert (
            "authorization" not in request.headers and "appkey" not in request.headers
        )
        return httpx.Response(200, content=stream.getvalue())

    assert (
        len(
            fetch_master(
                retrieved_at=NOW,
                client=httpx.Client(transport=httpx.MockTransport(handler)),
            )
        )
        == 5
    )


@pytest.mark.parametrize("payload", [b"", b"not a zip"])
def test_bad_master_rejected(payload):
    with pytest.raises(DomesticError, match="invalid_master"):
        parse_master(payload, NOW)


def test_mocked_durable_calendar_cache_avoids_calendar_api():
    class Cache:
        def load_calendar(self, day):
            return parse_holidays(holidays())

    seen = []

    def handler(request):
        seen.append(request.url.path)
        return response(request)

    assert client(handler, cache=Cache()).collect(DEFAULT_CODES).status == "complete"
    assert HOLIDAY_PATH not in seen


@pytest.mark.parametrize(
    "command", ["domestic-close", "domestic-catalogue", "domestic-prune"]
)
def test_new_cli_defaults_do_not_read_secrets_or_connect_to_database(
    command, tmp_path, monkeypatch, capsys
):
    from xfolio.cli import main

    monkeypatch.chdir(tmp_path)
    main([command])
    report = json.loads(capsys.readouterr().out)
    assert report["network_requests"] == report["database_writes"] == 0
    assert report["price_retention_days"] == 90


def test_cli_collection_replays_actual_quotes_and_exposes_calculated_rates(
    monkeypatch, capsys
):
    from xfolio.cli import main
    from xfolio.domestic import cli

    monkeypatch.setattr(cli.KisSettings, "from_env_file", lambda _: SETTINGS)
    monkeypatch.setattr(cli, "KisClient", lambda settings, calendar_cache: client())
    main(["domestic-close", "--run"])
    output = capsys.readouterr().out
    report = json.loads(output)
    assert report["status"] == "complete"
    assert report["collection"]["quotes"][0]["change_pct"] == "-1.36"
    assert "never-output" not in output
