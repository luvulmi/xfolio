"""실제 API 없이 미리보기 보류·근거·길이·저장·CLI 경계를 검증한다."""

import json
from datetime import date, timedelta
from decimal import Decimal

import httpx
import pytest

from xfolio import cli
from xfolio.compose import build_morning_preview, weighted_length_estimate
from xfolio.demo import DEMO_CUTOFF, DEMO_PREPARED, demo_inputs, demo_preview
from xfolio.news_models import NewsQueryReport
from xfolio.storage import PreviewStore


@pytest.fixture(autouse=True)
def no_external_calls(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("미리보기 시험은 외부 API를 호출할 수 없습니다.")

    monkeypatch.setattr(httpx.Client, "send", forbidden)


def make_preview(market=None, news=None, selection=None):
    default_market, default_news, default_selection = demo_inputs()
    return build_morning_preview(
        market=market or default_market,
        news=news or default_news,
        selection=selection or default_selection,
        information_cutoff=DEMO_CUTOFF,
        prepared_at=DEMO_PREPARED,
    )


def test_demo_has_two_posts_preserving_values_period_source_and_evidence():
    result = demo_preview()
    assert result.status == "ready"
    assert len(result.posts) == 2
    assert all(post.weighted_length_estimate <= 280 for post in result.posts)
    assert "7,537.50 (+0.50%)" in result.posts[0].text
    assert "27,417.50 (-0.30%)" in result.posts[0].text
    assert "2026년 9월" in result.posts[1].text
    assert "전년 대비 2.5%" in result.posts[1].text
    assert "https://example.com/cpi" in result.posts[1].text
    assert result.evidence[0]["article_id"] == result.posts[1].source_ids[0]
    assert all("가상 예시" in post.text for post in result.posts)
    assert not result.can_publish


def test_complete_zero_is_one_post_but_partial_is_held_with_no_posts():
    zero, partial = demo_preview("zero"), demo_preview("partial")
    assert zero.status == "ready" and len(zero.posts) == 1
    assert "이번 수집 범위 내 선정 뉴스 없음" in zero.posts[0].text
    assert partial.status == "held" and not partial.posts
    assert not partial.evidence


def test_missing_market_is_not_replaced_by_fictional_values():
    _, news, selection = demo_inputs()
    result = build_morning_preview(
        market=None,
        news=news,
        selection=selection,
        information_cutoff=DEMO_CUTOFF,
        prepared_at=DEMO_PREPARED,
    )
    assert result.status == "held" and not result.posts


def test_inconsistent_complete_status_cannot_turn_page_failure_into_zero_news():
    market, news, _ = demo_inputs("zero")
    partial = NewsQueryReport(
        query_id="policy", search="policy", status="partial", error="page_budget"
    )
    news = news.model_copy(update={"query_reports": (partial,), "error": "page_budget"})
    result = build_morning_preview(
        market=market,
        news=news,
        selection=None,
        information_cutoff=DEMO_CUTOFF,
        prepared_at=DEMO_PREPARED,
    )
    assert result.status == "held" and not result.posts


@pytest.mark.parametrize(
    "field,value",
    [
        ("change_pct", Decimal("10.00")),
        ("trade_date", date(2026, 10, 22)),
        ("symbol", "^NDX"),
    ],
)
def test_index_mismatch_is_held(field, value):
    market, _, _ = demo_inputs()
    first = market.indices[0].model_copy(update={field: value})
    changed = market.model_copy(update={"indices": (first, market.indices[1])})
    assert make_preview(market=changed).status == "held"


def test_duplicate_index_and_future_close_are_held():
    market, _, _ = demo_inputs()
    duplicate = market.model_copy(
        update={"indices": (market.indices[0], market.indices[0])}
    )
    assert make_preview(market=duplicate).status == "held"
    future = market.indices[0].model_copy(update={"market_closed_at": DEMO_PREPARED})
    assert (
        make_preview(
            market=market.model_copy(update={"indices": (future, market.indices[1])})
        ).status
        == "held"
    )


@pytest.mark.parametrize("change", ["late", "unmatched", "real"])
def test_unverifiable_or_real_news_is_held_without_persistable_article_text(change):
    _, news, selection = demo_inputs()
    article = news.articles[0]
    if change == "late":
        article = article.model_copy(
            update={"retrieved_at": DEMO_CUTOFF + timedelta(seconds=1)}
        )
    elif change == "real":
        article = article.model_copy(update={"provider": "Marketaux"})
    else:
        selection = selection.model_copy(update={"evidence": "this quote is absent"})
    result = make_preview(
        news=news.model_copy(update={"articles": (article,)}), selection=selection
    )
    assert result.status == "held" and not result.posts and not result.evidence
    assert article.description not in result.model_dump_json()


def test_news_overflow_excludes_whole_story_instead_of_truncating_conditions():
    _, _, selection = demo_inputs()
    long_selection = selection.model_copy(update={"summary_ko": "긴 조건 " * 150})
    result = make_preview(selection=long_selection)
    assert result.status == "ready" and len(result.posts) == 1
    assert "선정 뉴스 없음" in result.posts[0].text
    assert "긴 조건" not in result.model_dump_json()
    assert result.reasons and not result.evidence


def test_length_estimate_normalizes_hangul_and_counts_urls_as_23():
    assert weighted_length_estimate("가A") == 3
    assert weighted_length_estimate("\u1100\u1161") == 2
    assert weighted_length_estimate("https://example.com/a-long-path") == 23
    assert "공식 파서" in demo_preview().length_notice


def test_sqlite_roundtrip_deduplicates_exact_version_and_preserves_old_version(
    tmp_path,
):
    store = PreviewStore(tmp_path / "drafts.sqlite3")
    original, changed = demo_preview(), demo_preview("zero")
    assert store.recent() == [] and not store.path.exists()
    assert store.save(original)
    assert not store.save(original)
    assert store.save(changed)
    assert {p.preview_id for p in store.recent()} == {
        original.preview_id,
        changed.preview_id,
    }
    assert original in store.recent()


def test_store_revalidates_dry_run_boundary_before_writing(tmp_path):
    store = PreviewStore(tmp_path / "drafts.sqlite3")
    invalid = demo_preview().model_copy(update={"can_publish": True})
    with pytest.raises(ValueError):
        store.save(invalid)
    assert not store.path.exists()


def test_cli_default_preview_uses_no_api_or_database(tmp_path, capsys):
    db = tmp_path / "no-write.sqlite3"
    cli.main(["preview", "--json", "--db", str(db)])
    result = json.loads(capsys.readouterr().out)
    assert result["synthetic"] and not result["can_publish"]
    assert len(result["posts"]) == 2 and not db.exists()


def test_cli_saves_idempotently_and_partial_has_nonzero_exit(tmp_path, capsys):
    db = tmp_path / "drafts.sqlite3"
    args = ["preview", "--save", "--db", str(db)]
    cli.main(args)
    cli.main(args)
    assert len(PreviewStore(db).recent()) == 1
    assert "이미 저장" in capsys.readouterr().out
    with pytest.raises(SystemExit) as error:
        cli.main(["preview", "--scenario", "partial", "--json"])
    assert error.value.code == 1
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "held" and result["posts"] == []
