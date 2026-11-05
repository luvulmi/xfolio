from datetime import timedelta

import pytest
import sqlalchemy as sa

from tests.legacy.test_am_edition import approve
from tests.support.am_fixtures import CHECKS, NOW, inputs
from tests.support.am_fixtures import (
    am_store as am_store,  # noqa: PLC0414 - 격리 fixture
)
from tests.support.paths import FIXTURES
from xfolio.api.store import ApiError
from xfolio.db.schema import (
    content_drafts,
    operations_events,
    publication_jobs,
    publication_posts,
    usage_ledger,
)
from xfolio.legacy.am_edition import (
    AMInputs,
    payload_hash,
    record_common_collection,
    save_am_edition,
    validate_am,
)
from xfolio.news.contracts import digest
from xfolio.news.input import NewsInputCollection, ScopeReport


def test_fixture_live_transport_and_changed_numeric_substring_are_blocked():
    data = inputs(1, transport_mode="live")
    assert "FIXTURE_LIVE_BLOCKED" in validate_am(data, now=NOW)[0]
    raw = data.model_dump()
    raw["news"][0]["body"] = "Example0 2026-Q3 매출 110 USD."
    assert (
        "DRAFT_CLAIM_CONTEXT_MISSING"
        in validate_am(AMInputs.model_validate(raw), now=NOW)[0]
    )


@pytest.mark.parametrize("started", [False, True])
def test_later_collection_correction_holds_approved_version_and_preserves_unknown_claim(
    am_store, started
):
    data = inputs(1)
    job = save_am_edition(am_store.engine, data, account_id="unit-account", now=NOW)
    approve(am_store, job)
    if started:
        with am_store.engine.begin() as conn:
            conn.execute(
                publication_jobs.update()
                .where(publication_jobs.c.id == job)
                .values(status="sending", first_attempt_at=NOW)
            )
            conn.execute(
                publication_posts.update()
                .where(publication_posts.c.job_id == job)
                .values(state="unknown")
            )
    raw = data.collections[0].model_dump()
    record = raw["records"][0]
    text = record["content"]["text"] + " Corrected source paragraph."
    record.update(
        input_id="corrected-input",
        collection_run_id="correction-run",
        supersedes="input-0",
        change_reason="source corrected",
        retrieved_at=NOW,
        available_at=NOW,
        last_checked_at=NOW,
        content_hash=digest(text),
        source_revision=digest(text),
    )
    record["content"].update(text=text, text_chars=len(text), assessed_at=NOW)
    run = NewsInputCollection.model_validate(
        raw
        | {
            "collection_run_id": "correction-run",
            "window_end": NOW,
            "finished_at": NOW,
            "reports": (
                ScopeReport(
                    scope_id="required",
                    kind="search",
                    status="complete",
                    requests=1,
                    input_ids=("corrected-input",),
                ),
            ),
        }
    )
    record_common_collection(am_store.engine, run, now=NOW)
    record_common_collection(am_store.engine, run, now=NOW + timedelta(seconds=1))
    detail = am_store.detail(job, "reviewed")
    assert detail["status"] == ("sending" if started else "held")
    assert (
        detail["decision_revision"] == 2
        and detail["hold_reason"] == "APPROVED_SOURCE_CHANGED"
    )
    with am_store.engine.connect() as conn:
        assert (
            conn.scalar(
                sa.select(sa.func.count())
                .select_from(operations_events)
                .where(operations_events.c.kind == "input_invalidated")
            )
            == 1
        )
        assert conn.scalar(sa.select(usage_ledger.c.state)) == (
            "reserved" if started else "released"
        )
        active_news = conn.scalar(
            sa.select(publication_posts.c.active_claim).where(
                publication_posts.c.event_key.is_not(None)
            )
        )
        assert active_news is started


def test_budget_and_unregistered_profile_cannot_reserve(am_store):
    job = save_am_edition(
        am_store.engine,
        inputs(1, max_publish_cost_krw="50001"),
        account_id="unit-account",
        now=NOW,
    )
    with pytest.raises(ApiError) as error:
        approve(am_store, job)
    assert error.value.code == "BUDGET_BLOCKED"
    with am_store.engine.begin() as conn:
        row = conn.execute(sa.select(content_drafts)).mappings().one()
        payload = row["payload"] | {"assembly_profile": "unregistered"}
        conn.execute(
            content_drafts.insert().values(
                id="unknown-profile",
                edition_id=job,
                version=2,
                content_hash=payload_hash(payload),
                synthetic=False,
                validation_passed=True,
                payload=payload,
            )
        )
        conn.execute(
            publication_jobs.update()
            .where(publication_jobs.c.id == job)
            .values(draft_id="unknown-profile")
        )
    with pytest.raises(ApiError) as error:
        approve(am_store, job, key="unknown", expected_version=2)
    assert error.value.code == "VALIDATION_BLOCKED"


def test_authenticated_api_requires_explicit_three_checks_and_returns_etf_contract(
    am_store,
):
    from tests.legacy.test_news_edition import api_client

    job = save_am_edition(
        am_store.engine, inputs(3), account_id="unit-account", now=NOW
    )
    with api_client(am_store.engine, now=NOW) as client:
        detail = client.get(f"/api/drafts/{job}").json()
        assert (
            detail["posts"][0]["kind"] == "etf" and detail["transport_mode"] == "mock"
        )
        assert detail["validation"]["profile"] == "etf_news_review_v1"
        body = {
            "action": "approve",
            "expected_version": 1,
            "expected_decision_revision": 0,
        }
        headers = {
            "Origin": "https://testserver",
            "X-CSRF-Token": "fixture-csrf",
            "Idempotency-Key": "api-approve",
        }
        assert (
            client.post(
                f"/api/drafts/{job}/decision", json=body, headers=headers
            ).json()["error"]["code"]
            == "REVIEW_REQUIRED"
        )
        for bad in (False, 1, "true"):
            response = client.post(
                f"/api/drafts/{job}/decision",
                json=body | {"review_checks": CHECKS | {"evidence_support": bad}},
                headers=headers,
            )
            assert response.status_code == 422
        response = client.post(
            f"/api/drafts/{job}/decision",
            json=body | {"review_checks": CHECKS},
            headers=headers,
        )
        assert response.status_code == 200 and response.json()["status"] == "scheduled"


def test_existing_bls_parser_reaches_common_am_approval_without_losing_comparison_basis(
    am_store, monkeypatch
):

    from tests.support import am_fixtures
    from xfolio.legacy.am_edition import NewsDraft
    from xfolio.news.providers.bls_input import parse_cpi_input

    monkeypatch.setattr(am_fixtures, "CUTOFF", am_fixtures.CUTOFF - timedelta(days=14))
    data = inputs()
    now = data.cutoff + timedelta(minutes=5)
    parsed = parse_cpi_input(
        (FIXTURES / "bls/cpi.html").read_text(encoding="utf-8"),
        retrieved_at=data.cutoff - timedelta(minutes=10),
        run_id="bls-run",
        rights=am_fixtures.rights(),
    )
    news = NewsDraft(
        record=parsed.record,
        facts=parsed.facts,
        body="미국 CPI-U 2026-09 전월 대비(계절조정) 0.6 percent 상승, 전년 동월 대비(비계절조정) 3.7 percent 상승.",
        claim_ids=tuple(c.claim_id for c in parsed.facts.claims),
        generation_mode="live",
        related=True,
        importance="material",
        input_review_id="cpi-input-review",
        reviewed_by="fixture-operator",
        reviewed_at=data.cutoff - timedelta(minutes=5),
        review_reason="CPI unit/basis fixture check",
    )
    bls = NewsInputCollection.model_validate(
        data.collections[1].model_dump()
        | {
            "records": (parsed.record,),
            "reports": (
                ScopeReport(
                    scope_id="required",
                    kind="release",
                    status="complete",
                    requests=1,
                    input_ids=(parsed.record.input_id,),
                ),
            ),
        }
    )
    data = AMInputs.model_validate(
        data.model_dump() | {"collections": (data.collections[0], bls), "news": (news,)}
    )
    assert validate_am(data, now=now)[0] == []
    job = save_am_edition(am_store.engine, data, account_id="cpi-unit", now=now)
    from xfolio.api.models import DecisionRequest

    request = DecisionRequest(
        action="approve",
        expected_version=1,
        expected_decision_revision=0,
        review_checks=CHECKS,
    )
    assert (
        am_store.decide(
            job, "operator@example.invalid", "cpi-approve", request, "reviewed", now
        )["status"]
        == "scheduled"
    )
