import json
from copy import deepcopy
from datetime import timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from xfolio.news_contracts import digest
from xfolio.news_selection import (
    SelectionCandidate,
    SelectionContext,
    evaluate_candidate,
    select_edition,
)

FIXTURE = Path(__file__).parent / "fixtures/news_selection/cases.json"
CASES = json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]
BY_ID = {case["candidate"]["article_id"]: case for case in CASES}


def candidate(case_id, **updates):
    raw = deepcopy(BY_ID[case_id]["candidate"])
    raw.update(updates)
    return SelectionCandidate.model_validate(raw)


def context(edition, **updates):
    raw = deepcopy(BY_ID["N01" if edition == "AM" else "N06"]["context"])
    raw.update(updates)
    return SelectionContext.model_validate(raw)


@pytest.mark.parametrize(
    "case", CASES, ids=lambda case: case["candidate"]["article_id"]
)
def test_documented_cases_apply_policy_to_input(case):
    actual = evaluate_candidate(
        SelectionCandidate.model_validate(case["candidate"]),
        SelectionContext.model_validate(case["context"]),
    )
    assert actual.disposition == case["expected"]["disposition"]
    assert actual.reason_code == case["expected"]["reason_code"]


@pytest.mark.parametrize(
    ("ids", "selected"),
    [
        (["N01", "N02", "N03", "N04", "N07", "N08", "N09"], ("N01", "N02")),
        (["N01", "N03", "N04", "N07", "N08", "N09"], ("N01",)),
        (["N03", "N04", "N07", "N08", "N09"], ()),
    ],
)
def test_morning_does_not_fill_empty_slots_with_ineligible_news(ids, selected):
    result = select_edition(tuple(candidate(key) for key in ids), context("AM"))
    assert result.selected_ids == selected
    assert result.status == "ready"  # 뉴스 0건이어도 지수 글은 가능하다.
    assert result.can_publish is False


def test_evening_selects_distinct_events_and_skips_normal_zero():
    ctx = context(
        "PM",
        prior_facts={"A:EARNINGS:2026-Q3": ("v1",), "B:ACQUISITION:T1": ("v1",)},
    )
    inputs = tuple(candidate(key) for key in ["N05", "N06", "N10", "N12"])
    assert select_edition(inputs, ctx).selected_ids == ("N12", "N06")
    result = select_edition((candidate("N05"), candidate("N10")), ctx)
    assert result.status == "no_content"
    assert result.selected_ids == ()


@pytest.mark.parametrize("edition", ["AM", "PM"])
@pytest.mark.parametrize("status", ["partial", "failed"])
def test_incomplete_collection_holds_whole_edition(edition, status):
    result = select_edition(
        (candidate("N01"),), context(edition, collection_status=status)
    )
    assert result.status == "held"
    assert result.reason_code == "INCOMPLETE_COLLECTION"
    assert result.selected_ids == ()


def test_required_indices_and_non_operating_day_are_separate_from_zero_news():
    assert select_edition((), context("AM", indices_complete=False)).status == "held"
    assert (
        select_edition((), context("AM", operating_day=False)).status == "not_operating"
    )


def test_third_candidate_loses_capacity_without_becoming_published_fact():
    other = candidate(
        "N06",
        article_id="N06b",
        event_key="B:ACQUISITION:T2",
        published_at="2026-10-28T13:00:00+09:00",
        collected_at="2026-10-28T13:05:00+09:00",
    )
    ctx = context("PM")
    result = select_edition((candidate("N12"), other, candidate("N06")), ctx)
    assert result.selected_ids == ("N12", "N06")
    assert (
        next(item for item in result.decisions if item.article_id == "N06b").reason_code
        == "NOT_SELECTED_CAPACITY"
    )
    assert ctx.prior_facts == {"B:ACQUISITION:T1": ("v1",)}


def test_equal_rank_uses_stable_id_but_same_event_never_occupies_two_slots():
    first = candidate("N06", article_id="aaa", event_key="B:ACQUISITION:T2")
    second = candidate("N06", article_id="bbb", event_key="B:ACQUISITION:T3")
    assert select_edition((second, first), context("PM")).selected_ids == ("aaa", "bbb")
    same = candidate("N06", article_id="ccc", event_key="B:ACQUISITION:T2")
    result = select_edition((same, first), context("PM"))
    assert result.selected_ids == ("aaa",)
    assert result.decisions[0].reason_code == "SAME_EVENT_IN_EDITION"


def test_materiality_precedes_scope_and_time():
    company = candidate("N06")
    review = company.index_relation.model_dump() | {"importance": "critical"}
    company = candidate("N06", index_relation=review)
    assert select_edition((candidate("N12"), company), context("PM")).selected_ids == (
        "N06",
        "N12",
    )


def test_correction_invalidates_whole_approved_edition_after_freeze():
    ctx = context("PM", approved_facts={"B:ACQUISITION:T1": ("v2",)})
    result = select_edition((candidate("N12"), candidate("N06"), candidate("N11")), ctx)
    assert result.status == "held"
    assert result.selected_ids == ()
    assert result.reason_code == "APPROVED_FACT_CORRECTED"
    # 승인 관련성이 없는 늦은 정정은 이번 편성에 새 근거로 추가하지 않는다.
    assert (
        evaluate_candidate(candidate("N11"), context("PM")).reason_code
        == "EVIDENCE_AFTER_FREEZE"
    )


def test_pm_publication_and_evidence_boundaries_are_inclusive():
    ctx = context("PM")
    exact = candidate(
        "N12",
        published_at=ctx.cutoff,
        collected_at=ctx.freeze,
    )
    assert evaluate_candidate(exact, ctx).disposition == "eligible"
    late = candidate(
        "N12",
        published_at=ctx.cutoff + timedelta(seconds=1),
        collected_at=ctx.freeze,
    )
    assert evaluate_candidate(late, ctx).reason_code == "AFTER_PM_CUTOFF"
    late = candidate("N12", collected_at=ctx.freeze + timedelta(seconds=1))
    assert evaluate_candidate(late, ctx).reason_code == "EVIDENCE_AFTER_FREEZE"


def test_morning_requires_information_obtained_by_cutoff_and_excludes_window_start():
    ctx = context("AM")
    exact = candidate("N01", published_at=ctx.cutoff, collected_at=ctx.freeze)
    assert evaluate_candidate(exact, ctx).disposition == "eligible"
    assert (
        evaluate_candidate(
            candidate("N01", collected_at=ctx.freeze + timedelta(seconds=1)), ctx
        ).reason_code
        == "EVIDENCE_AFTER_FREEZE"
    )
    assert (
        evaluate_candidate(
            candidate("N01", published_at=ctx.window_start), ctx
        ).reason_code
        == "BEFORE_WINDOW"
    )


def test_field_mutations_change_decision_without_case_specific_dispatch():
    original = candidate("N01")
    assert evaluate_candidate(original, context("AM")).disposition == "eligible"
    # 원본 ID를 유지해도 근거가 바뀌면 해당 사유로 제외해야 한다.
    claims = [claim.model_dump() for claim in original.claims]
    claims[0]["unit"] = None
    assert (
        evaluate_candidate(candidate("N01", claims=claims), context("AM")).reason_code
        == "INSUFFICIENT_EVIDENCE"
    )
    assert (
        evaluate_candidate(candidate("N01", confirmed=False), context("AM")).reason_code
        == "UNCONFIRMED"
    )
    review = original.index_relation.model_dump() | {"related": False}
    assert (
        evaluate_candidate(
            candidate("N01", index_relation=review), context("AM")
        ).reason_code
        == "INDEX_UNRELATED"
    )
    review = original.index_relation.model_dump() | {"reviewed": False}
    assert (
        evaluate_candidate(
            candidate("N01", index_relation=review), context("AM")
        ).reason_code
        == "RELATION_REVIEW_REQUIRED"
    )
    review = original.index_relation.model_dump() | {"importance": "routine"}
    assert (
        evaluate_candidate(
            candidate("N01", index_relation=review), context("AM")
        ).reason_code
        == "IMPORTANCE_NOT_ESTABLISHED"
    )


def test_changed_facts_need_explicit_material_followup_review():
    ctx = context("PM")
    changed = candidate("N06", material_new_fact=False)
    assert evaluate_candidate(changed, ctx).reason_code == "FOLLOWUP_REVIEW_REQUIRED"


def test_pending_approved_fact_is_also_duplicate_and_fixture_cannot_publish():
    ctx = context("PM", approved_facts={"B:ACQUISITION:T1": ("v2",)})
    assert (
        evaluate_candidate(candidate("N06"), ctx).reason_code == "SAME_EVENT_SAME_FACT"
    )
    for case in CASES:
        item = SelectionCandidate.model_validate(case["candidate"])
        assert item.synthetic is True
        assert item.can_publish is False


def test_rights_scope_and_synthetic_publish_block_cannot_be_overridden():
    with pytest.raises(ValidationError):
        candidate("N01", can_publish=True)
    real_scope = candidate("N01", synthetic=False)
    assert (
        evaluate_candidate(real_scope, context("AM")).reason_code == "RIGHTS_UNVERIFIED"
    )
    denied = candidate("N01").rights.model_dump() | {"ai_transfer": "denied"}
    assert (
        evaluate_candidate(candidate("N01", rights=denied), context("AM")).reason_code
        == "RIGHTS_UNVERIFIED"
    )


def test_official_guidance_is_a_confirmed_announcement_not_price_prediction():
    text = "A announced Q4 revenue guidance changed from 90-100 to 95-105 USD."
    guidance = candidate(
        "N02",
        article_id="guidance",
        event_type="official_guidance",
        evidence_text=text,
        evidence_version=digest(text),
        claims=[
            {
                "claim_id": "guidance",
                "subject": "A",
                "action": "announced guidance change",
                "period": "2026-Q4",
                "evidence_span": text,
                "evidence_position": "sentence:1",
                "conditions": "Company guidance; not realized revenue",
            }
        ],
    )
    assert (
        evaluate_candidate(guidance, context("AM")).reason_code
        == "ELIGIBLE_OFFICIAL_GUIDANCE"
    )
    assert (
        len(select_edition((guidance, candidate("N02")), context("AM")).selected_ids)
        == 1
    )


def test_evidence_hash_and_span_are_validated_and_duplicate_ids_rejected():
    with pytest.raises(ValidationError, match="content_version_mismatch"):
        candidate("N01", evidence_text="Changed")
    c = candidate("N01")
    claims = [claim.model_dump() for claim in c.claims]
    claims[0]["evidence_span"] = "Other claim 2.4"
    assert (
        evaluate_candidate(candidate("N01", claims=claims), context("AM")).reason_code
        == "INSUFFICIENT_EVIDENCE"
    )
    with pytest.raises(ValueError, match="duplicate_article_id"):
        select_edition((c, c), context("AM"))
