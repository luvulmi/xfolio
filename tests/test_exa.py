"""Exa 수집은 전부 합성 응답·MockTransport로 검사한다."""

import json
import logging
import socket
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from pydantic import SecretStr

from xfolio.exa import ExaConfig, ExaError, ExaQuery, collect_exa
from xfolio.news_input import InputRights

NOW = datetime(2026, 10, 31, tzinfo=UTC)
KEY = "fixture-secret-never-log"
URL = "https://example.invalid/story"
CONFIG = ExaConfig(queries=(ExaQuery(query_id="one", query="US market news"),))


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("external_network_forbidden")

    monkeypatch.setattr(socket.socket, "connect", blocked)


def rights(**updates):
    return InputRights.model_validate(
        {
            "collection": "permitted",
            "review_id": "fixture-review",
            "reviewed_by": "tester",
            "reviewed_at": NOW - timedelta(days=1),
            "policy_reference": "synthetic fixture only",
        }
        | updates
    )


def article(**updates):
    return {
        "id": URL,
        "url": URL,
        "title": "Synthetic news",
        "publishedDate": "2026-10-30T20:00:00Z",
        "text": "Synthetic body with context.",
    } | updates


def payload(results=None, **updates):
    return {
        "results": [article()] if results is None else results,
        "costDollars": {"total": 0.007},
    } | updates


def collect(handler, **updates):
    calls = []

    def capture(request):
        calls.append(request)
        return handler(request)

    with httpx.Client(transport=httpx.MockTransport(capture)) as client:
        result = collect_exa(
            **(
                {
                    "client": client,
                    "api_key": SecretStr(KEY),
                    "rights": rights(),
                    "window_start": NOW - timedelta(days=1),
                    "window_end": NOW,
                    "run_id": "fixture-run",
                    "config": CONFIG,
                    "clock": lambda: NOW,
                    "synthetic": True,
                }
                | updates
            )
        )
    return result, calls


def test_search_request_contract_and_unreviewed_body_are_preserved():
    query = ExaQuery(
        query_id="one",
        query="US market news",
        include_domains=("example.invalid",),
        exclude_domains=("other.invalid",),
    )
    result, calls = collect(
        lambda r: httpx.Response(200, json=payload()),
        config=ExaConfig(queries=(query,)),
    )
    assert len(calls) == 1 and calls[0].method == "POST"
    body = json.loads(calls[0].content)
    assert body["type"] == "auto" and body["category"] == "news"
    assert body["includeDomains"] == ["example.invalid"]
    assert body["excludeDomains"] == ["other.invalid"]
    assert body["contents"]["maxAgeHours"] == -1
    assert body["contents"]["text"]["maxCharacters"] == 20000
    assert calls[0].headers["x-api-key"] == KEY
    run = result.collection
    assert run.status == "complete" and not run.normal_zero
    item = run.records[0]
    assert item.publisher == "example.invalid" and item.source_id == "exa"
    assert item.content.sufficiency == "not_assessed" and not item.publication.reliable
    assert item.document_type == "unknown"
    assert item.rights.ai_transfer == "pending_review"
    assert KEY not in result.model_dump_json()


def test_empty_all_required_searches_is_normal_zero_without_contents():
    result, calls = collect(
        lambda r: httpx.Response(200, json=payload([])), config=ExaConfig()
    )
    assert len(calls) == 3
    assert result.collection.normal_zero and result.collection.no_updates
    assert len(result.collection.reports) == 3


def test_missing_body_is_fetched_once_in_cache_and_scope_references_stay_linked():
    def handler(request):
        if request.url.path == "/search":
            return httpx.Response(200, json=payload([article(text=None)]))
        assert json.loads(request.content)["urls"] == [URL]
        return httpx.Response(
            200, json=payload(statuses=[{"id": URL, "status": "success"}])
        )

    result, calls = collect(handler)
    run = result.collection
    assert len(calls) == 2 and run.status == "complete"
    assert run.required_scope_ids == ("search:one", "contents:one")
    assert len(run.records) == 1 and run.records[0].content.text
    assert run.reports[0].input_ids == run.reports[1].input_ids


@pytest.mark.parametrize(
    "bad_statuses",
    [
        [],
        [{"id": URL, "status": "error"}],
        [{"id": URL, "status": "success"}, {"id": URL, "status": "success"}],
    ],
)
def test_contents_missing_or_failed_status_is_partial_and_keeps_discovery(bad_statuses):
    def handler(request):
        return httpx.Response(
            200,
            json=payload([article(text=None)])
            if request.url.path == "/search"
            else payload(statuses=bad_statuses),
        )

    result, _ = collect(handler)
    assert result.collection.status == "partial"
    assert not result.collection.normal_zero and len(result.collection.records) == 1
    assert result.collection.records[0].available_at is None


@pytest.mark.parametrize("status", [401, 402, 403, 429])
def test_auth_credit_and_rate_failure_stop_remaining_requests(status):
    result, calls = collect(
        lambda r: httpx.Response(status, text=KEY), config=ExaConfig()
    )
    assert len(calls) == 1 and result.collection.status == "failed"
    assert not result.collection.normal_zero
    assert KEY not in result.model_dump_json()


def test_transport_failure_is_safe_and_not_retried():
    def handler(request):
        raise httpx.ConnectError(KEY, request=request)

    result, calls = collect(handler, config=ExaConfig())
    assert len(calls) == 1 and result.collection.status == "failed"
    assert result.collection.reports[0].error_codes[0] == "transport_error"
    assert KEY not in result.model_dump_json()


def test_request_cap_and_partial_body_failure_keep_successful_input():
    result, calls = collect(
        lambda r: httpx.Response(200, json=payload()), config=ExaConfig(max_requests=1)
    )
    assert len(calls) == 1 and result.collection.status == "partial"
    assert len(result.collection.records) == 1
    assert "request_budget" in result.collection.reports[1].error_codes


@pytest.mark.parametrize("cost", [None, "NaN", -1, True])
def test_unknown_or_invalid_cost_stops_and_is_never_zero(cost):
    result, calls = collect(
        lambda r: httpx.Response(200, json=payload(costDollars={"total": cost})),
        config=ExaConfig(),
    )
    assert len(calls) == 1 and result.collection.status == "partial"
    assert result.collection.response_cost_usd is None
    assert "cost_unknown" in result.collection.reports[0].error_codes


def test_response_cost_over_reserve_stops_and_is_still_recorded():
    result, calls = collect(
        lambda r: httpx.Response(200, json=payload(costDollars={"total": ".03"})),
        config=ExaConfig(),
    )
    assert len(calls) == 1
    assert str(result.collection.reports[0].response_cost_usd) == "0.03"
    assert result.collection.status == "partial"
    assert "cost_budget" in result.collection.reports[0].error_codes


def test_cost_reservation_blocks_next_request_before_http():
    result, calls = collect(
        lambda r: httpx.Response(200, json=payload([])),
        config=ExaConfig(max_response_cost_usd=".02", request_cost_reserve_usd=".02"),
    )
    assert len(calls) == 1 and result.collection.status == "partial"
    assert "cost_budget" in result.collection.reports[1].error_codes


@pytest.mark.parametrize(
    "data",
    [
        {},
        {"results": "bad"},
        {"results": [None]},
        payload([article(url="https://example.invalid?api_key=hidden")]),
        payload([article(publishedDate="tomorrow")]),
        payload([article(publishedDate="2026-11-01T00:00:00Z")]),
    ],
)
def test_malformed_and_future_inputs_never_become_normal_zero(data):
    result, _ = collect(lambda r: httpx.Response(200, json=data))
    assert result.collection.status == "failed" and not result.collection.normal_zero


@pytest.mark.parametrize("stamp", ["2026-10-30", "2026-10-30T00:00:00Z", None])
def test_date_midnight_and_missing_publication_are_retained_unverified(stamp):
    result, _ = collect(
        lambda r: httpx.Response(200, json=payload([article(publishedDate=stamp)]))
    )
    item = result.collection.records[0]
    assert not item.publication.reliable
    assert item.publication.raw == stamp
    if stamp == "2026-10-30":
        assert item.publication.value is None and item.publication.precision == "date"


def test_same_url_is_deduplicated_and_conflicting_versions_are_partial():
    calls = [0]

    def handler(request):
        calls[0] += 1
        return httpx.Response(
            200,
            json=payload([article(text="Changed body" if calls[0] == 3 else "Body")]),
        )

    result, _ = collect(handler, config=ExaConfig())
    assert result.collection.status == "partial" and len(result.collection.records) == 1
    assert "article_conflict" in result.collection.reports[2].error_codes


def test_recheck_preserves_first_capture_and_new_source_links_previous():
    first, _ = collect(lambda r: httpx.Response(200, json=payload()))
    old = first.collection.records[0]
    again, _ = collect(
        lambda r: httpx.Response(200, json=payload()),
        clock=lambda: NOW + timedelta(hours=1),
        previous_records=(old,),
    )
    assert again.collection.no_updates
    assert again.collection.records[0].available_at == old.available_at
    changed, _ = collect(
        lambda r: httpx.Response(200, json=payload([article(text="Corrected body")])),
        clock=lambda: NOW + timedelta(hours=1),
        previous_records=(old,),
    )
    assert changed.collection.records[0].supersedes == old.input_id
    assert changed.collection.records[0].available_at > old.available_at


def test_credentials_echo_and_debug_logs_are_not_returned(caplog):
    def handler(request):
        logging.getLogger("httpx").warning("header %s", KEY)
        return httpx.Response(200, json=payload([article(text=KEY)]))

    with caplog.at_level(logging.DEBUG):
        result, calls = collect(handler)
    assert (
        len(calls) == 1
        and "credential_echo" in result.collection.reports[0].error_codes
    )
    assert KEY not in result.model_dump_json() and KEY not in caplog.text


def test_escaped_key_echo_is_also_rejected():
    body = json.dumps(payload([article(text=KEY)])).replace(KEY, "\\u0066" + KEY[1:])
    result, _ = collect(lambda r: httpx.Response(200, text=body))
    assert result.collection.reports[0].error_codes[0] == "credential_echo"
    assert KEY not in result.model_dump_json()


def test_provider_domain_filter_violation_is_not_accepted():
    config = ExaConfig(
        queries=(
            ExaQuery(
                query_id="one", query="news", include_domains=("allowed.invalid",)
            ),
        )
    )
    result, _ = collect(lambda r: httpx.Response(200, json=payload()), config=config)
    assert result.collection.status == "failed" and not result.collection.normal_zero


def test_missing_contents_response_url_cannot_be_replaced_with_unrequested_url():
    def handler(request):
        return httpx.Response(
            200,
            json=payload([article(text=None)])
            if request.url.path == "/search"
            else payload(
                [article(url="https://other.invalid/story")],
                statuses=[{"id": URL, "status": "success"}],
            ),
        )

    result, _ = collect(handler)
    assert (
        result.collection.status == "partial"
        and result.collection.records[0].available_at is None
    )


def test_query_configuration_changes_have_distinct_version_fingerprints():
    changed = ExaConfig(queries=(ExaQuery(query_id="one", query="different news"),))
    assert changed.fingerprint != CONFIG.fingerprint
    assert (
        ExaConfig.model_validate_json(CONFIG.model_dump_json()).fingerprint
        == CONFIG.fingerprint
    )


def test_provider_record_id_and_original_timezone_are_preserved():
    result, _ = collect(
        lambda r: httpx.Response(
            200,
            json=payload(
                [
                    article(
                        id="provider-doc-id", publishedDate="2026-10-30T16:00:00-04:00"
                    )
                ]
            ),
        )
    )
    item = result.collection.records[0]
    assert item.source_record_id == "provider-doc-id"
    assert (
        item.publication.raw.endswith("-04:00") and item.publication.timezone != "UTC"
    )


@pytest.mark.parametrize(
    "updates",
    [
        {"rights": InputRights()},
        {"rights": rights(expires_at=NOW)},
        {"window_end": NOW + timedelta(seconds=1)},
        {"window_start": NOW - timedelta(days=8)},
    ],
)
def test_invalid_or_unpermitted_collection_makes_no_request(updates):
    with pytest.raises((ExaError, ValueError)):
        collect(lambda r: pytest.fail("must not call"), **updates)


def test_same_body_with_changed_publication_metadata_is_partial():
    first, _ = collect(lambda r: httpx.Response(200, json=payload()))
    result, _ = collect(
        lambda r: httpx.Response(
            200, json=payload([article(publishedDate="2026-10-30T21:00:00Z")])
        ),
        previous_records=first.collection.records,
    )
    assert result.collection.status == "partial" and not result.collection.no_updates
    assert result.collection.reports[0].error_codes == ("article_conflict",)


def test_same_provider_record_id_with_different_urls_is_partial():
    result, _ = collect(
        lambda r: httpx.Response(
            200,
            json=payload(
                [article(), article(url="https://other.invalid/story", text=None)]
            ),
        )
    )
    assert result.collection.status == "partial" and len(result.collection.records) == 1


def test_body_repeating_the_title_is_marked_without_claiming_sufficiency():
    result, _ = collect(
        lambda r: httpx.Response(
            200, json=payload([article(title="Only a title", text="Only a title")])
        )
    )
    assert result.collection.records[0].content.title_only
    assert result.collection.records[0].content.sufficiency == "not_assessed"
