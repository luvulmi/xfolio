"""뉴스 공통 근거 검사는 실제 AI/전송/사람 승인과 분리한다."""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from tests.support.paths import FIXTURES
from xfolio.news.contracts import digest
from xfolio.news.evaluation import (
    NewsClaim,
    NewsFacts,
    PriorNewsFact,
    evaluate_news_input,
)
from xfolio.news.input import ContentEvidence, InputRights, NewsInput, PublicationTime
from xfolio.news.providers.bls_input import parse_cpi_input

HTML = (FIXTURES / "bls/cpi.html").read_text(encoding="utf-8")
NOW = datetime(2026, 10, 31, tzinfo=UTC)


def rights(**updates):
    return InputRights.model_validate(
        {
            "collection": "permitted",
            "ai_transfer": "permitted",
            "summary_publication": "permitted",
            "review_id": "unit-review",
            "reviewed_by": "tester",
            "reviewed_at": NOW - timedelta(days=1),
            "policy_reference": "unit test only",
        }
        | updates
    )


def cpi(html=HTML, **updates):
    return parse_cpi_input(
        html,
        **({"retrieved_at": NOW, "run_id": "unit-cpi", "rights": rights()} | updates),
    )


def evaluate(record, facts, **updates):
    return evaluate_news_input(
        record,
        facts,
        **(
            {"now": NOW, "cutoff": NOW, "window_start": NOW - timedelta(days=30)}
            | updates
        ),
    )


def change_record(item, **updates):
    return NewsInput.model_validate(item.model_dump() | updates)


def prior(item, facts, approved=False):
    return PriorNewsFact(
        event_key=facts.event_key,
        fact_version=facts.fact_version,
        input_id=item.input_id,
        content_hash=item.content_hash,
        approved=approved,
    )


def test_supported_cpi_is_machine_candidate_and_always_requires_human_review():
    item = cpi()
    decision = evaluate(item.record, item.facts)
    assert decision.disposition == "candidate" and not decision.can_publish
    assert decision.human_review_required


@pytest.mark.parametrize(
    "updates,code",
    [
        ({"rights": InputRights()}, "RIGHTS_UNVERIFIED"),
        ({"rights": rights(expires_at=NOW)}, "RIGHTS_UNVERIFIED"),
        ({"rights": rights(ai_transfer="restricted")}, "RIGHTS_UNVERIFIED"),
        (
            {"publication": PublicationTime(raw="2026-10-14", precision="date")},
            "PUBLISHED_TIME_UNVERIFIED",
        ),
        (
            {
                "available_at": NOW + timedelta(seconds=1),
                "last_checked_at": NOW + timedelta(seconds=1),
            },
            "EVIDENCE_AFTER_CUTOFF",
        ),
        ({"last_checked_at": NOW + timedelta(seconds=1)}, "CAPTURE_IN_FUTURE"),
        ({"document_type": "unknown"}, "DOCUMENT_TYPE_REVIEW_REQUIRED"),
        ({"document_type": "live_updates"}, "DOCUMENT_TYPE_REVIEW_REQUIRED"),
        ({"data_origin": "synthetic_fixture", "synthetic": True}, "SYNTHETIC_INPUT"),
    ],
)
def test_independent_rights_time_document_and_fixture_holds(updates, code):
    original = cpi()
    decision = evaluate(change_record(original.record, **updates), original.facts)
    assert code in decision.reason_codes and not decision.can_publish


def test_publication_window_and_separate_ai_publication_permissions():
    item = cpi()
    assert evaluate(
        item.record, item.facts, window_start=NOW - timedelta(days=1)
    ).reason_codes == ("PUBLICATION_OUTSIDE_WINDOW",)
    record = change_record(
        item.record, rights=rights(summary_publication="pending_review")
    )
    assert evaluate(record, item.facts).disposition == "candidate"
    assert evaluate(record, item.facts, purpose="summary_publication").reason_codes == (
        "RIGHTS_UNVERIFIED",
    )


def test_body_insufficiency_and_missing_facts_are_not_collection_zero():
    item = cpi(HTML.replace("increased 0.6 percent", "was unchanged"))
    assert evaluate(item.record, item.facts).reason_codes == ("INSUFFICIENT_BODY",)
    item = cpi()
    assert evaluate(item.record, None).reason_codes == ("FACTS_REQUIRED",)


@pytest.mark.parametrize(
    "field,value,code",
    [
        ("input_id", "other", "FACT_SOURCE_MISMATCH"),
        ("content_hash", "0" * 64, "FACT_SOURCE_MISMATCH"),
        ("fact_version", "other", "FACT_VERSION_MISMATCH"),
    ],
)
def test_exact_source_and_fact_versions_are_required(field, value, code):
    item = cpi()
    if field == "fact_version":
        decision = evaluate(change_record(item.record, fact_version=value), item.facts)
    else:
        facts = NewsFacts.model_validate(item.facts.model_dump() | {field: value})
        decision = evaluate(item.record, facts)
    assert decision.reason_codes == (code,)


@pytest.mark.parametrize(
    "updates,code",
    [
        ({"evidence_span": "Not in actual body"}, "EVIDENCE_SPAN_MISSING"),
        ({"value": "100.6"}, "VALUE_NOT_IN_EVIDENCE"),
        ({"conditions": ("subject to approval",)}, "CONDITION_NOT_IN_EVIDENCE"),
        ({"statement_type": "analyst_estimate"}, "ANALYST_ESTIMATE_REVIEW_REQUIRED"),
    ],
)
def test_claim_values_conditions_and_estimates_are_not_promoted(updates, code):
    item = cpi()
    first = NewsClaim.model_validate(item.facts.claims[0].model_dump() | updates)
    facts = NewsFacts.model_validate(item.facts.model_dump() | {"claims": (first,)})
    record = change_record(item.record, event_key=None, fact_version=None)
    assert evaluate(record, facts).reason_codes == (code,)


def test_source_independent_fact_version_and_same_event_deduplication():
    item = cpi()
    other = NewsClaim.model_validate(
        item.facts.claims[0].model_dump()
        | {
            "claim_id": "different",
            "evidence_locator": "other paragraph",
            "value": "0.60",
        }
    )
    facts = NewsFacts.model_validate(
        item.facts.model_dump()
        | {
            "claims": (other, item.facts.claims[1]),
            "input_id": "other-media",
            "content_hash": "f" * 64,
        }
    )
    assert facts.fact_version == item.facts.fact_version
    decision = evaluate(
        item.record, item.facts, prior=(prior(item.record, item.facts),)
    )
    assert decision.disposition == "duplicate"


@pytest.mark.parametrize("change", ["0.6 percent", "9.1 percent"])
def test_approved_source_or_fact_corrections_hold_before_other_exclusions(change):
    item = cpi()
    changed = cpi(HTML.replace(change, "0.7 percent"), previous=item.record)
    denied = change_record(changed.record, rights=InputRights())
    decision = evaluate(
        denied, changed.facts, prior=(prior(item.record, item.facts, True),)
    )
    assert decision.disposition == "hold" and not decision.can_publish


def test_unapproved_source_only_change_still_requires_review():
    item = cpi()
    changed = cpi(HTML.replace("9.1 percent", "9.2 percent"), previous=item.record)
    result = evaluate(
        changed.record, changed.facts, prior=(prior(item.record, item.facts),)
    )
    assert result.disposition == "review_required"


def earnings():
    item = cpi()
    text = "Example 2026 Q3 non-GAAP EPS 0.52 USD; Q4 outlook 15 to 16 USD, subject to approval."
    content = ContentEvidence(
        text=text,
        text_chars=len(text),
        truncation="not_detected",
        sufficiency="sufficient",
        reason="unit fixture",
        assessed_by="tester",
        assessed_at=NOW,
        evidence_spans=(text,),
    )
    record = change_record(
        item.record,
        content=content,
        content_hash=digest(text),
        source_revision=digest(text),
        event_key=None,
        fact_version=None,
        source_id="exa",
        source_record_id="example",
        document_type="article",
    )
    claim = NewsClaim(
        claim_id="earnings",
        subject="Example",
        action="reported",
        metric="EPS",
        target_period="2026-Q3",
        statement_type="actual",
        accounting_basis="non-GAAP",
        value="0.52",
        unit="USD",
        comparison_basis="quarter_actual",
        evidence_span=text,
        evidence_locator="paragraph 1",
    )
    facts = NewsFacts(
        input_id=record.input_id,
        content_hash=record.content_hash,
        subject_id="Example",
        event_type="earnings",
        identity="2026-Q3",
        extraction_mode="manual_review",
        claims=(claim,),
    )
    return record, facts


def test_gaap_and_non_gaap_are_distinct_and_not_substring_matches():
    record, facts = earnings()
    assert evaluate(record, facts).disposition == "candidate"
    wrong = NewsClaim.model_validate(
        facts.claims[0].model_dump() | {"accounting_basis": "GAAP"}
    )
    wrong_facts = NewsFacts.model_validate(facts.model_dump() | {"claims": (wrong,)})
    assert wrong_facts.fact_version != facts.fact_version
    assert evaluate(record, wrong_facts).reason_codes == (
        "ACCOUNTING_BASIS_NOT_IN_EVIDENCE",
    )


def test_company_outlook_range_is_not_actual_and_requires_both_bounds_and_condition():
    record, facts = earnings()
    claim = NewsClaim.model_validate(
        facts.claims[0].model_dump()
        | {
            "value": None,
            "value_range": {"lower": "15", "upper": "16"},
            "target_period": "2026-Q4",
            "statement_type": "company_outlook",
            "conditions": ("subject to approval",),
        }
    )
    forecast = NewsFacts.model_validate(facts.model_dump() | {"claims": (claim,)})
    assert forecast.fact_version != facts.fact_version
    assert evaluate(record, forecast).disposition == "candidate"
    wrong = NewsClaim.model_validate(
        claim.model_dump() | {"value_range": {"lower": "15", "upper": "17"}}
    )
    assert evaluate(
        record, NewsFacts.model_validate(forecast.model_dump() | {"claims": (wrong,)})
    ).reason_codes == ("VALUE_NOT_IN_EVIDENCE",)


@pytest.mark.parametrize(
    "updates,code",
    [
        ({"unit": None}, "numeric_context_required"),
        ({"target_period": None}, "claim_time_context_required"),
        ({"value_range": {"lower": "15", "upper": "16"}}, "scalar_range_conflict"),
        ({"value_range": {"lower": "17", "upper": "16"}}, "invalid_value_range"),
    ],
)
def test_incomplete_numeric_claim_is_invalid(updates, code):
    _, facts = earnings()
    with pytest.raises(ValidationError, match=code):
        NewsClaim.model_validate(facts.claims[0].model_dump() | updates)
