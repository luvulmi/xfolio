"""명시적 격리 DB와 합성 전제. non-synthetic 성공 시험은 실제 게시 허가가 아니다."""

import os
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from xfolio.am_edition import AMInputs, NewsDraft
from xfolio.api.store import PostgresStore
from xfolio.etf import collect_etf_closes
from xfolio.market import completed_sessions
from xfolio.news_contracts import digest
from xfolio.news_evaluation import NewsClaim, NewsFacts
from xfolio.news_input import (
    ContentEvidence,
    InputRights,
    NewsInput,
    NewsInputCollection,
    PublicationTime,
    ScopeReport,
)

KST = ZoneInfo("Asia/Seoul")
CUTOFF = datetime(2026, 10, 29, 7, 30, tzinfo=KST)
NOW = CUTOFF + timedelta(minutes=5)
CHECKS = {
    "evidence_support": True,
    "conditions_preserved": True,
    "relevance_and_novelty": True,
}


def rights(**updates):
    return InputRights.model_validate(
        {
            "collection": "permitted",
            "storage": "permitted",
            "ai_transfer": "permitted",
            "summary_publication": "permitted",
            "review_id": "unit-review",
            "reviewed_by": "unit-operator",
            "reviewed_at": CUTOFF - timedelta(days=1),
            "policy_reference": "isolated test assumption",
        }
        | updates
    )


def inputs(count=0, *, synthetic=False, **updates):
    previous, current, _ = completed_sessions(CUTOFF, "NYSE")

    def loader(*args):
        return pd.DataFrame(
            {"Close": [100, 101], "Dividends": [0, 0], "Stock Splits": [0, 0]},
            index=pd.DatetimeIndex(
                [str(previous), str(current)], tz="America/New_York"
            ),
        ), {"currency": "USD", "instrumentType": "ETF"}

    snapshot = collect_etf_closes(
        as_of=CUTOFF,
        clock=lambda: CUTOFF - timedelta(minutes=2),
        history_loader=loader,
        rights=rights(),
        synthetic=synthetic,
    )
    if not synthetic:
        snapshot = type(snapshot).model_validate(
            snapshot.model_dump() | {"data_origin": "permitted_fixture"}
        )
    news = []
    for i in range(count):
        text = f"Example{i} reports 2026-Q3 revenue {10 + i} USD."
        captured = CUTOFF - timedelta(minutes=10)
        record = NewsInput(
            input_id=f"input-{i}",
            source_id="exa",
            source_record_id=f"example-{i}",
            source_url=f"https://example.invalid/news/{i}",
            publisher="Example",
            document_type="article",
            publication=PublicationTime(
                raw=(CUTOFF - timedelta(hours=2)).astimezone(UTC).isoformat(),
                value=CUTOFF - timedelta(hours=2),
                timezone="UTC",
                precision="second",
                verified=True,
            ),
            retrieved_at=captured,
            available_at=captured,
            last_checked_at=captured,
            collection_run_id="exa-run",
            content=ContentEvidence(
                text=text,
                text_chars=len(text),
                truncation="not_detected",
                sufficiency="sufficient",
                reason="unit-test",
                assessed_by="unit-reviewer",
                assessed_at=captured,
                evidence_spans=(text,),
            ),
            content_hash=digest(text),
            source_revision=digest(text),
            revision_kind="content_hash",
            data_origin="synthetic_fixture" if synthetic else "permitted_fixture",
            synthetic=synthetic,
            rights=rights(),
        )
        claim = NewsClaim(
            claim_id=f"claim-{i}",
            subject=f"Example{i}",
            action="reported",
            metric="revenue",
            target_period="2026-Q3",
            statement_type="actual",
            accounting_basis="not_applicable",
            value=str(10 + i),
            unit="USD",
            comparison_basis="quarter_actual",
            evidence_span=text,
            evidence_locator="paragraph 1",
        )
        facts = NewsFacts(
            input_id=record.input_id,
            content_hash=record.content_hash,
            subject_id=f"Example{i}",
            event_type="business_event",
            identity="2026-Q3",
            extraction_mode="manual_review",
            claims=(claim,),
        )
        news.append(
            NewsDraft(
                record=record,
                facts=facts,
                body=f"Example{i} 2026-Q3 매출 {10 + i} USD.",
                claim_ids=(claim.claim_id,),
                generation_mode="mock" if synthetic else "live",
                related=True,
                importance="material",
                input_review_id=f"review-{i}",
                reviewed_by="fixture-operator",
                reviewed_at=CUTOFF - timedelta(minutes=5),
                review_reason="unit-test material US company event",
            )
        )
    runs = tuple(
        NewsInputCollection(
            collection_run_id=f"{provider}-run",
            source_id=provider,
            adapter_version="unit-adapter",
            query_version="unit-query",
            scope="configured_fixture_scope",
            window_start=CUTOFF - timedelta(days=1),
            window_end=CUTOFF,
            finished_at=CUTOFF,
            required_scope_ids=("required",),
            status="complete",
            records=tuple(n.record for n in news) if provider == "exa" else (),
            reports=(
                ScopeReport(
                    scope_id="required",
                    kind="search" if provider == "exa" else "release",
                    status="complete",
                    requests=1,
                    input_ids=tuple(n.record.input_id for n in news)
                    if provider == "exa"
                    else (),
                ),
            ),
        )
        for provider in ("exa", "bls")
    )
    return AMInputs.model_validate(
        {
            "target_date": CUTOFF.date(),
            "market_run_id": "etf-run",
            "snapshot": snapshot,
            "collections": runs,
            "news": tuple(news),
            "window_start": CUTOFF - timedelta(days=1),
            "frozen_at": CUTOFF,
            "max_publish_cost_krw": "100",
        }
        | updates
    )


@pytest.fixture
def am_store():
    url = os.environ.get("XFOLIO_TEST_DATABASE_URL")
    if not url:
        pytest.skip("explicit isolated PostgreSQL not configured")
    base = PostgresStore(url).engine
    schema = "xf_am_" + secrets.token_hex(8)
    with base.begin() as conn:
        conn.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    store = object.__new__(PostgresStore)
    store.engine = sa.create_engine(
        base.url, connect_args={"options": f"-csearch_path={schema}"}
    )
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option(
        "script_location", str(Path(__file__).parents[1] / "migrations")
    )
    with store.engine.begin() as conn:
        config.attributes["connection"] = conn
        command.upgrade(config, "head")
    try:
        yield store
    finally:
        store.engine.dispose()
        with base.begin() as conn:
            conn.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        base.dispose()
