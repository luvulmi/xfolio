"""OpenAPI의 게시 편성·결정 계약."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Edition = Literal["AM", "PM"]
Status = Literal[
    "prepared",
    "validated",
    "approved",
    "scheduled",
    "sending",
    "published",
    "held",
    "failed",
    "partial",
    "unknown",
    "expired",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DecisionRequest(StrictModel):
    action: Literal["approve", "hold"]
    expected_version: int = Field(ge=1)
    expected_decision_revision: int = Field(ge=0)
    reason: str | None = Field(default=None, min_length=1, max_length=300)

    @model_validator(mode="after")
    def hold_reason(self):
        if self.action == "hold" and (not self.reason or not self.reason.strip()):
            raise ValueError("hold_reason_required")
        return self


class Operator(StrictModel):
    email: str
    display_name: str


class Me(StrictModel):
    operator: Operator
    mode: Literal["dry_run", "reviewed", "auto"]
    csrf_token: str
    allowed_actions: list[str]


class DraftSummary(StrictModel):
    id: str
    target_date: date
    edition: Edition
    market_trade_date: date | None = None
    version: int
    decision_revision: int
    status: Status
    news_count: int
    scheduled_at: datetime
    expires_at: datetime


class DraftList(StrictModel):
    items: list[DraftSummary]
    next_cursor: str | None = None


class Validation(StrictModel):
    status: str
    blocking_reasons: list[str] = []


class Post(StrictModel):
    position: int
    kind: Literal["index", "news"]
    text: str
    evidence_ids: list[str] = []
    evidence: list[dict] = []
    event_key: str | None = None
    fact_version: str | None = None


class DraftDetail(DraftSummary):
    mode: Literal["dry_run", "reviewed", "auto"]
    synthetic: bool
    validation: Validation
    frozen_at: datetime | None = None
    posts: list[Post]
    allowed_actions: list[str]
    publication: dict = Field(default_factory=lambda: {"job_id": None, "posts": []})
    history: list[dict] = []
    hold_reason: str | None = None


class DecisionResult(StrictModel):
    decision_id: str
    applied: bool
    replayed: bool
    version: int
    decision_revision: int
    status: Status
    original_result: dict | None = None


class OperationsSummary(StrictModel):
    collection: dict
    usage: dict
    publications: dict
    alerts: dict
