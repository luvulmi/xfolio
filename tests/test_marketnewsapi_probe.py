"""MarketNewsAPI sample guardrails without external requests."""

import importlib.util
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

SPEC = importlib.util.spec_from_file_location(
    "marketnewsapi_probe",
    Path(__file__).resolve().parents[1]
    / "scripts/experiments/marketnewsapi_sample_probe.py",
)
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)
NOW = datetime(2026, 10, 25, 12, tzinfo=UTC)
KEY = "test-secret-never-print"


def test_dry_run_does_not_send_key_or_request():
    def blocked(request):
        pytest.fail("dry run sent a request")

    result = probe.probe(key=KEY, now=NOW, transport=httpx.MockTransport(blocked))
    assert result["mode"] == "dry_run"
    assert result["max_requests"] == 6
    assert len(result["queries"]) == 6
    assert KEY not in json.dumps(result)


def test_real_probe_limits_requests_and_saves_metadata_only():
    requests = []

    def handler(request):
        requests.append(request)
        kind = request.url.params["type"]
        symbol = request.url.params["tickers"]
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": f"art_{symbol}_{kind}",
                        "title": "Example title",
                        "url": "https://example.com/story",
                        "source": {"name": "Example source"},
                        "published_at": "2026-10-24T12:00:00Z",
                        "ingested_at": "2026-10-24T12:00:05Z",
                        "type": kind,
                        "tickers": [symbol],
                        "snippet": "DO_NOT_SAVE_SNIPPET",
                        "summary": "DO_NOT_SAVE_SUMMARY",
                        "body": "DO_NOT_SAVE_BODY" if kind == "press_release" else None,
                    }
                ],
                "meta": {
                    "count": 1,
                    "plan": "free",
                    "delayed_minutes": 15,
                    "next_cursor": "opaque_cursor",
                },
            },
        )

    result = probe.probe(
        run=True,
        key=KEY,
        limit=1,
        now=NOW,
        transport=httpx.MockTransport(handler),
    )
    rendered = json.dumps(result)
    assert len(requests) == 6
    assert all(
        request.headers["Authorization"] == f"Bearer {KEY}" for request in requests
    )
    assert all(request.url.params["limit"] == "1" for request in requests)
    assert all(query["response"]["has_next_cursor"] for query in result["queries"])
    assert all(
        query["response"]["articles"][0]["symbol_tag_matches"]
        for query in result["queries"]
    )
    assert (
        result["queries"][0]["response"]["articles"][0]["published_at_utc"]
        == "2026-10-24T12:00:00+00:00"
    )
    assert "DO_NOT_SAVE" not in rendered
    assert "Example title" not in rendered
    assert KEY not in rendered
    assert "opaque_cursor" not in rendered


def test_http_error_does_not_expose_response_or_key():
    def handler(request):
        return httpx.Response(401, text=f"private {KEY}")

    with pytest.raises(probe.ProbeError, match="status 401") as error:
        probe.probe(run=True, key=KEY, now=NOW, transport=httpx.MockTransport(handler))
    assert KEY not in str(error.value)
