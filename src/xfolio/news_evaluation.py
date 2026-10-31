"""공통 입력의 근거·이용·시각·중복 검사. 의미 확인과 승인 권한은 부여하지 않는다."""

import json
import re
from decimal import Decimal
from typing import Literal

from pydantic import AwareDatetime, Field, model_validator

from xfolio.news_contracts import digest
from xfolio.news_input import Identifier, InputContract, NewsInput


class ValueRange(InputContract):
    lower: Decimal = Field(allow_inf_nan=False)
    upper: Decimal = Field(allow_inf_nan=False)

    @model_validator(mode="after")
    def ordered_range(self):
        if self.lower > self.upper:
            raise ValueError("invalid_value_range")
        return self


class NewsClaim(InputContract):
    claim_id: Identifier
    subject: Identifier
    action: Identifier
    metric: Identifier
    target_period: Identifier | None = None
    event_time: AwareDatetime | None = None
    statement_type: Literal["actual", "company_outlook", "analyst_estimate"]
    accounting_basis: Literal["GAAP", "non-GAAP", "not_applicable"]
    value: Decimal | None = Field(default=None, allow_inf_nan=False)
    value_range: ValueRange | None = None
    unit: Identifier | None = None
    comparison_basis: Identifier | None = None
    conditions: tuple[Identifier, ...] = ()
    evidence_span: Identifier
    evidence_locator: Identifier

    @model_validator(mode="after")
    def numeric_context(self):
        if self.target_period is None and self.event_time is None:
            raise ValueError("claim_time_context_required")
        if self.value is not None and self.value_range is not None:
            raise ValueError("scalar_range_conflict")
        if (self.value is not None or self.value_range is not None) and not all(
            (self.unit, self.target_period, self.comparison_basis)
        ):
            raise ValueError("numeric_context_required")
        return self


class NewsFacts(InputContract):
    input_id: Identifier
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    subject_id: Identifier
    event_type: Literal[
        "earnings",
        "merger_acquisition",
        "policy",
        "economic_indicator",
        "business_event",
    ]
    identity: Identifier
    extraction_mode: Literal["parser", "manual_review", "ai_candidate"]
    claims: tuple[NewsClaim, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_claims(self):
        if len({c.claim_id for c in self.claims}) != len(self.claims):
            raise ValueError("duplicate_claim_id")
        if self.event_type == "earnings" and any(
            c.accounting_basis == "not_applicable" for c in self.claims
        ):
            raise ValueError("earnings_accounting_basis_required")
        return self

    @property
    def event_key(self):
        return digest(json.dumps([self.subject_id, self.event_type, self.identity]))

    @property
    def fact_version(self):
        facts = [
            c.model_dump(
                mode="json", exclude={"claim_id", "evidence_span", "evidence_locator"}
            )
            for c in self.claims
        ]
        for fact, claim in zip(facts, self.claims, strict=True):
            if claim.value is not None:
                fact["value"] = str(claim.value.normalize())
            if claim.value_range:
                fact["value_range"] = {
                    "lower": str(claim.value_range.lower.normalize()),
                    "upper": str(claim.value_range.upper.normalize()),
                }
            fact["conditions"] = sorted(fact["conditions"])
        return digest(
            json.dumps(
                sorted(facts, key=lambda x: json.dumps(x, sort_keys=True)),
                sort_keys=True,
                separators=(",", ":"),
            )
        )


class PriorNewsFact(InputContract):
    event_key: Identifier
    fact_version: Identifier
    input_id: Identifier
    content_hash: Identifier
    approved: bool = False


class InputEvaluation(InputContract):
    input_id: Identifier
    disposition: Literal["candidate", "exclude", "duplicate", "hold", "review_required"]
    reason_codes: tuple[Identifier, ...]
    can_publish: Literal[False] = False
    human_review_required: Literal[True] = True


def _number_in_span(number, span):
    # 0.6과 10.6, 15와 150을 구분한다. 단위 변환·쉼표 제거는 추정하지 않는다.
    pattern = r"(?<![\w.])" + re.escape(str(number)) + r"(?![\w.])"
    return re.search(pattern, span) is not None


def evaluate_news_input(
    record: NewsInput,
    facts: NewsFacts | None,
    *,
    now: AwareDatetime,
    cutoff: AwareDatetime,
    window_start: AwareDatetime,
    purpose: Literal["ai_transfer", "summary_publication"] = "ai_transfer",
    prior: tuple[PriorNewsFact, ...] = (),
) -> InputEvaluation:
    """주어진 사실 후보의 기계 검사. 실제 문맥의 의미 대조는 사람이 수행한다."""
    if (
        any(t.utcoffset() is None for t in (now, cutoff, window_start))
        or not window_start < cutoff <= now
    ):
        raise ValueError("invalid_evaluation_window")
    if purpose not in {"ai_transfer", "summary_publication"}:
        raise ValueError("unknown_permission_purpose")

    def result(disposition, *codes):
        return InputEvaluation(
            input_id=record.input_id, disposition=disposition, reason_codes=codes
        )

    # 이미 승인된 동일 원문의 변화는 권리/충분성 탈락보다 먼저 전체 보류 신호를 낸다.
    if any(p.approved and p.input_id == record.supersedes for p in prior):
        return result("hold", "APPROVED_SOURCE_CHANGED")
    if facts and any(
        p.approved
        and p.event_key == facts.event_key
        and p.fact_version != facts.fact_version
        for p in prior
    ):
        return result("hold", "APPROVED_FACT_CHANGED")
    rights = record.rights
    if record.synthetic:
        return result("exclude", "SYNTHETIC_INPUT")
    if not rights.allows("collection", now=now) or not rights.allows(purpose, now=now):
        return result("exclude", "RIGHTS_UNVERIFIED")
    if not record.publication.reliable:
        return result("exclude", "PUBLISHED_TIME_UNVERIFIED")
    if not window_start < record.publication.value <= cutoff:
        return result("exclude", "PUBLICATION_OUTSIDE_WINDOW")
    if record.available_at is None or record.available_at > cutoff:
        return result("exclude", "EVIDENCE_AFTER_CUTOFF")
    if record.last_checked_at > now:
        return result("exclude", "CAPTURE_IN_FUTURE")
    if record.content.sufficiency != "sufficient":
        return result("exclude", "INSUFFICIENT_BODY")
    if record.document_type in {"unknown", "live_updates"}:
        return result("review_required", "DOCUMENT_TYPE_REVIEW_REQUIRED")
    if facts is None:
        return result("review_required", "FACTS_REQUIRED")
    if facts.input_id != record.input_id or facts.content_hash != record.content_hash:
        return result("exclude", "FACT_SOURCE_MISMATCH")
    if (record.event_key and record.event_key != facts.event_key) or (
        record.fact_version and record.fact_version != facts.fact_version
    ):
        return result("exclude", "FACT_VERSION_MISMATCH")
    for claim in facts.claims:
        if claim.evidence_span not in record.content.text:
            return result("exclude", "EVIDENCE_SPAN_MISSING")
        if any(c not in claim.evidence_span for c in claim.conditions):
            return result("exclude", "CONDITION_NOT_IN_EVIDENCE")
        numbers = (
            (claim.value,)
            if claim.value is not None
            else (
                (claim.value_range.lower, claim.value_range.upper)
                if claim.value_range
                else ()
            )
        )
        if any(not _number_in_span(n, claim.evidence_span) for n in numbers):
            return result("exclude", "VALUE_NOT_IN_EVIDENCE")
        if claim.accounting_basis != "not_applicable" and not re.search(
            r"(?<![\w-])" + re.escape(claim.accounting_basis) + r"(?![\w-])",
            claim.evidence_span,
        ):
            return result("exclude", "ACCOUNTING_BASIS_NOT_IN_EVIDENCE")
        if claim.statement_type == "analyst_estimate":
            return result("review_required", "ANALYST_ESTIMATE_REVIEW_REQUIRED")
    same_event = [p for p in prior if p.event_key == facts.event_key]
    if record.supersedes:
        return result("review_required", "CHANGED_SOURCE_REVIEW_REQUIRED")
    if any(p.fact_version == facts.fact_version for p in same_event):
        return result("duplicate", "SAME_EVENT_SAME_FACT")
    if same_event:
        return result("review_required", "CHANGED_FACT_REVIEW_REQUIRED")
    return result("candidate", "MACHINE_CHECKS_PASSED")
