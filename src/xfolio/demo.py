"""실제 시세·뉴스를 사용하지 않는, 날짜가 고정된 가상 아침 자료."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from xfolio.compose import NewsSelection, build_morning_preview
from xfolio.market import INDICES, completed_sessions
from xfolio.models import IndexClose, MarketSnapshot
from xfolio.news_models import NewsArticle, NewsCollection

DEMO_CUTOFF = datetime(2026, 10, 23, 22, 30, tzinfo=UTC)
DEMO_PREPARED = DEMO_CUTOFF + timedelta(minutes=15)
DEMO_QUOTE = (
    "Fictional US Statistics Office announced on 2026-10-23 that the "
    "2026-09 CPI rose 2.5% year-on-year."
)


def demo_inputs(scenario="news"):
    if scenario not in ("news", "zero", "partial"):
        raise ValueError("알 수 없는 가상 시나리오입니다.")
    indices = []
    for spec, previous_close, close in zip(
        INDICES,
        (Decimal(7500), Decimal(27500)),
        (Decimal("7537.50"), Decimal("27417.50")),
        strict=True,
    ):
        previous, day, close_at = completed_sessions(DEMO_CUTOFF, spec.calendar)
        indices.append(
            IndexClose(
                index_id=spec.index_id,
                symbol=spec.symbol,
                name=spec.name,
                trade_date=day,
                previous_trade_date=previous,
                close=close,
                previous_close=previous_close,
                change_pct=(close / previous_close - 1) * 100,
                source_url="https://example.com/fictional-indices",
                retrieved_at=close_at + timedelta(minutes=1),
                market_closed_at=close_at,
            )
        )
    market = MarketSnapshot(
        as_of=DEMO_CUTOFF, trade_date=date(2026, 10, 23), indices=tuple(indices)
    )
    article = NewsArticle(
        provider="synthetic",
        article_id="00000000-0000-0000-0000-000000000001",
        title="가상 통계청의 2026년9월 CPI 발표",
        description=DEMO_QUOTE,
        source="가상 미국 통계청",
        url="https://example.com/cpi",
        published_at=datetime(2026, 10, 23, 12, 30, tzinfo=UTC),
        retrieved_at=datetime(2026, 10, 23, 12, 31, tzinfo=UTC),
    )
    news = NewsCollection(
        status="partial" if scenario == "partial" else "complete",
        window_start=DEMO_CUTOFF - timedelta(days=1),
        window_end=DEMO_CUTOFF,
        collected_at=DEMO_CUTOFF,
        articles=() if scenario == "zero" else (article,),
        requests=0,
        query_reports=(),
    )
    selection = (
        None
        if scenario == "zero"
        else NewsSelection(
            article_id=article.article_id,
            evidence=DEMO_QUOTE,
            summary_ko="가상 미국 통계청은 10/23 발표에서 2026년 9월 CPI가 전년 대비 2.5% 상승했다고 밝혔다.",
        )
    )
    return market, news, selection


def demo_preview(scenario="news"):
    market, news, selection = demo_inputs(scenario)
    return build_morning_preview(
        market=market,
        news=news,
        selection=selection,
        information_cutoff=DEMO_CUTOFF,
        prepared_at=DEMO_PREPARED,
    )
