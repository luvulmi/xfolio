"""T03: 네트워크/유료 모델 없이 제공처·근거·시각·중복·장애 경계를 검증."""

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
from pydantic import ValidationError

from tests.support.paths import FIXTURES
from xfolio.ai.workflow import GenerationLimits
from xfolio.cli import main
from xfolio.news.collection import (
    NewsError,
    NewsItem,
    SourceResult,
    collect,
    collect_finnhub,
    integrate,
    summarize,
)
from xfolio.news.providers.official import (
    FEEDS,
    collect_official,
    feed_entries,
    fetch,
    official_url,
    parse_official,
)

NOW = datetime(2026, 11, 4, 7, tzinfo=UTC)
PUBLISHED = datetime(2026, 11, 3, 13, 30, tzinfo=UTC)
GDP_URL = "https://www.bea.gov/news/2026/gdp-third-estimate-3rd-quarter-2026"
PCE_URL = "https://www.bea.gov/news/2026/personal-income-and-outlays-september-2026"
FOMC_URL = (
    "https://www.federalreserve.gov/newsevents/pressreleases/monetary20261103a.htm"
)


def bea_html(kind="gdp"):
    title = (
        "Gross Domestic Product, 3rd Quarter 2026 (Third Estimate)"
        if kind == "gdp"
        else "Personal Income and Outlays, September 2026"
    )
    body = (
        "Real gross domestic product (GDP) increased at an annual rate of 2.5 percent in the third quarter of 2026, according to the third estimate released today by the U.S. Bureau of Economic Analysis (BEA)."
        if kind == "gdp"
        else "From the preceding month, the PCE price index for September increased 0.2 percent.</p><p>From the same month one year ago, the PCE price index for September increased 2.8 percent."
    )
    return f'<html><h1>{title}</h1><div class="field--name-field-release-date">EMBARGOED UNTIL RELEASE AT 8:30 a.m. EST, Tuesday, November 3, 2026</div><div class="field--name-body"><p>{body}</p></div></html>'


def fomc_html():
    return '<html><p class="article__time">November 3, 2026</p><h3 class="title">Federal Reserve issues FOMC statement</h3><p class="releaseTime">For release at 2:00 p.m. EST</p><div class="col-xs-12 col-sm-8 col-md-8"><p>The Committee decided to maintain the target range for the federal funds rate at 3-3/4 to 4 percent, in support of its goals.</p></div></html>'


def official(kind="gdp"):
    provider = "Board" if kind == "fomc" else "BEA"
    return parse_official(
        fomc_html() if kind == "fomc" else bea_html(kind),
        provider=provider,
        url=FOMC_URL if kind == "fomc" else PCE_URL if kind == "pce" else GDP_URL,
        title="Federal Reserve issues FOMC statement"
        if kind == "fomc"
        else "GDP (Third Estimate), 3rd Quarter 2026"
        if kind == "gdp"
        else "Personal Income and Outlays, September 2026",
        published_at=PUBLISHED + timedelta(hours=5, minutes=30)
        if kind == "fomc"
        else PUBLISHED,
        retrieved_at=NOW,
    )


def link(n=1, age=1, title=None):
    return NewsItem(
        provider="Finnhub",
        kind="link",
        source_id=str(n),
        url=f"https://www.cnbc.com/2026/11/04/us-stocks-{n}.html",
        title=title or f"US stocks rise on earnings report {n}",
        publisher="CNBC",
        published_at=NOW - timedelta(hours=age),
        retrieved_at=NOW,
        content_version=f"v{n}",
        event_key=f"company:{n}",
        permission_reference="synthetic-test",
        synthetic=True,
    )


def sources(*items, failed=()):
    return [
        SourceResult(
            provider=p,
            status="failed" if p in failed else "complete",
            requests=1,
            errors=("http_503",) if p in failed else (),
            items=tuple(i for i in items if i.provider == p),
        )
        for p in ("Finnhub", "BLS", "BEA", "Board")
    ]


def integrated(*items, **kw):
    return integrate(
        sources(*items), as_of=NOW, finished_at=NOW, run_id="fixture-run", **kw
    )


class FakeAI:
    def __init__(self, mutate=None):
        self.calls = []
        self.mutate = mutate

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        request = json.loads(kwargs["input_json"])
        output = {k: request[k] for k in ("source_id", "content_version")}
        output["claims"] = [
            {
                "claim_id": f["claim_id"],
                "evidence_span": f["evidence_span"],
                "text_ko": f["allowed_texts"][0],
            }
            for f in request["claims"]
        ]
        response = {
            "model": "gpt-6-luna",
            "status": "completed",
            "output": output,
            "input_tokens": 100,
            "output_tokens": 50,
        }
        if self.mutate:
            self.mutate(response)
        return response


class Budget:
    def __init__(self, fail=False):
        self.reserved = self.confirmed = self.failed = 0
        self.fail_budget = fail

    def reserve(self, *args):
        if self.fail_budget:
            raise NewsError("monthly_budget_exceeded")
        self.reserved += 1

    def finish(self, *args):
        self.confirmed += 1

    def fail(self, *args):
        self.failed += 1


def limits(**changes):
    return GenerationLimits(
        **(
            {
                "max_input_tokens": 16000,
                "input_krw_per_million": Decimal(200),
                "output_krw_per_million": Decimal(1000),
                "price_basis": "synthetic_not_current_price",
                "prices_valid_until": NOW + timedelta(days=1),
            }
            | changes
        )
    )


def summarized(item):
    return summarize(item, client=FakeAI(), store=Budget(), limits=limits(), now=NOW)


@pytest.mark.parametrize(
    "kind,count,terms",
    [
        ("gdp", 1, ("2026년 3분기", "3차 추정", "연율 2.5%")),
        ("pce", 2, ("2026년 9월", "전월 대비 0.2%", "전년 동월 대비 2.8%")),
        ("fomc", 1, ("3.75~4%", "유지", "2026-11-03")),
    ],
)
def test_official_facts_and_summary(kind, count, terms):
    item = official(kind)
    assert len(item.facts) == count
    result = summarized(item)
    assert all(term in result.summary_ko for term in terms)
    assert "facts" not in result.metadata()


@pytest.mark.parametrize(
    "before,after,code",
    [
        ("November 3, 2026", "November 2, 2026", "date_mismatch"),
        ("8:30 a.m. EST", "9:30 a.m. EST", "time_mismatch"),
        ("EST, Tuesday", "EDT, Tuesday", "time_mismatch"),
        ("third estimate", "updated estimate", "gdp_period_or_estimate"),
        ("<p>Real", "<p>Copyright Example. Real", "rights"),
        ("</div></html>", "", "truncated_body"),
        ('class="field--name-body"', 'class="not-release"', "body_or_rights"),
    ],
)
def test_official_uncertain_page_excluded(before, after, code):
    with pytest.raises(NewsError, match=code):
        parse_official(
            bea_html().replace(before, after),
            provider="BEA",
            url=GDP_URL,
            title="GDP",
            published_at=PUBLISHED,
            retrieved_at=NOW,
        )


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.test/news/2026/gdp-x",
        "https://www.bea.gov@evil.test/news/2026/gdp-x",
        "https://www.bea.gov/news/2026/../gdp-x",
        "https://www.bea.gov/news/2026/gdp-x?token=abc",
        "https://www.bea.gov/news/2026/gdp-x#x",
        "http://www.bea.gov/news/2026/gdp-x",
    ],
)
def test_official_url_allowlist(url):
    assert not official_url("BEA", url)


def rss(
    title="GDP (Third Estimate), 3rd Quarter 2026",
    url=GDP_URL,
    stamp="Tue, 03 Nov 2026 08:30:00 EST",
):
    return f'<rss version="2.0"><channel><item><title>{title}</title><link>{url}</link><pubDate>{stamp}</pubDate></item></channel></rss>'


@pytest.mark.parametrize(
    "xml",
    [
        "<html>broken",
        "<rss/>",
        "<!DOCTYPE rss><rss/>",
        rss(stamp="2026-11-03"),
        rss(stamp="Tue, 03 Nov 2026 08:30:00"),
    ],
)
def test_feed_invalid_time_or_schema(xml):
    with pytest.raises(NewsError):
        feed_entries(xml, "BEA")


def test_feed_explicit_offset_and_scope():
    assert feed_entries(rss(), "BEA")[0][2] == PUBLISHED
    assert feed_entries(rss(title="Local Area GDP, 2026"), "BEA") == []


@pytest.mark.parametrize(
    "mutate",
    [
        lambda r: r["output"].__setitem__("source_id", "other"),
        lambda r: r["output"].__setitem__("content_version", "other"),
        lambda r: r["output"]["claims"][0].__setitem__(
            "text_ko", "수치는 99%이며 투자하세요."
        ),
        lambda r: r["output"]["claims"][0].__setitem__("evidence_span", "fabricated"),
        lambda r: r["output"]["claims"].clear(),
    ],
)
def test_summary_rejects_source_numbers_period_basis_or_evidence(mutate):
    ai, budget = FakeAI(mutate), Budget()
    with pytest.raises(NewsError, match="summary_"):
        summarize(official(), client=ai, store=budget, limits=limits(), now=NOW)
    assert budget.reserved == budget.confirmed == 1


def test_general_news_never_enters_ai():
    ai, budget = FakeAI(), Budget()
    with pytest.raises(NewsError, match="general_news_ai_forbidden"):
        summarize(link(), client=ai, store=budget, limits=limits(), now=NOW)
    assert ai.calls == [] and budget.reserved == 0
    with pytest.raises(ValidationError):
        NewsItem.model_validate(link().model_dump() | {"summary_ko": "forbidden"})


def test_budget_blocks_before_ai_and_unknown_keeps_reservation():
    ai = FakeAI()
    with pytest.raises(NewsError, match="monthly_budget"):
        summarize(
            official(), client=ai, store=Budget(fail=True), limits=limits(), now=NOW
        )
    assert not ai.calls

    def unknown(_):
        raise RuntimeError("SECRET_UPSTREAM_RESPONSE")

    budget = Budget()
    with pytest.raises(NewsError, match="generation_result_unknown") as exc:
        summarize(
            official(), client=FakeAI(unknown), store=budget, limits=limits(), now=NOW
        )
    assert (
        "SECRET" not in str(exc.value) and budget.failed == 1 and budget.confirmed == 0
    )


def test_prices_and_input_caps_block_before_ai():
    for caps in [limits(prices_valid_until=NOW), limits(max_input_tokens=256)]:
        ai, budget = FakeAI(), Budget()
        with pytest.raises(NewsError):
            summarize(official(), client=ai, store=budget, limits=caps, now=NOW)
        assert not ai.calls and not budget.reserved


def test_zero_partial_failure_are_distinct():
    assert integrated().normal_zero
    result = integrate(
        sources(failed=("BLS",)), as_of=NOW, finished_at=NOW, run_id="partial"
    )
    assert result.status == "partial" and not result.normal_zero
    result = integrate(
        sources(failed=("Finnhub", "BLS", "BEA", "Board")),
        as_of=NOW,
        finished_at=NOW,
        run_id="failed",
    )
    assert result.status == "failed" and not result.normal_zero


def test_integrated_cap_recent_first_and_missing_96h():
    items = [
        link(1, age=25),
        link(2, age=95),
        link(3, age=2),
        link(4, age=1),
        link(5, age=97),
    ]
    result = integrated(*items)
    assert [x.source_id for x in result.selected] == ["4", "3", "1"]
    assert result.excluded["outside_window_or_source_time"] == 1
    assert integrated(link(1, age=96)).selected
    assert not integrated(link(1, age=96.001)).selected


@pytest.mark.parametrize("age", [97])
def test_outside_window(age):
    candidate = (
        link(1, age=age)
        if age >= 0
        else link(1).model_copy(update={"published_at": NOW + timedelta(seconds=1)})
    )
    assert not integrated(candidate).selected


def test_all_identity_keys_exclude_sent_and_unsent_preview_does_not():
    item = link()
    for key in item.keys:
        assert integrated(item, seen_keys=(key,)).normal_zero
    assert integrated(item).selected and integrated(item).selected
    assert integrated(item, last_success=NOW).selected
    assert not integrated(
        link(2, age=48), last_success=NOW - timedelta(hours=24)
    ).selected


def test_official_preferred_for_same_macro_event():
    item = official()
    general = link().model_copy(update={"event_key": item.event_key})
    result = integrated(general, item, summary=summarized)
    assert len(result.selected) == 1 and result.selected[0].provider == "BEA"
    assert result.excluded["already_sent_or_duplicate"] == 1


def test_missing_or_failed_summary_is_partial_and_general_survives():
    result = integrated(official(), link())
    assert result.status == "partial" and [x.provider for x in result.selected] == [
        "Finnhub"
    ]
    assert result.excluded["summary_not_configured"] == 1


def finnhub_row(n=1, **changes):
    return {
        "id": n,
        "datetime": int((NOW - timedelta(hours=1)).timestamp()),
        "headline": "US stocks rally on earnings",
        "source": "CNBC",
        "url": f"https://www.cnbc.com/2026/11/04/stock-{n}.html",
        "summary": "DO_NOT_SEND_TO_AI",
        "image": "DO_NOT_STORE",
    } | changes


def test_finnhub_header_no_general_body_request_or_fields():
    calls = []

    def handle(request):
        calls.append(request)
        assert request.headers["X-Finnhub-Token"] == "SECRET_KEY"
        assert "SECRET_KEY" not in str(request.url)
        return httpx.Response(200, json=[finnhub_row()])

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        result = collect_finnhub(
            client, api_key="SECRET_KEY", as_of=NOW, clock=lambda: NOW
        )
    assert result.status == "complete" and len(calls) == 1
    assert len(result.items) == 1 and result.items[0].facts == ()
    assert "DO_NOT_" not in result.model_dump_json()


@pytest.mark.parametrize(
    "payload",
    [{}, [None], [finnhub_row(datetime=True)], [finnhub_row(datetime="invalid")]],
)
def test_finnhub_bad_rows_are_not_normal_zero(payload):
    with httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload))
    ) as client:
        result = collect_finnhub(client, api_key="key", as_of=NOW, clock=lambda: NOW)
    assert result.status in ("partial", "failed")


@pytest.mark.parametrize("code", [301, 401, 403, 429, 500])
def test_finnhub_http_errors_sanitized(code):
    with httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(code, text="SECRET"))
    ) as client:
        result = collect_finnhub(client, api_key="key", as_of=NOW, clock=lambda: NOW)
    assert result.status == "failed" and "SECRET" not in result.model_dump_json()


def test_official_link_unsafe_does_not_make_external_request():
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(
            200,
            headers={"content-type": "text/xml"},
            text=rss(url="https://evil.test/news"),
        )

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        result = collect_official(client, provider="BEA", as_of=NOW, clock=lambda: NOW)
    assert len(calls) == 1 and result.status == "partial"


def test_whole_pipeline_mock_and_no_general_ai():
    calls = []

    def handle(request):
        calls.append(str(request.url))
        url = str(request.url)
        if "finnhub" in url:
            return httpx.Response(200, json=[finnhub_row()])
        if url == FEEDS["BEA"]:
            return httpx.Response(200, text=rss(), headers={"content-type": "text/xml"})
        if url == FEEDS["Board"]:
            return httpx.Response(
                200,
                text=rss(
                    title="Federal Reserve issues FOMC statement",
                    url=FOMC_URL,
                    stamp="Tue, 03 Nov 2026 19:00:00 GMT",
                ),
                headers={"content-type": "text/xml"},
            )
        if url == GDP_URL:
            html = bea_html()
        elif url == FOMC_URL:
            html = fomc_html()
        else:
            html = (FIXTURES / "bls/cpi.html").read_text(encoding="utf-8")
        return httpx.Response(200, text=html, headers={"content-type": "text/html"})

    ai = []

    def summary(item):
        ai.append(item.provider)
        return summarized(item)

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        result = collect(
            client, api_key="key", as_of=NOW, clock=lambda: NOW, summary=summary
        )
    assert result.status == "complete" and len(result.selected) == 3
    assert set(ai) == {"BEA", "Board"} and len(calls) == 6
    assert (
        "facts" not in json.dumps(result.report())
        and result.report()["can_send"] is False
    )


def test_cli_dry_run(capsys):
    main(["newsletter-news"])
    report = json.loads(capsys.readouterr().out)
    assert report["network_requests"] == report["database_writes"] == 0
    assert report["maximum_selected"] == 3 and not report["can_send"]


def test_bls_expanded_html_limit_and_feed_limit():
    html = (
        (FIXTURES / "bls/cpi.html").read_text(encoding="utf-8")
        + "<!--"
        + "x" * 1_300_000
        + "-->"
    )
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(
                200, text=html, headers={"content-type": "text/html"}
            )
        )
    ) as client:
        assert (
            len(fetch(client, "https://www.bls.gov/news.release/cpi.htm")) > 1_000_000
        )
        result = collect_official(client, provider="BLS", as_of=NOW, clock=lambda: NOW)
        assert result.status == "complete"
    with (
        httpx.Client(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(
                    200, content=b"x" * 2_000_001, headers={"content-type": "text/html"}
                )
            )
        ) as client,
        pytest.raises(NewsError, match="response_limit"),
    ):
        fetch(client, "https://www.bls.gov/news.release/cpi.htm")


def test_official_plain_rights_notice_and_title_period_conflict():
    for html in [
        bea_html().replace("<p>Real", "<aside>Copyright third party</aside><p>Real")
    ]:
        with pytest.raises(NewsError, match="rights"):
            parse_official(
                html,
                provider="BEA",
                url=GDP_URL,
                title="GDP (Third Estimate), 3rd Quarter 2026",
                published_at=PUBLISHED,
                retrieved_at=NOW,
            )
    with pytest.raises(NewsError, match="title_body_mismatch"):
        parse_official(
            bea_html(),
            provider="BEA",
            url=GDP_URL,
            title="GDP (Third Estimate), 4th Quarter 2026",
            published_at=PUBLISHED,
            retrieved_at=NOW,
        )


def test_source_status_cannot_hide_failure():
    with pytest.raises(ValidationError, match="status_error"):
        SourceResult(
            provider="BLS", status="complete", requests=1, errors=("http_403",)
        )


@pytest.mark.parametrize(
    "action,by,label",
    [
        ("lower", "by 1/4 percentage point ", "인하"),
        ("raise", "by 1/2 percentage point ", "인상"),
    ],
)
def test_fomc_rate_change_and_condition_preserved(action, by, label):
    html = (
        fomc_html()
        .replace("maintain the target", "" + action + " the target")
        .replace("rate at", "rate " + by + "to")
    )
    item = parse_official(
        html,
        provider="Board",
        url=FOMC_URL,
        title="Federal Reserve issues FOMC statement",
        published_at=PUBLISHED + timedelta(hours=5, minutes=30),
        retrieved_at=NOW,
    )
    assert label in summarized(item).summary_ko


def test_official_permission_not_silently_promoted():
    with pytest.raises(ValidationError, match="official_permission_unverified"):
        NewsItem.model_validate(
            official().model_dump() | {"permission_reference": "unverified"}
        )


def test_pce_feed_and_page_period_must_match():
    with pytest.raises(NewsError, match="pce_title_body_mismatch"):
        parse_official(
            bea_html("pce"),
            provider="BEA",
            url=PCE_URL,
            title="Personal Income and Outlays, October 2026",
            published_at=PUBLISHED,
            retrieved_at=NOW,
        )
