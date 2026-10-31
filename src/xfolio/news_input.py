"""N02 공통 수집 입력. 메모리 계약이며 저장·의미 승인·게시 허가가 아니다."""

from datetime import UTC
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    StringConstraints,
    field_validator,
    model_validator,
)

from xfolio.news_contracts import digest
from xfolio.news_models import NewsArticle

Identifier = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
SourceId = Literal["exa", "bls"]
Permission = Literal["permitted", "pending_review", "restricted", "expired"]
ErrorCode = Literal[
    "transport_error",
    "http_error",
    "rate_limit",
    "request_budget",
    "invalid_payload",
    "invalid_publication_time",
    "content_fetch_failed",
    "result_limit",
    "credential_echo",
    "cost_unknown",
    "cost_budget",
    "article_conflict",
    "expected_release_missing",
]


class InputContract(BaseModel):
    # 본문·원래 시각 문자열은 strip하지 않는다.
    model_config = ConfigDict(frozen=True, extra="forbid")


class PublicationTime(InputContract):
    raw: str | None = None
    value: AwareDatetime | None = None
    timezone: Identifier | None = None
    precision: Literal["date", "minute", "second", "unknown"] = "unknown"
    verified: bool = False

    @field_validator("value")
    @classmethod
    def utc_time(cls, value):
        return value.astimezone(UTC) if value else None

    @model_validator(mode="after")
    def valid_precision(self):
        if self.precision != "unknown" and not (self.raw and self.raw.strip()):
            raise ValueError("publication_raw_required")
        if self.precision == "date" and self.value is not None:
            raise ValueError("date_must_not_become_midnight")
        if self.verified and (
            self.precision not in {"minute", "second"}
            or self.value is None
            or not self.timezone
            or not (self.raw and self.raw.strip())
        ):
            raise ValueError("verified_publication_requires_precise_time")
        return self

    @property
    def reliable(self) -> bool:
        return self.verified and self.value is not None


class InputRights(InputContract):
    collection: Permission = "pending_review"
    storage: Permission = "pending_review"
    ai_transfer: Permission = "pending_review"
    summary_publication: Permission = "pending_review"
    review_id: Identifier | None = None
    reviewed_by: Identifier | None = None
    reviewed_at: AwareDatetime | None = None
    policy_reference: Identifier | None = None
    expires_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def reviewed_permission(self):
        if "permitted" in (
            self.collection,
            self.storage,
            self.ai_transfer,
            self.summary_publication,
        ) and not all(
            (self.review_id, self.reviewed_by, self.reviewed_at, self.policy_reference)
        ):
            raise ValueError("permission_review_required")
        if self.expires_at and (
            self.reviewed_at is None or self.expires_at <= self.reviewed_at
        ):
            raise ValueError("invalid_permission_expiry")
        return self

    def allows(self, purpose: str, *, now: AwareDatetime) -> bool:
        if purpose not in {
            "collection",
            "storage",
            "ai_transfer",
            "summary_publication",
        }:
            raise ValueError("unknown_permission_purpose")
        return (
            getattr(self, purpose) == "permitted"
            and self.reviewed_at is not None
            and self.reviewed_at <= now
            and (self.expires_at is None or now < self.expires_at)
        )


class ContentEvidence(InputContract):
    text: str | None = None
    text_chars: int = Field(ge=0, strict=True)
    requested_max_chars: int | None = Field(default=None, gt=0, strict=True)
    truncation: Literal["unknown", "detected", "not_detected"] = "unknown"
    title_only: bool = False
    sufficiency: Literal["not_assessed", "insufficient", "sufficient"] = "not_assessed"
    reason: Identifier | None = None
    assessed_by: Identifier | None = None
    assessed_at: AwareDatetime | None = None
    evidence_spans: tuple[Identifier, ...] = ()

    @property
    def limit_reached(self) -> bool:
        return (
            self.requested_max_chars is not None
            and self.text_chars >= self.requested_max_chars
        )

    @model_validator(mode="after")
    def valid_content(self):
        if self.text is not None and len(self.text) != self.text_chars:
            raise ValueError("text_length_mismatch")
        if self.sufficiency != "not_assessed" and not all(
            (self.reason, self.assessed_by, self.assessed_at)
        ):
            raise ValueError("content_assessment_required")
        if self.evidence_spans and (
            not self.text or any(span not in self.text for span in self.evidence_spans)
        ):
            raise ValueError("evidence_span_missing")
        if self.sufficiency == "sufficient" and (
            not self.text
            or not self.text.strip()
            or not self.evidence_spans
            or self.title_only
            or self.truncation != "not_detected"
            or self.limit_reached
        ):
            raise ValueError("content_not_sufficient")
        return self


class NewsInput(InputContract):
    schema_version: Literal["news_common_input_v1"] = "news_common_input_v1"
    input_id: Identifier
    source_id: SourceId
    source_record_id: Identifier
    source_url: HttpUrl
    publisher: Identifier
    publisher_url: HttpUrl | None = None
    document_type: Literal["article", "press_release", "live_updates", "unknown"]
    publication: PublicationTime
    acceptance: PublicationTime | None = None
    retrieved_at: AwareDatetime
    available_at: AwareDatetime | None = None
    last_checked_at: AwareDatetime
    collection_run_id: Identifier
    content: ContentEvidence
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    source_revision: Identifier | None = None
    revision_kind: Literal["native", "content_hash", "unknown"] = "unknown"
    event_key: Identifier | None = None
    fact_version: Identifier | None = None
    supersedes: Identifier | None = None
    change_reason: Identifier | None = None
    is_new_version: bool = True
    data_origin: Literal["live_capture", "permitted_fixture", "synthetic_fixture"]
    synthetic: bool
    rights: InputRights = Field(default_factory=InputRights)

    @field_validator("source_url", "publisher_url")
    @classmethod
    def safe_url(cls, value):
        return NewsArticle.unauthenticated_source_url(value) if value else None

    @field_validator("retrieved_at", "available_at", "last_checked_at")
    @classmethod
    def utc_time(cls, value):
        return value.astimezone(UTC) if value else None

    @model_validator(mode="after")
    def valid_input(self):
        if self.synthetic != (self.data_origin == "synthetic_fixture"):
            raise ValueError("data_origin_mismatch")
        if self.last_checked_at < self.retrieved_at or (
            self.available_at is not None
            and not self.retrieved_at <= self.available_at <= self.last_checked_at
        ):
            raise ValueError("invalid_capture_times")
        for stamp in (self.publication, self.acceptance):
            if stamp and stamp.reliable and stamp.value > self.retrieved_at:
                raise ValueError("capture_before_publication")
        if self.content.text is not None and (
            self.content_hash != digest(self.content.text) or self.available_at is None
        ):
            raise ValueError("content_hash_or_availability_required")
        if self.content.assessed_at and self.content.assessed_at > self.last_checked_at:
            raise ValueError("assessment_after_last_check")
        if self.revision_kind == "content_hash" and (
            not self.content_hash or self.source_revision != self.content_hash
        ):
            raise ValueError("hash_revision_mismatch")
        if self.revision_kind == "native" and not self.source_revision:
            raise ValueError("native_revision_required")
        if self.revision_kind == "unknown" and self.source_revision is not None:
            raise ValueError("unknown_revision_has_value")
        if self.content_hash and self.revision_kind == "unknown":
            raise ValueError("revision_kind_required")
        if (self.event_key is None) != (self.fact_version is None):
            raise ValueError("event_version_pair_required")
        if self.supersedes and (
            self.supersedes == self.input_id or not self.change_reason
        ):
            raise ValueError("invalid_superseded_input")
        return self

    def rechecked(self, *, checked_at: AwareDatetime) -> "NewsInput":
        """같은 버전 재확인. 최초 조회/확보 시각과 본문은 보존한다."""
        updated = self.model_validate(
            self.model_dump() | {"last_checked_at": checked_at}
        )
        if updated.last_checked_at < self.last_checked_at:
            raise ValueError("recheck_cannot_rewind")
        return updated


class ScopeReport(InputContract):
    scope_id: Identifier
    kind: Literal["search", "contents", "release"]
    status: Literal["complete", "partial", "failed"]
    requests: int = Field(ge=0, strict=True)
    input_ids: tuple[Identifier, ...] = ()
    error_codes: tuple[ErrorCode, ...] = ()
    response_cost_usd: Decimal | None = Field(default=None, ge=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def valid_report(self):
        if len(set(self.input_ids)) != len(self.input_ids):
            raise ValueError("duplicate_scope_input")
        if self.status == "complete" and (not self.requests or self.error_codes):
            raise ValueError("invalid_complete_scope")
        if self.status != "complete" and not self.error_codes:
            raise ValueError("scope_failure_reason_required")
        if self.status == "failed" and self.input_ids:
            raise ValueError("failed_scope_has_results")
        return self


class NewsInputCollection(InputContract):
    schema_version: Literal["news_common_collection_v1"] = "news_common_collection_v1"
    collection_run_id: Identifier
    source_id: SourceId
    adapter_version: Identifier
    query_version: Identifier
    watchlist_version: Identifier | None = None
    scope: Identifier
    window_start: AwareDatetime
    window_end: AwareDatetime
    finished_at: AwareDatetime
    required_scope_ids: tuple[Identifier, ...] = Field(min_length=1)
    reports: tuple[ScopeReport, ...] = ()
    records: tuple[NewsInput, ...] = ()
    status: Literal["complete", "partial", "failed"]

    @field_validator("window_start", "window_end", "finished_at")
    @classmethod
    def utc_time(cls, value):
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def valid_collection(self):
        if not self.window_start < self.window_end <= self.finished_at:
            raise ValueError("invalid_collection_window")
        required = set(self.required_scope_ids)
        by_scope = {report.scope_id: report for report in self.reports}
        if (
            len(required) != len(self.required_scope_ids)
            or len(by_scope) != len(self.reports)
            or not set(by_scope) <= required
        ):
            raise ValueError("invalid_required_scopes")
        complete = len(by_scope) == len(required) and all(
            report.status == "complete" for report in self.reports
        )
        progress = any(report.status != "failed" for report in self.reports)
        expected = "complete" if complete else "partial" if progress else "failed"
        if self.status != expected:
            raise ValueError("collection_status_mismatch")
        ids = {record.input_id for record in self.records}
        referenced = {key for report in self.reports for key in report.input_ids}
        if len(ids) != len(self.records) or ids != referenced:
            raise ValueError("collection_input_reference_mismatch")
        versions = {
            (record.source_record_id, record.source_revision, record.content_hash)
            for record in self.records
        }
        if len(versions) != len(self.records):
            raise ValueError("duplicate_source_version")
        for record in self.records:
            if (
                record.source_id != self.source_id
                or record.collection_run_id != self.collection_run_id
            ):
                raise ValueError("collection_source_mismatch")
            if record.last_checked_at > self.finished_at:
                raise ValueError("capture_after_collection")
        return self

    @property
    def normal_zero(self) -> bool:
        return self.status == "complete" and not self.records

    @property
    def new_version_count(self) -> int:
        return sum(record.is_new_version for record in self.records)

    @property
    def no_updates(self) -> bool:
        return self.status == "complete" and self.new_version_count == 0

    @property
    def response_cost_usd(self) -> Decimal | None:
        # 불명/누락 비용을 0으로 정산하지 않는다.
        if len(self.reports) != len(self.required_scope_ids) or any(
            report.response_cost_usd is None for report in self.reports
        ):
            return None
        return sum((r.response_cost_usd for r in self.reports), Decimal(0))
