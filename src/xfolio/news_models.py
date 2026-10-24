"""뉴스 수집의 메모리 입력과 수집 상태. 기사 본문 저장 허가를 뜻하지 않는다."""

from datetime import UTC, timedelta
from typing import Literal
from urllib.parse import parse_qsl, urlsplit

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    field_validator,
    model_validator,
)

NewsError = Literal[
    "request_budget",
    "page_budget",
    "daily_request_limit",
    "rate_limit_60_seconds",
    "http_error",
    "transport_error",
    "invalid_payload",
    "invalid_pagination",
    "invalid_article",
    "invalid_publication_time",
    "article_outside_window",
    "pagination_changed",
    "duplicate_page",
    "article_conflict",
    "credential_echo",
]


class NewsArticle(BaseModel):
    """실기사 텍스트는 메모리에서만 사용한다. synthetic만 별도 저장 대상이다."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    provider: Literal["Marketaux", "synthetic"] = "Marketaux"
    article_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    description: str = ""
    snippet: str = ""
    source: str = Field(min_length=1)
    url: HttpUrl
    published_at: AwareDatetime
    retrieved_at: AwareDatetime

    @field_validator("article_id", "title", "source")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("empty_article_field")
        return value

    @field_validator("published_at", "retrieved_at")
    @classmethod
    def utc_time(cls, value):
        return value.astimezone(UTC)

    @field_validator("url")
    @classmethod
    def unauthenticated_source_url(cls, value):
        parts = urlsplit(str(value))
        if (
            parts.username
            or parts.password
            or any(
                name.lower()
                in {"api_token", "api_key", "apikey", "token", "authorization"}
                for name, _ in parse_qsl(parts.query)
            )
        ):
            raise ValueError("authenticated_source_url")
        return value


class NewsQueryReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    query_id: str
    search: str
    domains: tuple[str, ...] = ()
    symbols: tuple[str, ...] = ()
    group_similar: Literal[False] = False
    status: Literal["complete", "partial", "failed", "skipped"] = "skipped"
    requests: int = Field(default=0, ge=0)
    pages: tuple[dict, ...] = ()
    responses: tuple[dict, ...] = ()
    error: NewsError | None = None


class NewsCollection(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    status: Literal["complete", "partial", "failed"]
    window_start: AwareDatetime
    window_end: AwareDatetime
    collected_at: AwareDatetime
    articles: tuple[NewsArticle, ...] = ()
    requests: int = Field(default=0, ge=0)
    query_reports: tuple[NewsQueryReport, ...] = ()
    error: NewsError | None = None

    @field_validator("window_start", "window_end", "collected_at")
    @classmethod
    def utc_time(cls, value):
        return value.astimezone(UTC)

    @property
    def checkpoint_eligible(self) -> bool:
        return (
            self.status == "complete"
            and self.error is None
            and all(
                report.status == "complete" and report.error is None
                for report in self.query_reports
            )
        )

    @model_validator(mode="after")
    def valid_window(self):
        if (
            self.window_start >= self.window_end
            or self.window_end > self.collected_at
            or self.window_end - self.window_start > timedelta(days=7)
        ):
            raise ValueError("invalid_time_window")
        return self
