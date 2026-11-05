"""API/DB/AI 없는 T04 합성 표본. 실제 수집/인수 근거로 사용하지 않는다."""

from datetime import date, timedelta
from decimal import Decimal

from xfolio.domestic.calendar import completed_sessions, local_calendar
from xfolio.domestic.catalogue import default_instruments
from xfolio.domestic.models import CloseQuote, Collection, DayClose
from xfolio.news.collection import Fact, NewsItem, SourceResult, integrate
from xfolio.newsletter.edition import MorningInputs, MorningSettings, at


def demo_inputs(scenario="news", *, target_date=date(2026, 11, 4)):
    cutoff = at(target_date, 7, 50)
    start = target_date - timedelta(days=14)
    opened = set(
        local_calendar().schedule(start_date=start, end_date=target_date).index.date
    )
    calendar = {
        start + timedelta(days=i): start + timedelta(days=i) in opened
        for i in range(15)
    }
    previous, latest = completed_sessions(cutoff, calendar)
    instruments = default_instruments(cutoff - timedelta(days=1))
    quotes, errors = [], {}
    for i, instrument in enumerate(instruments):
        if scenario == "failed" or scenario == "partial" and i == 1:
            errors[instrument.code] = "provider_unavailable"
            continue
        price = Decimal(25000 + i * 1000)

        def day(session, value, change=None):
            return DayClose(
                trade_date=session.trade_date,
                scheduled_close=session.scheduled_close,
                close=value,
                flng_cls_code="00",
                split_rate=0,
                modification="N",
                revaluation_reason="",
                provider_change=change,
            )

        quotes.append(
            CloseQuote(
                code=instrument.code,
                previous=day(previous, price),
                latest=day(latest, price + 100, Decimal(100)),
                retrieved_at=cutoff + timedelta(minutes=1),
                basis_verified=True,
            )
        )
    items = []
    if scenario in {"news", "partial"}:
        for i in range(2):
            items.append(
                NewsItem(
                    provider="Finnhub",
                    kind="link",
                    source_id=f"demo-{i}",
                    url=f"https://www.cnbc.com/2026/11/03/synthetic-stocks-{i}.html",
                    title=f"Synthetic US stocks earnings report {i + 1}",
                    publisher="CNBC",
                    published_at=cutoff - timedelta(hours=i + 1),
                    retrieved_at=cutoff + timedelta(minutes=1),
                    content_version=f"demo-v{i}",
                    event_key=f"synthetic-company:{i}",
                    permission_reference="finnhub_personal_use:2026-11-03",
                    synthetic=True,
                )
            )
        items.append(
            NewsItem(
                provider="BEA",
                kind="official",
                source_id="demo-gdp",
                url="https://www.bea.gov/news/2026/gdp-third-estimate-3rd-quarter-2026",
                title="Synthetic GDP release",
                publisher="BEA",
                published_at=cutoff - timedelta(hours=12),
                retrieved_at=cutoff + timedelta(minutes=1),
                content_version="demo-gdp-v1",
                event_key="synthetic-gdp",
                facts=(
                    Fact(
                        claim_id="gdp",
                        evidence_span="Synthetic GDP increased 2.5 percent.",
                        allowed_texts=(
                            "가상 표본: 2026년 3분기 실질 GDP 3차 추정치는 전기 대비 연율 2.5% 증가했다.",
                        ),
                    ),
                ),
                permission_reference="official_self_authored:2026-11-02",
                synthetic=True,
            )
        )
    failed = (
        {"Finnhub", "BLS", "BEA", "Board"}
        if scenario == "failed"
        else {"BLS"}
        if scenario == "partial"
        else set()
    )
    sources = tuple(
        SourceResult(
            provider=p,
            status="failed" if p in failed else "complete",
            requests=0,
            errors=("synthetic_failure",) if p in failed else (),
            items=tuple(i for i in items if i.provider == p),
        )
        for p in ("Finnhub", "BLS", "BEA", "Board")
    )
    news = integrate(
        sources,
        as_of=cutoff,
        finished_at=cutoff + timedelta(minutes=2),
        run_id="demo-news-" + scenario,
        summary=lambda i: i.model_copy(
            update={"summary_ko": " ".join(f.allowed_texts[0] for f in i.facts)}
        ),
    )
    return MorningInputs(
        target_date=target_date,
        recipient_scope="self",
        frozen_at=cutoff,
        settings=MorningSettings(revision=1),
        watchlist_revision=1,
        instruments=instruments,
        market_run_id="demo-market-" + scenario,
        market=Collection(
            started_at=cutoff,
            finished_at=cutoff + timedelta(minutes=2),
            requested_codes=tuple(i.code for i in instruments),
            watchlist_revision=1,
            quotes=tuple(quotes),
            errors=errors,
        ),
        calendar_opened=calendar,
        news=news,
    )
