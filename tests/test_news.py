"""News Pipeline의 상태·완전 수집·비밀 보호를 외부 API 없이 검증한다."""

import json
import logging
from datetime import UTC, datetime, timedelta, timezone
from io import StringIO
from urllib.parse import quote, quote_plus
from uuid import UUID

import httpx
import pytest
from pydantic import ValidationError

from xfolio.news import NewsCollectionError, collect_news, metadata_report
from xfolio.news_models import NewsArticle, NewsCollection, NewsQueryReport
from xfolio.news_queries import FOCUSED_QUERIES, NewsQuery

START = datetime(2020, 1, 2, 0, tzinfo=UTC)
END = START + timedelta(minutes=30)
TOKEN = "secret-not-to-save"
QUERIES = (
    NewsQuery("macro", '"Federal Reserve"'),
    NewsQuery("company", "reported", ("example.com",), ("ACME",)),
)


class Clock:
    def __init__(self):
        self.value = 0.0

    def now(self):
        return self.value

    def sleep(self, duration):
        self.value += duration


def article(number=1, **updates):
    return {
        "uuid": str(UUID(int=number)),
        "title": "Synthetic private title",
        "description": "Do not persist this description",
        "snippet": "Do not persist this snippet",
        "source": "example.com",
        "url": f"https://example.com/{number}",
        "published_at": (START + timedelta(minutes=1)).isoformat(),
        **updates,
    }


def response(data=(), *, found=None, page=1, **kwargs):
    return httpx.Response(
        200,
        json={
            "meta": {
                "found": len(data) if found is None else found,
                "returned": len(data),
                "page": page,
                "limit": 3,
            },
            "data": list(data),
        },
        **kwargs,
    )


def run(handler, **kwargs):
    clock = kwargs.pop("clock", Clock())
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        return collect_news(
            start=START,
            end=END,
            queries=kwargs.pop("queries", QUERIES),
            token=TOKEN,
            client=client,
            clock=clock.now,
            sleep=clock.sleep,
            **kwargs,
        )


def test_zero_results_complete_all_queries_without_losing_collection_scope():
    result = run(lambda request: response(), queries=FOCUSED_QUERIES)
    assert result.status == "complete" and result.checkpoint_eligible
    assert result.requests == 4 and result.articles == ()
    assert all(q.status == "complete" for q in result.query_reports)
    assert result.window_start == START and result.window_end == END
    assert result.collected_at.utcoffset() == timedelta(0)


def test_all_pages_paced_and_cross_query_uuid_deduplicated_with_text_only_in_memory():
    clock, starts, bodies = Clock(), [], []

    def handler(request):
        starts.append(clock.value)
        bodies.append(request)
        assert request.url.params["group_similar"] == "false"
        assert request.url.params["published_after"] == "2020-01-02T00:00:00"
        assert request.extensions["timeout"] == dict.fromkeys(
            ("connect", "read", "write", "pool"), 15
        )
        page = int(request.url.params["page"])
        return response(
            [article(n) for n in ((1, 2, 3) if page == 1 else (4,))], found=4, page=page
        )

    result = run(handler, clock=clock)
    assert starts == [0, 3, 6, 9]
    assert result.status == "complete" and len(result.articles) == 4
    assert result.articles[0].title == "Synthetic private title"
    assert bodies[-1].url.params["symbols"] == "ACME"
    assert bodies[-1].url.params["domains"] == "example.com"
    report = json.dumps(metadata_report(result))
    for forbidden in (TOKEN, "api_token", "Synthetic private title", "Do not persist"):
        assert forbidden not in report
    assert metadata_report(result)["articles"][0]["field_lengths"]["title"] > 0


@pytest.mark.parametrize(
    "status,error",
    [
        (402, "daily_request_limit"),
        (429, "rate_limit_60_seconds"),
        (302, "http_error"),
        (500, "http_error"),
    ],
)
def test_http_failure_stops_and_skips_later_queries_without_echoing_body(status, error):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            status,
            text=f"{TOKEN} {request.url}",
            headers={"location": "https://example.com/leak"},
        )

    result = run(handler)
    assert result.status == "failed" and result.error == error
    assert result.requests == len(calls) == 1 and not result.checkpoint_eligible
    assert result.query_reports[0].status == "failed"
    assert result.query_reports[1].status == "skipped"
    assert TOKEN not in json.dumps(metadata_report(result))


def test_network_error_does_not_retry_or_disclose_exception():
    def handler(request):
        raise httpx.ConnectError(f"{TOKEN} {request.url}", request=request)

    result = run(handler)
    assert result.error == "transport_error" and result.requests == 1
    assert TOKEN not in json.dumps(metadata_report(result))


@pytest.mark.parametrize("limits", [{"max_requests": 1}, {"max_pages": 1}])
def test_page_or_request_cap_is_partial_not_zero_or_complete(limits):
    def handler(request):
        return response([article(n) for n in (1, 2, 3)], found=6)

    result = run(handler, **limits)
    assert result.status == "partial" and not result.checkpoint_eligible
    assert result.error in {"request_budget", "page_budget"}
    assert result.requests <= limits.get("max_requests", 12)


@pytest.mark.parametrize("case", ["duplicate", "changed_found"])
def test_duplicate_or_changing_pagination_never_advances_checkpoint(case):
    def handler(request):
        page = int(request.url.params["page"])
        nums = (1, 2, 3) if page == 1 or case == "duplicate" else (4, 5)
        return response(
            [article(n) for n in nums],
            found=6 if case == "duplicate" or page == 1 else 5,
            page=page,
        )

    result = run(handler)
    assert result.status == "partial" and not result.checkpoint_eligible
    assert result.error in {"duplicate_page", "pagination_changed"}


@pytest.mark.parametrize(
    "stamp", [None, "unknown", "2020-01-02T00:10:00", "2020-01-02T01:00:00Z"]
)
def test_missing_naive_or_outside_window_dates_hold_entire_collection(stamp):
    result = run(lambda request: response([article(published_at=stamp)]))
    assert result.status == "partial" and not result.checkpoint_eligible
    assert result.error in {"invalid_publication_time", "article_outside_window"}


@pytest.mark.parametrize(
    "payload", [{}, {"meta": {}, "data": []}, {"error": {"message": TOKEN}}]
)
def test_bad_payload_is_failed_without_logging_provider_error(payload):
    result = run(lambda request: httpx.Response(200, json=payload))
    assert result.status == "failed" and result.requests == 1
    assert TOKEN not in json.dumps(metadata_report(result))


@pytest.mark.parametrize(
    "updates",
    [
        {"uuid": "invalid"},
        {"title": 12},
        {"url": "file:///secret"},
        {"source": TOKEN},
        {"snippet": ["invalid"]},
        {"url": f"https://example.com/?api_token={TOKEN}"},
    ],
)
def test_invalid_or_secret_echoed_article_fails_safely(updates):
    result = run(lambda request: response([article(**updates)]))
    assert result.status == "failed" and not result.checkpoint_eligible
    assert TOKEN not in json.dumps(metadata_report(result))


def test_safe_numeric_headers_only_are_reported_even_on_quota_failure():
    result = run(
        lambda request: httpx.Response(
            429,
            headers=[
                (b"x-usagelimit-limit", b"100"),
                (b"x-ratelimit-limit", b"30"),
                (b"x-ratelimit-remaining", b"-1"),
                (b"x-usagelimit-remaining", "４７".encode()),
                (b"x-debug", TOKEN.encode()),
            ],
        )
    )
    assert result.query_reports[0].responses[0]["limit_headers"] == {
        "x-usagelimit-limit": "100",
        "x-ratelimit-limit": "30",
    }


def test_failure_after_success_retains_safe_articles_and_marks_pending_skipped():
    calls = []

    def handler(request):
        calls.append(request)
        return (
            response([article()])
            if len(calls) == 1
            else httpx.Response(429, text=TOKEN)
        )

    result = run(handler, queries=(*QUERIES, NewsQuery("third", "confirmed")))
    assert result.requests == 2 and len(result.articles) == 1
    assert result.status == "failed" and not result.checkpoint_eligible
    assert [q.status for q in result.query_reports] == ["complete", "failed", "skipped"]
    assert TOKEN not in json.dumps(metadata_report(result))


def test_same_uuid_with_different_facts_across_queries_is_partial():
    count = 0

    def handler(request):
        nonlocal count
        count += 1
        return response([article(title=f"Version {count}")])

    result = run(handler)
    assert result.status == "partial" and result.error == "article_conflict"
    assert len(result.articles) == 1


def test_case_variants_of_one_uuid_cannot_count_as_two_articles():
    identifier = "abcdef00-0000-0000-0000-000000000001"
    result = run(
        lambda request: response(
            [
                article(uuid=identifier),
                article(uuid=identifier.upper()),
            ]
        )
    )
    assert result.status == "partial" and result.error == "duplicate_page"
    assert len(result.articles) == 1


def test_metadata_report_drops_unexpected_page_fields_and_response_headers():
    result = run(lambda request: response())
    unsafe = result.query_reports[0].model_copy(
        update={
            "pages": ({"found": 0, "snippet": "Private source text"},),
            "responses": (
                {
                    "status_code": 200,
                    "body": TOKEN,
                    "limit_headers": {"x-debug": TOKEN, "x-ratelimit-limit": "30"},
                },
            ),
        }
    )
    report = metadata_report(result.model_copy(update={"query_reports": (unsafe,)}))
    assert report["query_reports"][0]["pages"] == [{"found": 0}]
    assert report["query_reports"][0]["responses"] == [
        {
            "status_code": 200,
            "limit_headers": {"x-ratelimit-limit": "30"},
        }
    ]
    assert "Private source text" not in json.dumps(report)
    assert TOKEN not in json.dumps(report)


def test_fractional_window_bounds_are_not_silently_truncated():
    start, end = START.replace(microsecond=123456), END.replace(microsecond=654321)

    def handler(request):
        assert request.url.params["published_after"].endswith("00:00:00.123456")
        assert request.url.params["published_before"].endswith("00:30:00.654321")
        return response()

    clock = Clock()
    with httpx.Client(
        transport=httpx.MockTransport(handler), follow_redirects=True
    ) as client:
        result = collect_news(
            start=start,
            end=end,
            token=TOKEN,
            queries=QUERIES,
            client=client,
            clock=clock.now,
            sleep=clock.sleep,
        )
        assert not client.is_closed
    assert result.window_start == start and result.window_end == end


def test_invalid_json_fails_without_echoing_response_text():
    result = run(lambda request: httpx.Response(200, text=f"not-json {TOKEN}"))
    assert result.error == "invalid_payload"
    assert TOKEN not in json.dumps(metadata_report(result))


@pytest.mark.parametrize(
    "updates",
    [
        {"token": None},
        {"token": "  "},
        {"start": START.replace(tzinfo=None)},
        {"start": END},
        {"start": START - timedelta(days=8)},
        {"end": datetime.now(UTC) + timedelta(days=1)},
        {"max_requests": 0},
        {"max_pages": True},
        {"queries": None},
        {"queries": ()},
        {"queries": (QUERIES[0], QUERIES[0])},
        {"queries": (NewsQuery("bad", "confirmed", domains=None),)},
    ],
)
def test_invalid_settings_are_rejected_before_a_client_request(updates):
    def forbidden(request):
        pytest.fail("invalid settings requested network")

    kwargs = {"start": START, "end": END, "token": TOKEN, **updates}
    with (
        httpx.Client(transport=httpx.MockTransport(forbidden)) as client,
        pytest.raises(NewsCollectionError),
    ):
        collect_news(**kwargs, client=client)


def test_article_frozen_extra_forbid_aware_dates_and_utc_normalization():
    raw = article()
    values = {"article_id": raw.pop("uuid"), **raw, "retrieved_at": END}
    result = NewsArticle(**values)
    with pytest.raises(ValidationError):
        result.title = "mutated"
    with pytest.raises(ValidationError):
        NewsArticle(**values, extra_field="private")
    with pytest.raises(ValidationError):
        NewsArticle(**{**values, "published_at": START.replace(tzinfo=None)})
    with pytest.raises(ValidationError):
        NewsArticle(**{**values, "url": "https://user:password@example.com/news"})
    kst = timezone(timedelta(hours=9))
    normalized = NewsArticle(**{**values, "published_at": START.astimezone(kst)})
    assert normalized.published_at == START and normalized.published_at.tzinfo == UTC
    with pytest.raises(ValidationError):
        NewsCollection(
            status="complete", window_start=END, window_end=START, collected_at=END
        )


def test_complete_label_with_query_error_cannot_advance_checkpoint():
    inconsistent = NewsCollection(
        status="complete",
        window_start=START,
        window_end=END,
        collected_at=END,
        query_reports=(
            NewsQueryReport(
                query_id="macro",
                search="confirmed",
                status="complete",
                error="page_budget",
            ),
        ),
    )
    assert inconsistent.status == "complete"
    assert not inconsistent.checkpoint_eligible
    synthetic = NewsCollection(
        status="complete", window_start=START, window_end=END, collected_at=END
    )
    assert synthetic.checkpoint_eligible


def test_info_logging_does_not_disclose_api_token(caplog):
    caplog.set_level(logging.INFO, logger="httpx")
    result = run(lambda request: response())
    assert result.status == "complete"
    assert TOKEN not in caplog.text
    assert "api_token=" not in caplog.text


@pytest.mark.parametrize("transport_failure", [False, True])
def test_sensitive_child_logs_filtered_but_normal_logs_and_logging_config_preserved(
    caplog, transport_failure
):
    token = "offline token+url/?"
    clock, stream = Clock(), StringIO()
    logger = logging.getLogger("httpcore.connection")
    caplog.set_level(logging.INFO, logger="httpx")
    caplog.set_level(logging.INFO, logger="httpcore.connection")
    own_handler = logging.StreamHandler(stream)
    logger.addHandler(own_handler)
    before = [
        (target, list(target.filters))
        for target in (
            logger,
            logging.getLogger("httpx"),
            own_handler,
            *logging.getLogger().handlers,
        )
    ]
    levels = (logger.level, logging.getLogger("httpx").level, logging.getLogger().level)

    def handler(request):
        logger.info("sensitive value: %s", token)
        logger.info("encoded value: %s", quote(token, safe=""))
        logger.info("encoded value: %s", quote_plus(token))
        logger.info("safe transport diagnostic")
        if transport_failure:
            raise httpx.ConnectError("synthetic failure", request=request)
        return response()

    try:
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            result = collect_news(
                start=START,
                end=END,
                queries=QUERIES,
                token=token,
                client=client,
                clock=clock.now,
                sleep=clock.sleep,
            )
        assert result.status == ("failed" if transport_failure else "complete")
        for output in (caplog.text, stream.getvalue()):
            assert "safe transport diagnostic" in output
            assert token not in output
            assert quote(token, safe="") not in output
            assert quote_plus(token) not in output
            assert "api_token=" not in output
        assert all(target.filters == filters for target, filters in before)
        assert levels == (
            logger.level,
            logging.getLogger("httpx").level,
            logging.getLogger().level,
        )
    finally:
        logger.removeHandler(own_handler)
