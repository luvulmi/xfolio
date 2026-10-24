"""동일 사건 표본의 비밀/본문 비저장, 부분 수집과 오류 중단 경계."""

import importlib.util
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

SPEC = importlib.util.spec_from_file_location(
    "news_event_compare",
    Path(__file__).resolve().parents[1] / "scripts/experiments/news_event_compare.py",
)
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)
ProbeError = probe.ProbeError
compare = probe.compare

NOW = datetime(2026, 10, 24, 16, tzinfo=UTC)


def manifest(count=1):
    return {
        "version": "test",
        "window_start": "2026-10-20T00:00:00Z",
        "window_end": "2026-10-24T15:00:00Z",
        "cases": [
            {
                "id": str(i),
                "kind": "earnings",
                "event_key": "one_event",
                "search": "test",
                "markers": {"fact": "2.5"},
            }
            for i in range(count)
        ],
    }


def test_partial_sample_stores_no_text_or_token():
    payload = {
        "meta": {"found": 50, "returned": 1, "limit": 3, "page": 1},
        "data": [
            {
                "uuid": "00000000-0000-0000-0000-000000000001",
                "title": "private-title",
                "description": "private-body 2.5",
                "snippet": "secret-token",
                "published_at": "2026-10-21T12:00:00Z",
                "url": "https://example.com/secret-token",
                "source": "example.com",
                "entities": [],
            }
        ],
    }
    report = compare(
        manifest(),
        run=True,
        token="secret-token",
        now=NOW,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=payload)
        ),
    )
    encoded = json.dumps(report)
    assert all(
        value not in encoded
        for value in ("private-title", "private-body", "secret-token")
    )
    assert report["cases"][0]["state"] == "partial_sample"
    assert report["cases"][0]["articles"][0]["marker_matches"] == {"fact": True}
    assert report["can_publish"] is False
    assert report["cursor_written"] is False


@pytest.mark.parametrize("status", [402, 429, 500])
def test_http_error_stops_following_cases(status):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(status, json={"error": "secret-token"})

    report = compare(
        manifest(2),
        run=True,
        token="secret-token",
        now=NOW,
        transport=httpx.MockTransport(handler),
    )
    assert len(seen) == 1
    assert report["state"] == "failed"
    assert report["cases"][1]["state"] == "skipped"
    assert "secret-token" not in json.dumps(report)


def test_dry_run_skips_old_reference_without_network():
    config = manifest(2)
    config["cases"][1]["kind"] = "outside_window"
    report = compare(
        config,
        now=NOW,
        transport=httpx.MockTransport(lambda request: pytest.fail("network")),
    )
    assert report["request_count"] == 0
    assert report["cases"][1]["reason"] == "reference_event_outside_window"


def test_stale_fixed_window_is_rejected():
    with pytest.raises(ProbeError):
        compare(manifest(), now=datetime(2026, 11, 1, tzinfo=UTC))


def test_official_fetch_does_not_treat_http_success_as_parsing_success():
    config = {"cases": [{"id": "a", "official_url": "https://example.com/a"}]}
    report = probe.official_probe(
        config,
        run=True,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                content=b"%PDF-private-content",
                headers={"content-type": "application/pdf"},
            )
        ),
    )
    assert report["cases"][0]["parsed"] is False
    assert report["content_saved"] is False
    assert "private-content" not in json.dumps(report)
