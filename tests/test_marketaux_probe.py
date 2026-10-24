"""Marketaux 실험의 요청 상한·실패·메타데이터만의 출력을 네트워크 없이 검사한다."""

import importlib.util
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import httpx
import pytest

SPEC = importlib.util.spec_from_file_location(
    "marketaux_probe",
    Path(__file__).resolve().parents[1]
    / "scripts/experiments/marketaux_sample_probe.py",
)
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)
NOW = datetime(2026, 10, 24, 12, tzinfo=UTC)
TOKEN = "test-secret-never-print"


def article(number=1, **overrides):
    return {
        "uuid": str(UUID(int=number)),
        "url": f"https://example.com/{number}",
        "source": "example.com",
        "published_at": "2026-10-24T01:00:00.000000Z",
        "title": "Sample original headline",
        "description": "Private excerpt",
        "snippet": "Private snippet",
        "entities": [{"symbol": "AAPL", "name": "Apple"}],
        **overrides,
    }


def payload(data=None, found=None, page=1, **meta):
    data = [article()] if data is None else data
    return {
        "meta": {
            "found": len(data) if found is None else found,
            "returned": len(data),
            "limit": 3,
            "page": page,
            **meta,
        },
        "data": data,
    }


def run(handler, **kwargs):
    return probe.probe(
        run=True, token=TOKEN, now=NOW, transport=httpx.MockTransport(handler), **kwargs
    )


def test_dry_run_has_no_network_or_token_and_macro_has_no_entity_filters():
    def blocked(request):
        pytest.fail("dry-run must not request")

    result = probe.probe(token=TOKEN, now=NOW, transport=httpx.MockTransport(blocked))
    assert result["mode"] == "dry_run"
    assert result["max_requests"] == 4
    assert result["published_after_utc"] == "2026-10-22T12:00:00+00:00"
    for query in result["queries"][:2]:
        assert (
            not {"symbols", "countries", "entity_types", "must_have_entities"}
            & query["parameters"].keys()
        )
    assert TOKEN not in json.dumps(result)


def test_run_requires_token():
    with pytest.raises(probe.ProbeError, match="MARKETAUX_API_TOKEN"):
        probe.probe(run=True, now=NOW)


def test_valid_metadata_deduplicates_and_never_returns_original_text():
    calls = []

    def handler(request):
        calls.append(request)
        assert request.url.params["api_token"] == TOKEN
        assert request.url.params["sort"] == "published_at"
        assert request.url.params["limit"] == "3"
        return httpx.Response(200, json=payload())

    result = run(handler)
    assert len(calls) == 4
    assert len(result["articles"]) == 1
    item = result["articles"][0]
    assert len(item["matched_queries"]) == 4
    assert item["description_chars"] == len("Private excerpt")
    assert item["eligible_for_review"]
    assert item["selected_entities"] == [{"symbol": "AAPL", "name": "Apple"}]
    output = json.dumps(result)
    for excluded in (
        "Private excerpt",
        "Private snippet",
        "Sample original headline",
        TOKEN,
    ):
        assert excluded not in output


def test_zero_is_successful_empty_sample():
    result = run(lambda request: httpx.Response(200, json=payload([])), pages=2)
    assert result["articles"] == []
    assert all(
        q["zero_results"] and not q["incomplete"] and len(q["pages"]) == 1
        for q in result["queries"]
    )


@pytest.mark.parametrize("pages, expected", [(1, 4), (2, 8)])
def test_partial_pages_are_marked_and_request_budget_is_bounded(pages, expected):
    calls = []

    def handler(request):
        calls.append(request)
        page = int(request.url.params["page"])
        data = [article((page - 1) * 3 + i) for i in range(1, 4)]
        return httpx.Response(200, json=payload(data, found=20, page=page))

    result = run(handler, pages=pages, days=7)
    assert len(calls) == expected
    assert result["max_requests"] == expected
    assert result["sample_status"] == "limited_sample"
    assert all(q["incomplete"] for q in result["queries"])
    assert len(result["articles"]) == pages * 3
    assert len(result["articles"][0]["matched_queries"]) == 4


@pytest.mark.parametrize("status", [401, 429, 500])
def test_http_errors_stop_without_retry_or_response_body(status):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, text=TOKEN)

    with pytest.raises(probe.ProbeError, match=f"status {status}") as caught:
        run(handler, pages=2)
    assert len(calls) == 1
    assert TOKEN not in str(caught.value)


@pytest.mark.parametrize("error", [httpx.ReadTimeout, httpx.ConnectError])
def test_transport_errors_redact_urls_and_token(error):
    def handler(request):
        raise error(f"failed {request.url} {TOKEN}", request=request)

    with pytest.raises(probe.ProbeError, match="transport failure") as caught:
        run(handler)
    assert TOKEN not in str(caught.value)
    assert "api_token" not in str(caught.value)


@pytest.mark.parametrize(
    "bad",
    [
        {"error": {"message": TOKEN}},
        {"data": []},
        payload(page=2),
        payload(limit=10),
        payload(returned=0),
        payload(found=0),
        payload(found="1"),
        payload([article(uuid="not-a-uuid")]),
        payload([article(source=None)]),
        payload([article(description={})]),
        payload([article(entities="invalid")]),
        payload([article(url="https:invalid")]),
    ],
)
def test_bad_schema_or_api_error_is_not_treated_as_zero(bad):
    with pytest.raises(probe.ProbeError) as caught:
        run(lambda request: httpx.Response(200, json=bad))
    assert TOKEN not in str(caught.value)


def test_invalid_json_is_controlled_error():
    with pytest.raises(probe.ProbeError, match="invalid JSON"):
        run(lambda request: httpx.Response(200, text=TOKEN))


@pytest.mark.parametrize("timestamp", [None, "unknown", "2026-10-24T01:00:00"])
def test_unknown_time_is_explicit_and_ineligible(timestamp):
    result = run(
        lambda request: httpx.Response(
            200, json=payload([article(published_at=timestamp)])
        )
    )
    item = result["articles"][0]
    assert item["published_at"] is None
    assert item["field_states"]["published_at"] == "unknown"
    assert not item["eligible_for_review"]


def test_outside_window_is_not_accepted_and_duplicates_within_page_are_merged():
    value = article(published_at="2026-10-10T01:00:00Z")
    result = run(lambda request: httpx.Response(200, json=payload([value, value])))
    assert len(result["articles"]) == 1
    assert result["articles"][0]["field_states"]["published_at"] == "outside_window"
    assert len(result["articles"][0]["matched_queries"]) == 4


def test_token_echo_in_metadata_is_redacted_even_when_token_needs_json_escaping():
    secret = 'token-"-sensitive'
    value = article(source=secret, entities=[{"symbol": "AAPL", "name": secret}])
    result = probe.probe(
        run=True,
        token=secret,
        now=NOW,
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json=payload([value]))
        ),
    )
    assert result["articles"][0]["source"] == "[REDACTED]"
    assert result["articles"][0]["selected_entities"][0]["name"] == "[REDACTED]"


@pytest.mark.parametrize(
    "kwargs",
    [{"pages": 3}, {"days": 8}, {"days": 0}, {"now": NOW.replace(tzinfo=None)}],
)
def test_invalid_configuration_cannot_expand_request_scope(kwargs):
    with pytest.raises(probe.ProbeError, match="config"):
        probe.probe(**kwargs)


def test_cli_run_without_environment_token_fails(monkeypatch, capsys):
    monkeypatch.delenv("MARKETAUX_API_TOKEN", raising=False)
    with pytest.raises(SystemExit) as caught:
        probe.main(["--run"])
    assert caught.value.code == 1
    assert "MARKETAUX_API_TOKEN is required" in capsys.readouterr().err
