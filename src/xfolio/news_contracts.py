"""제공처 공통 근거·사건·수집 계약. 형식 검증은 의미 검토를 대체하지 않는다."""

import hashlib
import json
import re
from datetime import UTC, timedelta
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from xfolio.news_models import NewsArticle


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class Contract(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)


class SourceRecord(Contract):
    provider: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    source_url: str
    published_at: AwareDatetime
    updated_at: AwareDatetime | None = None
    retrieved_at: AwareDatetime
    timestamp_precision: Literal["minute", "second"]
    content_version: str
    permission_scope: Literal["bls_public_text", "unverified"] = "unverified"
    collection_run_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    text_scope: str = Field(min_length=1)

    @model_validator(mode="after")
    def valid_source(self):
        # 기존 기사와 같은 인증 URL 차단 규칙을 재사용한다.
        from pydantic import HttpUrl, TypeAdapter

        NewsArticle.unauthenticated_source_url(
            TypeAdapter(HttpUrl).validate_python(self.source_url)
        )
        if self.content_version != digest(self.text):
            raise ValueError("content_version_mismatch")
        if self.updated_at and self.updated_at < self.published_at:
            raise ValueError("invalid_updated_at")
        return self


class EvidenceClaim(Contract):
    source_id: str
    content_version: str
    subject: str = Field(min_length=1)
    event_type: str = Field(min_length=1)
    action: str = Field(min_length=1)
    certainty: Literal["confirmed", "forecast", "conditional"]
    period: str | None = None
    event_time: AwareDatetime | None = None
    value: str | None = None
    unit: str | None = None
    comparison_basis: str | None = None
    conditions: str | None = None
    evidence_span: str = Field(min_length=1)

    @model_validator(mode="after")
    def complete_claim(self):
        if not self.period and not self.event_time:
            raise ValueError("missing_period")
        if self.value is not None and not all(
            (self.unit, self.period, self.comparison_basis)
        ):
            raise ValueError("numeric_context_required")
        if self.value is not None and not re.fullmatch(r"-?\d+(?:\.\d+)?", self.value):
            raise ValueError("invalid_numeric_value")
        if self.certainty == "conditional" and not self.conditions:
            raise ValueError("truncated_condition")
        return self


class NewsEvent(Contract):
    subject_id: str = Field(min_length=1)
    event_type: str = Field(min_length=1)
    period_or_transaction: str = Field(min_length=1)
    claims: tuple[EvidenceClaim, ...] = ()
    eligibility_status: Literal["eligible", "excluded", "review_required"] = (
        "review_required"
    )
    reason_codes: tuple[str, ...] = ("event_scope_uncertain",)
    prior_event_version: str | None = None

    @property
    def event_key(self) -> str:
        return digest(
            json.dumps([self.subject_id, self.event_type, self.period_or_transaction])
        )

    @property
    def fact_version(self) -> str:
        # 출처/발췌만 달라진 재인용은 같은 사실 버전으로 유지한다.
        facts = [
            c.model_dump(
                mode="json", exclude={"source_id", "content_version", "evidence_span"}
            )
            for c in self.claims
        ]
        return digest(
            json.dumps(
                sorted(facts, key=lambda v: json.dumps(v, sort_keys=True)),
                sort_keys=True,
            )
        )

    @model_validator(mode="after")
    def eligible_has_evidence(self):
        if self.eligibility_status == "eligible" and (
            not self.claims or self.reason_codes
        ):
            raise ValueError("eligible_requires_claims_without_holds")
        return self


class EvidenceBundle(Contract):
    source: SourceRecord
    event: NewsEvent

    @model_validator(mode="after")
    def linked_evidence(self):
        for claim in self.event.claims:
            if (
                claim.source_id != self.source.source_id
                or claim.content_version != self.source.content_version
            ):
                raise ValueError("evidence_source_mismatch")
            if claim.evidence_span not in self.source.text:
                raise ValueError("evidence_span_missing")
            if claim.value is not None and not re.search(
                r"(?<![\w.])" + re.escape(claim.value) + r"(?![\w.])",
                claim.evidence_span,
            ):
                raise ValueError("value_not_in_evidence")
        if (
            self.event.eligibility_status == "eligible"
            and self.source.permission_scope == "unverified"
        ):
            raise ValueError("rights_unverified")
        return self


class CollectionRun(Contract):
    run_id: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    query_version: str = Field(min_length=1)
    scope: str = Field(min_length=1)
    window_start: AwareDatetime
    window_end: AwareDatetime
    finished_at: AwareDatetime
    cursor_before: AwareDatetime | None = None
    required_queries: tuple[str, ...]
    completed_queries: tuple[str, ...] = ()
    status: Literal["complete", "partial", "failed"]
    requests: int = Field(ge=0)
    error: str | None = None

    @model_validator(mode="after")
    def valid_run(self):
        if (
            not self.window_start < self.window_end <= self.finished_at
            or self.window_end - self.window_start > timedelta(days=7)
        ):
            raise ValueError("invalid_time_window")
        required, completed = set(self.required_queries), set(self.completed_queries)
        if (
            not required
            or len(required) != len(self.required_queries)
            or len(completed) != len(self.completed_queries)
            or not completed <= required
        ):
            raise ValueError("invalid_query_set")
        if self.status == "complete" and (
            required != completed or self.error is not None
        ):
            raise ValueError("incomplete_required_queries")
        return self

    @property
    def cursor_key(self):
        return json.dumps([self.provider, self.query_version, self.scope])

    @property
    def end_utc(self):
        return self.window_end.astimezone(UTC).isoformat()
