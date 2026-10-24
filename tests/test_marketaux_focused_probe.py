"""좁힌 검색 시험의 요청 예산·간격·페이지·비밀 비노출을 모의 통신으로 검사한다."""

import importlib.util
import json
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path
from uuid import UUID

import httpx
import pytest

SPEC = importlib.util.spec_from_file_location(
    "focused_probe",
    Path(__file__).resolve().parents[1]
    / "scripts/experiments/marketaux_focused_probe.py",
)
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)
NOW = datetime(2026, 10, 24, 13, tzinfo=UTC)
TOKEN = "test-secret-never-print"


def article(number=1, **overrides):
    return {
        "uuid": str(UUID(int=number)),
        "url": "https://example.com/news",
        "source": "example.com",
        "published_at": "2026-10-22T12:00:00Z",
        "description": "Sensitive description",
        "snippet": "Private snippet",
        **overrides,
    }


def response(data=None, found=None, page=1, **kwargs):
    data = [] if data is None else data
    return httpx.Response(
        200,
        json={
            "meta": {
                "found": len(data) if found is None else found,
                "returned": len(data),
                "limit": 3,
                "page": page,
            },
            "data": data,
        },
        **kwargs,
    )


def run(handler, **kwargs):
    elapsed = [0.0]

    def sleep(seconds):
        elapsed[0] += seconds

    return probe.probe(
        run=True,
        token=TOKEN,
        now=NOW,
        transport=httpx.MockTransport(handler),
        clock=lambda: elapsed[0],
        sleep=sleep,
        **kwargs,
    )


def test_dryrun_has_fixed_window_focused_filters_and_no_network():
    result = probe.probe(now=NOW)
    assert result["request_cap"] == 12
    assert result["request_count"] == 0
    assert len(result["queries"]) == 8
    params = result["queries"][0]["parameters"]
    assert params["published_after"] == "2026-10-21T22:29:00"
    assert params["published_before"] == "2026-10-22T22:30:00"
    assert params["group_similar"] == "false"
    assert params["limit"] == 3
    assert "reuters.com" in params["domains"]
    assert not result["checkpoint_advance"]


def test_missing_token_or_bad_reference_fails_without_network():
    with pytest.raises(probe.ProbeError, match="MARKETAUX_API_TOKEN"):
        probe.probe(run=True, now=NOW)
    with pytest.raises(probe.ProbeError, match="timezone"):
        probe.probe(now=NOW.replace(tzinfo=None))
    with pytest.raises(probe.ProbeError, match="seven-day"):
        probe.probe(now=datetime(2026, 11, 24, tzinfo=UTC))


def test_pacer_enforces_three_second_request_starts_and_whitelists_numeric_headers():
    elapsed, starts = [0.0], []

    def sleep(seconds):
        elapsed[0] += seconds

    def handler(request):
        starts.append(elapsed[0])
        assert request.url.params["group_similar"] == "false"
        return response(
            headers={
                "x-usagelimit-remaining": "45",
                "x-ratelimit-remaining": TOKEN,
                "x-secret": TOKEN,
                "x-usagelimit-limit": "100",
            }
        )

    result = probe.probe(
        run=True,
        token=TOKEN,
        now=NOW,
        transport=httpx.MockTransport(handler),
        clock=lambda: elapsed[0],
        sleep=sleep,
    )
    assert len(starts) == 8
    assert all(b - a >= 3 for a, b in pairwise(starts))
    assert result["state"] == "complete"
    assert result["checkpoint_advance"]
    assert result["requests"][0]["limit_headers"] == {
        "x-usagelimit-limit": "100",
        "x-usagelimit-remaining": "45",
    }
    assert TOKEN not in json.dumps(result)


def test_budget_limits_to_twelve_requests_and_partial_does_not_advance():
    def handler(request):
        page = int(request.url.params["page"])
        return response(
            [article(page * 10 + i) for i in range(3)], found=100, page=page
        )

    result = run(handler)
    assert result["request_count"] == 12
    assert result["queries"][0]["state"] == "partial"
    assert sum(q["state"] == "skipped" for q in result["queries"]) == 7
    assert not result["checkpoint_advance"]
    assert result["queries"][0]["required_pages_first_found"] == 34


def test_complete_fixed_window_does_not_mark_partial_supplement_complete():
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 5:
            return response([article(i) for i in (1, 2, 3)], found=4)
        return response()

    result = run(handler)
    assert result["state"] == "partial"
    assert result["fixed_window_checkpoint_eligible"]
    assert not result["checkpoint_advance"]


@pytest.mark.parametrize("status", [401, 402, 429, 500])
def test_error_stops_at_first_request_and_does_not_log_response(status):
    result = run(lambda request: httpx.Response(status, text=f"{TOKEN} {request.url}"))
    assert result["state"] == "failed"
    assert result["request_count"] == 1
    assert sum(q["state"] == "skipped" for q in result["queries"]) == 7
    assert not result["checkpoint_advance"]
    assert TOKEN not in json.dumps(result)
    assert "api_token" not in json.dumps(result)


def test_dedup_and_memory_review_callback_never_persist_text():
    reviewed = []
    result = run(
        lambda request: response([article()]),
        review_callback=lambda item, scope, query: reviewed.append(item["description"]),
    )
    assert result["unique_uuids"] == 1
    assert len(reviewed) == 1
    assert len(result["articles"][0]["observations"]) == 8
    output = json.dumps(result)
    assert "Sensitive description" not in output
    assert "Private snippet" not in output


def test_unknown_time_is_partial_and_api_error_is_failed():
    result = run(lambda request: response([article(published_at=None)]))
    assert result["state"] == "partial"
    assert not result["checkpoint_advance"]
    result = run(
        lambda request: httpx.Response(200, json={"error": {"message": TOKEN}})
    )
    assert result["state"] == "failed"
    assert TOKEN not in json.dumps(result)


def test_changed_found_or_duplicate_pages_never_marks_complete():
    def handler(request):
        page = int(request.url.params["page"])
        if page == 1:
            return response([article(i) for i in (1, 2, 3)], found=4)
        return response([article(3)], found=4, page=2)

    result = run(handler)
    assert result["queries"][0]["state"] == "partial"
    assert result["queries"][0]["duplicate_uuids"] == 1
    assert not result["checkpoint_advance"]


def test_transport_failure_is_controlled_and_secret_free():
    def handler(request):
        raise httpx.ConnectError(f"{request.url} {TOKEN}", request=request)

    result = run(handler)
    assert result["request_count"] == 1
    assert result["state"] == "failed"
    assert TOKEN not in json.dumps(result)


def test_echoed_secret_is_redacted_from_metadata_and_memory_review_callback():
    reviewed = []
    result = run(
        lambda request: response([article(source=TOKEN, description=TOKEN)]),
        review_callback=lambda item, *_: reviewed.append(item),
    )
    assert TOKEN not in json.dumps(result)
    assert TOKEN not in json.dumps(reviewed)
    assert result["articles"][0]["source"] == "[REDACTED]"
