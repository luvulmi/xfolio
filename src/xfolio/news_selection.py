"""검토된 근거 입력의 선정 정책. 중요성 추출·사실 판정·발행 승인은 별도다."""

from datetime import UTC, date, datetime, time
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import AwareDatetime, Field, HttpUrl, ValidationError, model_validator

from xfolio.news_contracts import Contract, EvidenceClaim, digest
from xfolio.news_models import NewsArticle

KST = ZoneInfo("Asia/Seoul")
Permission = Literal["permitted", "fixture_only", "unverified", "denied"]


class SelectionRights(Contract):
    collection: Permission
    storage: Permission
    ai_transfer: Permission
    summary_publication: Permission

    def usable(self, *, synthetic: bool) -> bool:
        allowed = {"permitted", "fixture_only"} if synthetic else {"permitted"}
        return all(value in allowed for value in self.model_dump().values())


class SelectionClaim(Contract):
    claim_id: str = Field(min_length=1)
    subject: str = Field(min_length=1)
    action: str = Field(min_length=1)
    period: str | None = None
    event_time: AwareDatetime | None = None
    value: str | None = None
    unit: str | None = None
    comparison_basis: str | None = None
    conditions: str | None = None
    evidence_span: str = Field(min_length=1)
    evidence_position: str = Field(min_length=1)


class RelationReview(Contract):
    """운영자/검토기가 근거와 함께 제공하는 판단. 이름 일치로 생성하지 않는다."""

    reviewed: bool = False
    related: bool = False
    reason: str = ""
    evidence_ref: str = ""
    importance: Literal["critical", "material", "routine", "uncertain"] = "uncertain"
    impact_scope: Literal["market", "sector", "company"] = "company"


class SelectionCandidate(Contract):
    article_id: str = Field(min_length=1)
    source: str = Field(min_length=1)
    url: HttpUrl
    published_at: AwareDatetime | None
    updated_at: AwareDatetime | None = None
    collected_at: AwareDatetime
    evidence_version: str = Field(min_length=1)
    evidence_text: str
    event_key: str = Field(min_length=1)
    fact_version: str = Field(min_length=1)
    event_type: Literal[
        "macro",
        "earnings",
        "analyst_opinion",
        "rumor",
        "acquisition",
        "sector_policy",
        "official_guidance",
    ]
    confirmed: bool = False
    claims: tuple[SelectionClaim, ...] = ()
    index_relation: RelationReview
    rights: SelectionRights
    material_new_fact: bool = False
    new_fact_reason: str = ""
    invalidates_fact_version: str | None = None
    synthetic: bool = True
    can_publish: Literal[False] = False

    @model_validator(mode="after")
    def source_integrity(self):
        NewsArticle.unauthenticated_source_url(self.url)
        if self.evidence_version != digest(self.evidence_text):
            raise ValueError("content_version_mismatch")
        if self.published_at and self.collected_at < self.published_at:
            raise ValueError("collection_before_publication")
        if self.updated_at and (
            self.published_at is None
            or not self.published_at <= self.updated_at <= self.collected_at
        ):
            raise ValueError("invalid_updated_at")
        return self


class SelectionContext(Contract):
    target_date: date
    edition: Literal["AM", "PM"]
    window_start: AwareDatetime
    collection_status: Literal["complete", "partial", "failed"] = "complete"
    indices_complete: bool = True
    operating_day: bool = True
    prior_facts: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    approved_facts: dict[str, tuple[str, ...]] = Field(default_factory=dict)

    @property
    def cutoff(self) -> datetime:
        return datetime.combine(
            self.target_date, time(7, 30) if self.edition == "AM" else time(17, 30), KST
        )

    @property
    def freeze(self) -> datetime:
        return datetime.combine(
            self.target_date, time(7, 30) if self.edition == "AM" else time(17, 45), KST
        )

    @model_validator(mode="after")
    def valid_window(self):
        if self.window_start >= self.cutoff:
            raise ValueError("invalid_selection_window")
        return self


class CandidateDecision(Contract):
    article_id: str
    disposition: Literal["eligible", "exclude", "duplicate", "hold", "not_selected"]
    reason_code: str


class EditionSelection(Contract):
    status: Literal["ready", "no_content", "held", "not_operating"]
    selected_ids: tuple[str, ...] = ()
    decisions: tuple[CandidateDecision, ...] = ()
    reason_code: str | None = None
    can_publish: Literal[False] = False


def _has_evidence(candidate: SelectionCandidate) -> bool:
    if not candidate.claims:
        return False
    for claim in candidate.claims:
        try:
            # 기존 숫자/조건 필수 계약을 그대로 적용한다.
            EvidenceClaim(
                source_id=candidate.article_id,
                content_version=candidate.evidence_version,
                event_type=candidate.event_type,
                certainty="conditional" if claim.conditions else "confirmed",
                **claim.model_dump(exclude={"claim_id", "evidence_position"}),
            )
        except ValidationError:
            return False
        if claim.evidence_span not in candidate.evidence_text:
            return False
        if claim.value is not None:
            import re

            if not re.search(
                r"(?<![\w.])" + re.escape(claim.value) + r"(?![\w.])",
                claim.evidence_span,
            ):
                return False
    return True


def evaluate_candidate(
    candidate: SelectionCandidate, context: SelectionContext
) -> CandidateDecision:
    """기대 판정 필드를 받지 않고 실제 입력 조건을 평가한다."""

    def decision(disposition, code):
        return CandidateDecision(
            article_id=candidate.article_id, disposition=disposition, reason_code=code
        )

    if not candidate.rights.usable(synthetic=candidate.synthetic):
        return decision("exclude", "RIGHTS_UNVERIFIED")
    if candidate.published_at is None:
        return decision("exclude", "PUBLISHED_TIME_UNKNOWN")
    if not _has_evidence(candidate):
        return decision("exclude", "INSUFFICIENT_EVIDENCE")
    # 동결 후 재조회는 기존 승인 사실의 무효화 탐지에만 사용한다.
    if candidate.invalidates_fact_version in context.approved_facts.get(
        candidate.event_key, ()
    ):
        return decision("hold", "APPROVED_FACT_CORRECTED")
    if candidate.published_at > context.cutoff:
        return decision(
            "exclude",
            "AFTER_PM_CUTOFF" if context.edition == "PM" else "AFTER_AM_CUTOFF",
        )
    if candidate.published_at <= context.window_start:
        return decision("exclude", "BEFORE_WINDOW")
    if candidate.collected_at > context.freeze or (
        candidate.updated_at and candidate.updated_at > context.freeze
    ):
        return decision("exclude", "EVIDENCE_AFTER_FREEZE")
    if candidate.event_type == "analyst_opinion":
        return decision("exclude", "OPINION_ONLY")
    if candidate.event_type == "rumor" or not candidate.confirmed:
        return decision("exclude", "UNCONFIRMED")
    relation = candidate.index_relation
    if not relation.reviewed or not relation.reason or not relation.evidence_ref:
        return decision("exclude", "RELATION_REVIEW_REQUIRED")
    if not relation.related:
        return decision("exclude", "INDEX_UNRELATED")
    if relation.importance not in {"critical", "material"}:
        return decision("exclude", "IMPORTANCE_NOT_ESTABLISHED")
    previous = tuple(
        set(context.prior_facts.get(candidate.event_key, ()))
        | set(context.approved_facts.get(candidate.event_key, ()))
    )
    if candidate.fact_version in previous:
        return decision("duplicate", "SAME_EVENT_SAME_FACT")
    if previous:
        if not candidate.material_new_fact or not candidate.new_fact_reason:
            return decision("exclude", "FOLLOWUP_REVIEW_REQUIRED")
        return decision("eligible", "MATERIAL_NEW_FACT")
    return decision(
        "eligible",
        {
            "macro": "ELIGIBLE_MACRO",
            "earnings": "ELIGIBLE_EARNINGS",
            "acquisition": "ELIGIBLE_ACQUISITION",
            "sector_policy": "ELIGIBLE_SECTOR_POLICY",
            "official_guidance": "ELIGIBLE_OFFICIAL_GUIDANCE",
        }[candidate.event_type],
    )


def select_edition(
    candidates: tuple[SelectionCandidate, ...], context: SelectionContext
) -> EditionSelection:
    """검토 입력을 편성한다. 출력은 항상 발행 불가 미리보기다."""
    if len({candidate.article_id for candidate in candidates}) != len(candidates):
        raise ValueError("duplicate_article_id")
    if not context.operating_day:
        return EditionSelection(status="not_operating", reason_code="NOT_OPERATING_DAY")
    if context.collection_status != "complete":
        return EditionSelection(status="held", reason_code="INCOMPLETE_COLLECTION")
    if context.edition == "AM" and not context.indices_complete:
        return EditionSelection(status="held", reason_code="REQUIRED_INDEX_MISSING")
    decisions = [evaluate_candidate(candidate, context) for candidate in candidates]
    if any(decision.disposition == "hold" for decision in decisions):
        return EditionSelection(
            status="held",
            decisions=tuple(decisions),
            reason_code="APPROVED_FACT_CORRECTED",
        )
    by_id = {candidate.article_id: candidate for candidate in candidates}

    def order(decision):
        candidate = by_id[decision.article_id]
        return (
            {"critical": 0, "material": 1}[candidate.index_relation.importance],
            {"market": 0, "sector": 1, "company": 2}[
                candidate.index_relation.impact_scope
            ],
            -candidate.published_at.astimezone(UTC).timestamp(),
            candidate.article_id,
        )

    eligible = sorted(
        (decision for decision in decisions if decision.disposition == "eligible"),
        key=order,
    )
    selected, events = [], set()
    replacements = {}
    for decision in eligible:
        event = by_id[decision.article_id].event_key
        if event in events:
            replacements[decision.article_id] = decision.model_copy(
                update={
                    "disposition": "duplicate",
                    "reason_code": "SAME_EVENT_IN_EDITION",
                }
            )
        elif len(selected) == 2:
            replacements[decision.article_id] = decision.model_copy(
                update={
                    "disposition": "not_selected",
                    "reason_code": "NOT_SELECTED_CAPACITY",
                }
            )
        else:
            selected.append(decision.article_id)
            events.add(event)
    return EditionSelection(
        status="ready" if selected or context.edition == "AM" else "no_content",
        selected_ids=tuple(selected),
        decisions=tuple(replacements.get(item.article_id, item) for item in decisions),
    )
