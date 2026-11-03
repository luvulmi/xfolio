"""실제 공급자 없이 미국 관련성·중복·경유 실패의 제외 동작을 검증한다."""

import importlib.util
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

SPEC = importlib.util.spec_from_file_location(
    "finnhub_news_probe",
    Path(__file__).parents[1] / "scripts/experiments/finnhub_news_probe.py",
)
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)
canonical_url = probe.canonical_url
event_bucket = probe.event_bucket
filter_rows = probe.filter_rows
relevance = probe.relevance
resolve_link = probe.resolve_link

NOW = datetime(2026, 11, 2, 23, tzinfo=UTC)


def row(identifier=1, headline="US stock futures rise", **overrides):
    return {
        "id": identifier,
        "headline": headline,
        "source": "Reuters",
        "datetime": int(NOW.timestamp()) - 60,
        "url": f"https://www.reuters.com/markets/story-{identifier}/",
        **overrides,
    }


@pytest.mark.parametrize(
    ("headline", "expected"),
    [
        ("US stocks rise as bond yields fall", "us_market"),
        ("U.S. economy adds jobs", "us_market"),
        ("Nasdaq earnings outlook improves", "us_market"),
        ("Oracle sells stock to finance AI buildout", "us_company"),
        ("China foreign minister discusses Middle East", "no_explicit_us_relevance"),
        ("Asian crude oil imports fall", "no_explicit_us_relevance"),
        ("Apple harvest grows in UK orchards", "no_explicit_us_relevance"),
        ("Our portfolio: US stocks to buy", "excluded_opinion_or_crypto"),
        ("Bitcoin climbs alongside US stocks", "excluded_opinion_or_crypto"),
    ],
)
def test_relevance(headline, expected):
    assert relevance(headline, "https://www.reuters.com/markets/a/") == expected


def test_duplicates_tracking_and_distinct_company_event():
    rows = [
        row(),
        row(2, "US stock futures rise - Reuters"),
        row(3, "Oracle earnings beat estimates"),
        row(4, "Oracle announces dividend"),
        row(
            5,
            "US jobs report released",
            url="https://www.reuters.com/markets/jobs/?utm_source=x",
        ),
        row(6, "US jobs report update", url="https://www.reuters.com/markets/jobs/"),
    ]
    candidates, rejected = filter_rows(rows, NOW)
    assert [item["id"] for item in candidates] == [1, 3, 4, 5]
    assert rejected["duplicate_id_url_or_title"] == 2
    assert filter_rows([row()], NOW)[0]  # 조회만으로 영속 기발송 처리하지 않는다.
    assert not filter_rows([row()], NOW, seen_ids=[1])[0]
    assert not filter_rows([row()], NOW, seen_urls=[row()["url"]])[0]


def test_future_old_and_invalid_rows_do_not_enter_selection():
    candidates, rejected = filter_rows(
        [
            row(datetime=int(NOW.timestamp()) + 1),
            row(2, datetime=int(NOW.timestamp()) - 96 * 3600 - 1),
            row(3, datetime=None),
            row(4, headline=None),
            row(5, url="https://malicious.example/a"),
        ],
        NOW,
    )
    assert not candidates
    assert sum(rejected.values()) == 5


@pytest.mark.parametrize(
    "url",
    [
        "http://www.reuters.com/a",
        "https://www.reuters.com.evil.example/a",
        "https://user:secret@www.reuters.com/a",
        "https://127.0.0.1/a",
        "https://www.reuters.com:999/a",
        "https://www.reuters.com:bad/a",
    ],
)
def test_unsafe_urls(url):
    assert canonical_url(url) == ""


def test_normal_redirect_and_source_mismatch():
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.host == "news.google.com":
            return httpx.Response(
                302,
                headers={
                    "location": "https://www.reuters.com/markets/us-stocks-rise-2026-11-02/"
                },
            )
        return httpx.Response(200)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = resolve_link(
            client, "https://news.google.com/rss/articles/test", "Reuters"
        )
        assert result["status"] == "publisher_redirect_url"
        assert result["calls"] == 1
        assert result["article_availability_verified"] is False
        assert all(request.method == "HEAD" for request in requests)
        assert all("X-Finnhub-Token" not in request.headers for request in requests)
        assert resolve_link(client, "https://www.cnbc.com/a", "Reuters")["calls"] == 0


@pytest.mark.parametrize(
    ("status", "location", "expected", "calls"),
    [
        (200, None, "google_interstitial", 1),
        (403, None, "http_403", 1),
        (
            302,
            "http://169.254.169.254/latest/meta-data/",
            "unsafe_or_unknown_source",
            1,
        ),
        (302, "/rss/articles/loop", "redirect_limit", 4),
    ],
)
def test_unresolved_or_unsafe_links_are_excluded(status, location, expected, calls):
    headers = {"location": location} if location else {}
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(status, headers=headers)
        )
    ) as client:
        result = resolve_link(
            client, "https://news.google.com/rss/articles/test", "Reuters"
        )
    assert result["url"] == ""
    assert result["status"] == expected
    assert result["calls"] == calls


def test_event_cap_is_separate_from_exact_duplicate():
    titles = [
        "US voters in sour economic mood heading into midterms",
        "Sectors bracing for pivot as US midterm elections loom",
    ]
    assert event_bucket(titles[0]) == event_bucket(titles[1]) == "us_midterms"
    # 서로 다른 관점이므로 정확한 기사 중복으로 삭제하지 않고 편성 때 한 사건 1건 제한.
    assert len(filter_rows([row(1, titles[0]), row(2, titles[1])], NOW)[0]) == 2


@pytest.mark.parametrize(
    ("source", "url"),
    [
        (
            "CNBC",
            "https://www.cnbc.com/2026/11/02/oracle-finances-ai.html?utm_source=test",
        ),
        ("Reuters", "https://www.reuters.com/markets/us-stocks-rise-2026-11-02/"),
        ("Reuters", "https://www.reuters.com/article/us-markets-idUSKBN123456/"),
    ],
)
def test_provider_article_url_does_not_require_head_or_body(source, url):
    def no_request(request):
        pytest.fail("공급자 직접 기사 주소는 원문 열람/HEAD 성공을 요구하지 않는다.")

    with httpx.Client(transport=httpx.MockTransport(no_request)) as client:
        result = resolve_link(client, url, source, max_requests=0)
    assert result["status"] == "provider_direct_url"
    assert result["url"] == canonical_url(url)
    assert result["calls"] == 0
    assert not result["article_availability_verified"]


@pytest.mark.parametrize(
    ("source", "url", "expected"),
    [
        ("CNBC", "https://www.cnbc.com/", "not_article_url"),
        ("Reuters", "https://www.reuters.com/markets/", "not_article_url"),
        ("CNBC", "https://www.cnbc.com/quotes/AAPL", "not_article_url"),
        (
            "Reuters",
            "https://www.reuters.com/markets/us-stocks-2026-11-02/../",
            "not_article_url",
        ),
        ("Reuters", "https://news.google.com/", "not_google_article_url"),
        (
            "Reuters",
            "https://www.cnbc.com/2026/11/02/us-stocks.html",
            "publisher_mismatch",
        ),
    ],
)
def test_homepage_section_and_mismatched_source_are_not_article_urls(
    source, url, expected
):
    with httpx.Client(
        transport=httpx.MockTransport(lambda request: pytest.fail("unexpected request"))
    ) as client:
        result = resolve_link(client, url, source)
    assert result["status"] == expected and not result["url"]
    assert result["calls"] == 0


def cnbc_row(identifier, headline):
    return row(
        identifier,
        headline,
        source="CNBC",
        url=f"https://www.cnbc.com/2026/11/02/story-{identifier}.html",
    )


def output_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return Path("tasks/verification/assets/news_samples/test/metadata.json")


def test_run_probe_event_limit_three_and_safe_aggregate(tmp_path, monkeypatch):
    output = output_path(tmp_path, monkeypatch)
    articles = [
        cnbc_row(1, "US voters heading into midterm elections"),
        cnbc_row(2, "Sectors prepare as US midterm elections loom"),
        cnbc_row(3, "US jobs report released"),
        cnbc_row(4, "US stocks rise on earnings"),
        cnbc_row(5, "Oracle earnings beat forecasts"),
    ]
    requests = []

    def handler(request):
        requests.append(request)
        assert request.method == "GET" and request.url.host == "finnhub.io"
        assert request.headers["X-Finnhub-Token"] == "synthetic-secret"
        return httpx.Response(200, json=articles)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        report = probe.run_probe(
            output, as_of=NOW, client=client, api_key="synthetic-secret"
        )
        assert not client.is_closed
    assert report["development_selected_ids"] == [1, 3, 4]
    assert report["selection_rejections"] == {"duplicate_final_url_or_event_cap": 1}
    assert report["head_calls"] == 0 and len(requests) == 1
    assert (
        report["valid_timestamp_count"] == 5 and report["invalid_timestamp_count"] == 0
    )
    assert report["source_hosts"] == {"www.cnbc.com": 5}
    assert report["selection_as_of_utc"] == NOW.isoformat()
    assert (
        datetime.fromisoformat(report["requested_at_utc"])
        <= datetime.fromisoformat(report["observed_at_utc"])
        <= datetime.fromisoformat(report["completed_at_utc"])
    )
    assert report == json.loads(output.read_text(encoding="utf-8"))
    evidence = output.read_text(encoding="utf-8")
    assert (
        "synthetic-secret" not in evidence and "US jobs report released" not in evidence
    )
    assert "story-3.html" not in evidence
    assert not report["raw_content_saved"] and not report["telegram_sent"]
    with pytest.raises(probe.ProbeError, match="new file"):
        probe.run_probe(output, as_of=NOW, api_key="synthetic-secret")


def test_google_budget_does_not_hide_later_direct_article(tmp_path, monkeypatch):
    output = output_path(tmp_path, monkeypatch)
    articles = [
        row(
            i,
            f"US stocks move after report {i}",
            url=f"https://news.google.com/rss/articles/test-{i}",
        )
        for i in range(1, 5)
    ]
    articles.append(cnbc_row(5, "Oracle earnings grow as revenue rises"))
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.host == "finnhub.io":
            return httpx.Response(200, json=articles)
        assert request.method == "HEAD" and "X-Finnhub-Token" not in request.headers
        return httpx.Response(302, headers={"location": "/rss/articles/loop"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        report = probe.run_probe(
            output, as_of=NOW, client=client, api_key="synthetic-secret"
        )
    assert report["head_calls"] == 12 and len(requests) == 13
    assert report["development_selected_ids"] == [5]
    assert report["links"][3]["status"] == "request_budget_exhausted"
    assert report["links"][4]["status"] == "provider_direct_url"


def test_failure_does_not_echo_response_or_key(tmp_path, monkeypatch):
    output = output_path(tmp_path, monkeypatch)
    with (
        httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    403, text="synthetic-secret article body"
                )
            )
        ) as client,
        pytest.raises(probe.ProbeError) as error,
    ):
        probe.run_probe(output, client=client, api_key="synthetic-secret")
    assert "synthetic-secret" not in str(error.value) and "article body" not in str(
        error.value
    )
    assert not output.exists()


def test_response_freshness_counts_query_time_boundaries_and_future():
    published = [
        NOW - timedelta(hours=1),
        NOW - timedelta(hours=24),
        NOW - timedelta(hours=96),
        NOW - timedelta(hours=97),
        NOW + timedelta(seconds=1),
    ]
    articles = [
        row(i, datetime=int(moment.timestamp()))
        for i, moment in enumerate(published, 1)
    ]
    articles[0]["url"] = "https://www.cnbc.com/2026/11/02/story.html"
    stats = probe.response_statistics(articles, NOW)
    assert stats["valid_timestamp_count"] == 5
    assert stats["invalid_timestamp_count"] == 0
    assert stats["future_timestamp_count"] == 1
    assert stats["within_24h_of_query"] == 2
    assert stats["within_96h_of_query"] == 3
    assert stats["newest_published_at_utc"] == published[4].isoformat()
    assert stats["oldest_published_at_utc"] == published[3].isoformat()
    assert stats["source_hosts"] == {"www.cnbc.com": 1, "www.reuters.com": 4}
    assert stats["publication_age_is_provider_delay"] is False


@pytest.mark.parametrize(
    "value", [True, "1234", None, float("nan"), float("inf"), -1, 10**100]
)
def test_invalid_timestamp_types_and_ranges_are_not_coerced(value):
    stats = probe.response_statistics([row(datetime=value)], NOW)
    assert stats["valid_timestamp_count"] == 0 and stats["invalid_timestamp_count"] == 1
    assert (
        stats["future_timestamp_count"]
        == stats["within_24h_of_query"]
        == stats["within_96h_of_query"]
        == 0
    )
    assert (
        stats["newest_published_at_utc"] is None
        and stats["oldest_published_at_utc"] is None
    )


def test_missing_rows_and_unsafe_or_malformed_hosts_do_not_break_statistics():
    articles = [
        None,
        {},
        row(url=None),
        row(url="https://secret@www.reuters.com/a"),
        row(url="https://www.reuters.com:bad/a"),
        row(url="https://bad host/a"),
        row(url="//www.reuters.com/a"),
        row(url="javascript:bad"),
        row(url="https://www.reuters.com/markets/a/"),
    ]
    stats = probe.response_statistics(articles, NOW)
    assert stats["valid_timestamp_count"] == 7 and stats["invalid_timestamp_count"] == 2
    assert stats["source_hosts"] == {"www.reuters.com": 1}
