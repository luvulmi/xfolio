"""증분 창·겹침·페이지·보류·비밀 비노출을 외부 통신 없이 시험한다."""

import importlib.util
import json
from datetime import UTC, date, datetime, timedelta
from itertools import pairwise
from pathlib import Path
from uuid import UUID

import httpx
import pytest

SPEC = importlib.util.spec_from_file_location(
    "incremental_probe",
    Path(__file__).resolve().parents[1]
    / "scripts/experiments/marketaux_incremental_probe.py",
)
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)
NOW = datetime(2026, 10, 24, 12, tzinfo=UTC)
TOKEN = "secret-not-to-be-displayed"


class VirtualClock:
    def __init__(self):
        self.value = 0.0
        self.sleeps = []

    def monotonic(self):
        return self.value

    def sleep(self, duration):
        assert duration > 0
        self.sleeps.append(duration)
        self.value += duration


def item(number=1, timestamp="2026-10-24T11:30:00Z", **extras):
    return {
        "uuid": str(UUID(int=number)),
        "url": "https://example.com/news",
        "source": "example.com",
        "published_at": timestamp,
        "description": "Do not save this body",
        "snippet": "private excerpt",
        **extras,
    }


def response(data=None, found=None, page=1, headers=None):
    data = [] if data is None else data
    return httpx.Response(
        200,
        headers=headers,
        json={
            "meta": {
                "found": len(data) if found is None else found,
                "returned": len(data),
                "page": page,
                "limit": 3,
            },
            "data": data,
        },
    )


def run(handler, **kwargs):
    virtual = VirtualClock()
    kwargs.setdefault("clock", virtual.monotonic)
    kwargs.setdefault("sleep", virtual.sleep)
    return probe.probe(
        run=True, token=TOKEN, now=NOW, transport=httpx.MockTransport(handler), **kwargs
    )


def test_windows_have_exact_nominal_boundary_and_one_minute_overlap():
    result = probe.probe(now=NOW, repeat=True)
    first, second = result["queries"][0], result["queries"][4]
    assert first["nominal_before_utc"] == second["nominal_after_utc"]
    assert first["parameters"]["published_after"] == "2026-10-24T10:59:00"
    assert second["parameters"]["published_after"] == "2026-10-24T11:29:00"
    assert result["request_cap"] == 17
    assert result["request_count"] == 0
    assert not result["checkpoint_advance"]
    assert not result["cursor_written"]
    assert result["experiment_version"] == "marketaux_incremental_v2_pacing"
    assert result["min_request_interval_seconds"] == 3
    assert result["max_retries"] == 0


def test_dry_run_never_waits_or_requests():
    def forbidden(*args, **kwargs):
        pytest.fail("dry run attempted pacing or network")

    result = probe.probe(
        now=NOW,
        clock=forbidden,
        sleep=forbidden,
        transport=httpx.MockTransport(forbidden),
    )
    assert result["request_count"] == 0
    assert result["request_observations"] == []


def test_request_starts_are_spaced_including_queries_and_repeat_without_wall_sleep():
    clock, starts = VirtualClock(), []

    def handler(request):
        starts.append(clock.value)
        clock.value += 5 if len(starts) == 2 else 0.25
        page = int(request.url.params["page"])
        stamp = request.url.params["published_before"] + "Z"
        return response(
            [
                item(number, timestamp=stamp)
                for number in ((1, 2, 3) if page == 1 else (4,))
            ],
            found=4,
            page=page,
        )

    result = run(handler, repeat=True, clock=clock.monotonic, sleep=clock.sleep)
    assert result["request_count"] == len(starts) == 17
    assert starts[0] == 0
    assert starts[1:3] == [3, 8]
    assert all(later - earlier >= 3 for earlier, later in pairwise(starts))
    assert clock.sleeps[0] == pytest.approx(2.75)
    assert len(clock.sleeps) == 15  # The five-second response already provides spacing.


def test_replay_paces_across_more_than_thirty_requests():
    clock, starts = VirtualClock(), []

    def handler(request):
        starts.append(clock.value)
        return response()

    result = run(
        handler,
        replay_date=date(2026, 10, 23),
        clock=clock.monotonic,
        sleep=clock.sleep,
    )
    assert result["request_count"] == 38
    assert all(
        sum(start - 60 < other <= start for other in starts) <= 20 for start in starts
    )
    assert starts[-1] == 111


@pytest.mark.parametrize(
    "status,classification",
    [
        (402, "daily_request_limit"),
        (429, "recent_60_second_rate_limit"),
    ],
)
def test_limit_error_stops_without_retry_and_preserves_only_safe_headers(
    status, classification
):
    clock, starts = VirtualClock(), []

    def handler(request):
        starts.append(clock.value)
        headers = {
            "X-UsageLimit-Limit": "100",
            "X-UsageLimit-Remaining": "46",
            "X-RateLimit-Limit": "30",
            "X-RateLimit-Remaining": "28",
            "X-Private": TOKEN,
        }
        if len(starts) == 1:
            return response(headers=headers)
        return httpx.Response(status, headers=headers, text=f"{TOKEN} {request.url}")

    result = run(handler, clock=clock.monotonic, sleep=clock.sleep)
    assert starts == [0, 3]
    assert clock.sleeps == [3]
    assert result["state"] == "failed"
    assert result["request_count"] == 2
    observed = result["request_observations"][-1]
    assert observed["status_code"] == status
    assert observed["limit_classification"] == classification
    assert observed["limit_headers"] == {
        "x-usagelimit-limit": "100",
        "x-usagelimit-remaining": "46",
        "x-ratelimit-limit": "30",
        "x-ratelimit-remaining": "28",
    }
    assert TOKEN not in json.dumps(result)
    assert "api_token" not in json.dumps(result)


@pytest.mark.parametrize("value", ["30.0", "-1", "+30", "３０", TOKEN, "30 extra", ""])
def test_non_ascii_or_non_numeric_limit_headers_are_discarded(value):
    def handler(request):
        return httpx.Response(
            429,
            text=f"{TOKEN} private error body",
            headers=[
                (b"x-ratelimit-limit", b"30"),
                (b"x-ratelimit-remaining", value.encode("utf-8")),
                (b"x-private-debug", TOKEN.encode("ascii")),
            ],
        )

    result = run(handler)
    assert result["request_observations"][0]["limit_headers"] == {
        "x-ratelimit-limit": "30"
    }
    assert TOKEN not in json.dumps(result)
    assert "private error body" not in json.dumps(result)


def test_missing_token_and_naive_time_are_rejected():
    with pytest.raises(probe.ProbeError, match="MARKETAUX_API_TOKEN"):
        probe.probe(run=True, now=NOW)
    with pytest.raises(probe.ProbeError, match="timezone"):
        probe.probe(now=NOW.replace(tzinfo=None))


def test_zero_results_are_complete_but_not_daily_coverage_guarantee():
    result = run(lambda request: response(), repeat=True)
    assert result["state"] == "complete"
    assert result["checkpoint_advance"]
    assert result["request_count"] == 9
    assert all(q["zero_results"] for q in result["queries"])
    assert result["sample_status"] == "limited_sample"
    assert "weekday" in " ".join(result["limitations"])


def test_overlap_and_repeated_page_uuids_are_merged():
    def handler(request):
        return response([item(timestamp="2026-10-24T11:29:30Z")])

    result = run(handler, repeat=True)
    assert result["state"] == "complete"
    assert result["unique_uuids"] == 1
    assert len(result["articles"][0]["observations"]) == 8
    assert result["queries"][0]["new_uuids"] == 1
    assert result["queries"][4]["duplicate_uuids"] == 1
    assert result["repeat"]["same_uuids"] == 1
    assert result["repeat"]["new_uuids"] == 0
    assert "Do not save this body" not in json.dumps(result)
    assert "private excerpt" not in json.dumps(result)


def test_partial_requires_all_pages_and_holds_checkpoint_at_request_cap():
    def handler(request):
        page = int(request.url.params["page"])
        start = datetime.fromisoformat(request.url.params["published_after"]).replace(
            tzinfo=UTC
        )
        data = [
            item(page * 10 + i, timestamp=(start + timedelta(minutes=1)).isoformat())
            for i in range(3)
        ]
        return response(data, found=12, page=page)

    result = run(handler, repeat=True)
    assert result["state"] == "partial"
    assert not result["checkpoint_advance"]
    assert result["request_count"] == 17
    assert all(
        q["state"] == "partial" and not q["checkpoint_advance"]
        for q in result["queries"]
    )
    assert all(len(q["pages"]) == 2 for q in result["queries"])


def test_duplicate_across_pages_does_not_falsely_complete_collection():
    def handler(request):
        page = int(request.url.params["page"])
        stamp = request.url.params["published_before"] + "Z"
        return response(
            [item(i, timestamp=stamp) for i in (1, 2, 3)], found=6, page=page
        )

    result = run(handler)
    assert result["state"] == "partial"
    assert not result["checkpoint_advance"]


@pytest.mark.parametrize("status", [401, 429, 500])
def test_http_failure_stops_immediately_and_is_not_zero(status):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, text=f"{TOKEN} {request.url}")

    result = run(handler, repeat=True)
    assert len(calls) == result["request_count"] == 1
    assert result["state"] == "failed"
    assert result["queries"][0]["state"] == "failed"
    assert result["queries"][1]["state"] == "skipped"
    assert not result["checkpoint_advance"]
    assert TOKEN not in json.dumps(result)
    assert "api_token" not in json.dumps(result)


def test_transport_failure_does_not_include_exception_or_token():
    def handler(request):
        raise httpx.ConnectError(f"{request.url} {TOKEN}", request=request)

    result = run(handler)
    assert result["state"] == "failed"
    assert TOKEN not in json.dumps(result)
    assert "api_token" not in json.dumps(result)


@pytest.mark.parametrize("stamp", [None, "unknown", "2026-10-24T11:30:00"])
def test_unknown_time_is_partial_and_checkpoint_is_held(stamp):
    result = run(lambda request: response([item(timestamp=stamp)]))
    assert result["state"] == "partial"
    assert not result["checkpoint_advance"]


def test_invalid_schema_is_failed_not_empty():
    result = run(lambda request: httpx.Response(200, json={"meta": {}, "data": []}))
    assert result["state"] == "failed"
    assert result["request_count"] == 1


def test_echoed_token_in_metadata_is_removed():
    result = run(lambda request: response([item(source=TOKEN)]))
    assert TOKEN not in json.dumps(result)
    assert result["articles"][0]["source"] == "[REDACTED]"


def test_found_changes_between_pages_prevent_checkpoint():
    def handler(request):
        page = int(request.url.params["page"])
        stamp = request.url.params["published_before"] + "Z"
        if page == 1:
            return response([item(i, timestamp=stamp) for i in (1, 2, 3)], found=4)
        return response([item(i, timestamp=stamp) for i in (4, 5)], found=5, page=2)

    result = run(handler)
    assert all(not q["checkpoint_advance"] for q in result["queries"])


def test_changed_repeat_page_holds_checkpoint_without_event_equivalence_claim():
    calls = []

    def handler(request):
        calls.append(request)
        stamp = request.url.params["published_before"] + "Z"
        return response([item(2 if len(calls) == 9 else 1, timestamp=stamp)])

    result = run(handler, repeat=True)
    assert result["request_count"] == 9
    assert result["state"] == "partial"
    assert not result["checkpoint_advance"]
    assert result["repeat"]["new_uuids"] == 1
    assert result["repeat"]["missing_previous_uuids"] == 1


def test_failure_after_success_preserves_observations_and_holds_global_checkpoint():
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 2:
            return httpx.Response(429)
        return response([item(timestamp=request.url.params["published_before"] + "Z")])

    result = run(handler)
    assert result["state"] == "failed"
    assert result["request_count"] == 2
    assert result["unique_uuids"] == 1
    assert result["queries"][0]["state"] == "complete"
    assert result["queries"][1]["state"] == "failed"
    assert not result["checkpoint_advance"]


def test_day_replay_covers_overnight_and_seventeen_followups_then_morning():
    result = probe.probe(now=NOW, replay_date=date(2026, 10, 23))
    jobs = result["queries"]
    assert len(jobs) == 38
    assert result["request_cap"] == 60
    assert jobs[0]["nominal_after_utc"] == "2026-10-22T08:30:00+00:00"
    assert jobs[0]["nominal_before_utc"] == "2026-10-23T00:00:00+00:00"
    assert jobs[2]["nominal_after_utc"] == jobs[0]["nominal_before_utc"]
    assert jobs[34]["nominal_before_utc"] == "2026-10-23T08:30:00+00:00"
    assert jobs[36]["query"] == "macro_policy"
    assert jobs[36]["nominal_after_utc"] == "2026-10-21T22:30:00+00:00"
    assert jobs[36]["nominal_before_utc"] == "2026-10-22T22:30:00+00:00"
    assert jobs[36]["parameters"]["published_after"] == "2026-10-21T22:29:00"


def test_day_replay_budget_strictly_caps_requests_and_skips_remaining_jobs():
    def handler(request):
        page = int(request.url.params["page"])
        stamp = request.url.params["published_before"] + "Z"
        return response(
            [item(page * 10 + i, timestamp=stamp) for i in range(3)],
            found=100,
            page=page,
        )

    result = run(handler, replay_date=date(2026, 10, 23))
    assert result["request_count"] == 60
    assert sum(q["state"] == "partial" for q in result["queries"]) == 6
    assert sum(q["state"] == "skipped" for q in result["queries"]) == 32
    assert not result["checkpoint_advance"]
    assert result["queries"][0]["required_pages_first_found"] == 34


def test_empty_day_replay_is_complete_with_38_requests_but_only_historical_scope():
    result = run(lambda request: response(), replay_date=date(2026, 10, 23))
    assert result["request_count"] == 38
    assert result["state"] == "complete"
    assert "not live" in result["limitations"][0]


@pytest.mark.parametrize(
    "day", [date(2026, 10, 24), date(2026, 10, 17), date(2026, 10, 11)]
)
def test_replay_date_cannot_escape_recent_weekday_scope(day):
    with pytest.raises(probe.ProbeError, match="replay date"):
        probe.probe(now=NOW, replay_date=day)


def test_replay_does_not_allow_an_extra_repeat_and_evidence_signals_store_no_text():
    with pytest.raises(probe.ProbeError, match="cannot use --repeat"):
        probe.probe(now=NOW, replay_date=date(2026, 10, 23), repeat=True)
    raw = item(
        description="Example announced 2026 Q3 revenue of USD 10, pending approval.",
        entities=[{"name": "Example", "symbol": "EXM"}],
    )
    signals = probe.evidence_signals(raw)
    assert all(
        value is True for key, value in signals.items() if key != "classification"
    )
    assert "revenue" not in json.dumps(signals)
