"""선정이 최신성보다 시장 중요도를 우선하며 상류 요청 한도에도 적용되는지 확인."""

import json

import httpx
import pytest
from pydantic import ValidationError

from tests.news.test_newsletter_news import NOW, integrated, link, official
from xfolio.news.collection import collect_finnhub
from xfolio.news.importance import VERSION, assess
from xfolio.news.providers.finnhub import relevance


def test_older_macro_beats_newer_routine_and_records_explanation():
    old = link(1, age=30, title="US inflation CPI accelerates")
    recent = [link(n, age=n / 10) for n in range(2, 6)]
    result = integrated(*recent, old)
    assert result.selected[0].source_id == old.source_id
    metadata = result.report()["selected"][0]
    assert metadata["importance"] == {
        "score": 90,
        "reasons": ["inflation"],
        "version": VERSION,
    }
    assert len(result.selected) == 3


def test_recency_breaks_equal_importance_and_repeat_is_excluded():
    newer, older = link(1, age=1), link(2, age=2)
    assert integrated(older, newer).selected[0].source_id == newer.source_id
    assert (
        integrated(older, newer, seen_keys=newer.keys).selected[0].source_id
        == older.source_id
    )


def test_official_evidence_and_legacy_metadata_are_preserved():
    assert "importance" not in link().metadata()
    release = official("fomc")
    result = integrated(
        release, summary=lambda x: x.model_copy(update={"summary_ko": "검증 요약"})
    )
    assert result.selected[0].importance.score == 100
    assert "official_primary_source" in result.selected[0].importance.reasons
    assert "facts" not in result.report()["selected"][0]


def test_keyword_repetition_does_not_inflate_score():
    assert assess("CPI CPI CPI inflation").score == assess("CPI").score
    assert assess("US banking crisis").score > assess("Nvidia earnings").score


def test_forged_importance_is_rejected():
    value = integrated(link()).selected[0]
    data = value.model_dump()
    data["importance"]["score"] = 100
    with pytest.raises(ValidationError, match="importance_rule_mismatch"):
        type(value).model_validate(data)


@pytest.mark.parametrize(
    "title", ["Fed cuts rates", "US GDP contracts", "U.S. banking crisis escalates"]
)
def test_explicit_us_macro_is_not_lost_before_ranking(title):
    assert (
        relevance(title, "https://www.cnbc.com/2026/11/04/us-macro.html") == "us_market"
    )


def test_link_budget_is_spent_on_high_importance_first():
    rows = [
        {
            "id": n,
            "datetime": int(NOW.timestamp()) - n * 3600,
            "headline": f"US stocks rise {n}" if n < 14 else "US inflation CPI report",
            "source": "CNBC",
            "url": f"https://news.google.com/rss/articles/item{n}",
        }
        for n in range(1, 15)
    ]
    heads = []

    def handler(request):
        if request.method == "GET":
            return httpx.Response(200, content=json.dumps(rows))
        heads.append(str(request.url))
        n = request.url.path.removeprefix("/rss/articles/item")
        return httpx.Response(
            302,
            headers={"Location": f"https://www.cnbc.com/2026/11/04/us-stocks-{n}.html"},
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = collect_finnhub(client, api_key="test", as_of=NOW, clock=lambda: NOW)
    assert heads[0].endswith("item14")
    assert len(heads) == 12
    assert any(item.source_id == "14" for item in result.items)
