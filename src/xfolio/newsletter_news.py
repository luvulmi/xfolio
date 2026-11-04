"""개인 뉴스레터 수집·공식 요약·선정. 발송/예약과 legacy X 편성은 수행하지 않는다."""

import json
import re
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Literal

import httpx
from pydantic import AwareDatetime, Field, model_validator

from xfolio.finnhub import (
    event_bucket,
    filter_rows,
    resolve_link,
    title_key,
)
from xfolio.news_contracts import Contract, digest
from xfolio.news_generation import estimate_input_tokens
from xfolio.news_workflow import GenerationLimits, GenerationResponse

PROVIDERS = ("Finnhub", "BLS", "BEA", "Board")


class NewsError(ValueError):
    """인증값·원문·외부 예외를 포함하지 않는 오류 코드."""


def aware(value):
    if value.utcoffset() is None:
        raise NewsError("timezone_required")
    return value.astimezone(UTC)


def topic(title):
    patterns = {
        "CPI": r"\bcpi\b|consumer price index",
        "PCE": r"\bpce\b|personal income and outlays",
        "GDP": r"\bgdp\b|gross domestic product",
        "FOMC": r"\bfomc\b|fed(?:eral reserve)?.*\b(?:rates?|rate decision)\b",
    }
    return next(
        (k for k, p in patterns.items() if re.search(p, title, re.IGNORECASE)), ""
    )


class Fact(Contract):
    claim_id: str = Field(min_length=1)
    evidence_span: str = Field(min_length=1)
    allowed_texts: tuple[str, ...] = Field(min_length=1)


class NewsItem(Contract):
    provider: Literal["Finnhub", "BLS", "BEA", "Board"]
    kind: Literal["link", "official"]
    source_id: str = Field(min_length=1)
    url: str
    title: str = Field(min_length=1, max_length=500)
    publisher: str
    published_at: AwareDatetime
    retrieved_at: AwareDatetime
    content_version: str
    event_key: str
    facts: tuple[Fact, ...] = ()
    summary_ko: str | None = None
    permission_reference: str
    synthetic: bool = False

    @model_validator(mode="after")
    def validate_scope(self):
        if self.published_at > self.retrieved_at:
            raise ValueError("publication_after_retrieval")
        if self.provider == "Finnhub":
            from urllib.parse import urlsplit

            from xfolio.finnhub import PUBLISHERS, canonical_url, is_article_url

            domain = PUBLISHERS.get(self.publisher.casefold())
            if (
                self.kind != "link"
                or self.facts
                or self.summary_ko is not None
                or not domain
                or canonical_url(self.url) != self.url
                or urlsplit(self.url).hostname not in (domain, "www." + domain)
                or not is_article_url(self.url, domain)
            ):
                raise ValueError("general_news_scope_invalid")
        else:
            from xfolio.official_releases import official_url

            if (
                self.kind != "official"
                or not self.facts
                or not official_url(self.provider, self.url)
            ):
                raise ValueError("official_scope_invalid")
            expected_permission = (
                "bls_public_text:2026-11-02"
                if self.provider == "BLS"
                else "official_self_authored:2026-11-02"
            )
            if self.permission_reference != expected_permission:
                raise ValueError("official_permission_unverified")
        return self

    @property
    def keys(self):
        return (
            "id:" + digest(self.provider + ":" + self.source_id),
            "url:" + digest(self.url),
            "title:" + digest(title_key(self.title, self.publisher)),
            "event:" + digest(self.event_key),
        )

    def metadata(self):
        # 근거 원문과 허용 문형은 메모리에만 둔다.
        return self.model_dump(mode="json", exclude={"facts"})


class SourceResult(Contract):
    provider: Literal["Finnhub", "BLS", "BEA", "Board"]
    status: Literal["complete", "partial", "failed"]
    items: tuple[NewsItem, ...] = ()
    requests: int = Field(ge=0)
    errors: tuple[str, ...] = ()
    excluded: dict[str, int] = Field(default_factory=dict)

    @model_validator(mode="after")
    def consistent_result(self):
        if (self.status == "complete") != (not self.errors):
            raise ValueError("source_status_error_mismatch")
        if any(item.provider != self.provider for item in self.items):
            raise ValueError("source_item_provider_mismatch")
        if any(count < 0 for count in self.excluded.values()):
            raise ValueError("invalid_excluded_count")
        return self


class NewsResult(Contract):
    run_id: str
    as_of: AwareDatetime
    finished_at: AwareDatetime
    status: Literal["complete", "partial", "failed"]
    sources: tuple[SourceResult, ...]
    selected: tuple[NewsItem, ...] = Field(max_length=3)
    excluded: dict[str, int]

    @model_validator(mode="after")
    def consistent_result(self):
        if (
            self.as_of > self.finished_at
            or len(self.sources) != 4
            or {s.provider for s in self.sources} != set(PROVIDERS)
        ):
            raise ValueError("collection_scope_or_times_invalid")
        if self.status == "complete" and (
            any(s.status != "complete" for s in self.sources)
            or any(
                self.excluded.get(k, 0)
                for k in ("summary_failed", "summary_not_configured")
            )
        ):
            raise ValueError("collection_status_invalid")
        keys = set()
        for item in self.selected:
            if (
                not self.as_of - timedelta(hours=96) <= item.published_at <= self.as_of
                or item.retrieved_at > self.finished_at
                or keys.intersection(item.keys)
            ):
                raise ValueError("selected_time_or_duplicates_invalid")
            if item.kind == "official" and not item.summary_ko:
                raise ValueError("selected_summary_required")
            keys.update(item.keys)
        return self

    @property
    def normal_zero(self):
        return self.status == "complete" and not self.selected

    def report(self):
        return {
            "run_id": self.run_id,
            "as_of": self.as_of.isoformat(),
            "finished_at": self.finished_at.isoformat(),
            "status": self.status,
            "normal_zero": self.normal_zero,
            "selected": [x.metadata() for x in self.selected],
            "sources": [
                s.model_dump(mode="json", exclude={"items"}) for s in self.sources
            ],
            "excluded": self.excluded,
            "can_send": False,
        }


def collect_finnhub(client, *, api_key, as_of, clock=lambda: datetime.now(UTC)):
    as_of = aware(as_of)
    if not api_key.strip():
        return SourceResult(
            provider="Finnhub",
            status="failed",
            requests=0,
            errors=("configuration_missing",),
        )
    try:
        with client.stream(
            "GET",
            "https://finnhub.io/api/v1/news",
            params={"category": "general", "minId": 0},
            headers={"X-Finnhub-Token": api_key},
            timeout=20,
            follow_redirects=False,
        ) as response:
            if response.status_code != 200:
                raise NewsError("http_" + str(response.status_code))
            content = b""
            for chunk in response.iter_bytes():
                content += chunk
                if len(content) > 2_000_000:
                    raise NewsError("response_limit")
            rows = json.loads(content)
        if (
            not isinstance(rows, list)
            or len(rows) > 1000
            or any(not isinstance(r, dict) for r in rows)
        ):
            raise NewsError("response_schema")
        rows = [
            {k: r.get(k) for k in ("id", "datetime", "headline", "source", "url")}
            for r in rows
        ]
        retrieved = aware(clock())
        candidates, excluded = filter_rows(rows, as_of)
        # bool/NaN/음수 timestamp를 datetime으로 묵인하지 않는다.
        invalid = [
            r for r in rows if type(r.get("datetime")) is not int or r["datetime"] < 0
        ]
        invalid_ids = {id(r) for r in invalid}
        if invalid:
            candidates, excluded = filter_rows(
                [r for r in rows if id(r) not in invalid_ids], as_of
            )
            excluded["invalid_row"] += len(invalid)
        items, calls, errors = [], 1, []
        head_calls = 0
        for row in candidates:
            result = resolve_link(
                client, row["url"], row["source"], min(4, 12 - head_calls)
            )
            calls += result["calls"]
            head_calls += result["calls"]
            if not result["url"]:
                excluded["link_" + result["status"]] += 1
                if result["status"] in {
                    "network_error",
                    "http_429",
                    "http_500",
                    "http_503",
                    "request_budget_exhausted",
                    "redirect_limit",
                }:
                    errors.append("link_" + result["status"])
                continue
            published = datetime.fromtimestamp(row["datetime"], UTC)
            bucket = topic(row["headline"]) or event_bucket(row["headline"])
            event = (
                bucket + ":" + published.date().isoformat()
                if bucket
                else "title:" + title_key(row["headline"], row["source"])
            )
            items.append(
                NewsItem(
                    provider="Finnhub",
                    kind="link",
                    source_id=str(row["id"]),
                    url=result["url"],
                    title=row["headline"],
                    publisher=row["source"],
                    published_at=published,
                    retrieved_at=retrieved,
                    content_version=digest(row["headline"] + result["url"]),
                    event_key=event,
                    permission_reference="finnhub_personal_use:2026-11-03",
                )
            )
        if excluded["invalid_row"]:
            errors.append("invalid_rows")
        return SourceResult(
            provider="Finnhub",
            status="partial" if errors else "complete",
            items=tuple(items),
            requests=calls,
            errors=tuple(sorted(set(errors))),
            excluded=dict(excluded),
        )
    except (httpx.HTTPError, ValueError, TypeError, OverflowError) as exc:
        code = str(exc) if isinstance(exc, NewsError) else "transport_or_schema"
        return SourceResult(
            provider="Finnhub", status="failed", requests=1, errors=(code,)
        )


def summarize(item, *, client, store, limits: GenerationLimits, now):
    """검증된 공식 사실의 문형을 AI가 반환한 뒤 source/version/span/text를 전부 대조."""
    item = NewsItem.model_validate_json(item.model_dump_json())
    now = aware(now)
    limits = GenerationLimits.model_validate_json(limits.model_dump_json())
    if item.kind != "official" or not item.facts:
        raise NewsError("general_news_ai_forbidden")
    if item.retrieved_at > now or limits.prices_valid_until <= now:
        raise NewsError("generation_time_or_prices_invalid")
    payload = json.dumps(
        {
            "source_id": item.source_id,
            "content_version": item.content_version,
            "instruction": "각 claim의 allowed_texts 중 하나만 반환하고 claim_id와 evidence_span을 보존한다. 외부 지식·인과·예측·투자 권유를 추가하지 않는다.",
            "claims": [f.model_dump(mode="json") for f in item.facts],
        },
        ensure_ascii=False,
    )
    if estimate_input_tokens(payload) > limits.max_input_tokens:
        raise NewsError("input_budget_exceeded")
    from uuid import uuid4

    request_id = str(uuid4())
    store.reserve(request_id, limits, now)
    try:
        response = GenerationResponse.model_validate(
            client.generate(
                model=limits.model,
                input_json=payload,
                max_output_tokens=limits.max_output_tokens,
                max_input_tokens=limits.max_input_tokens,
            )
        )
    except Exception:  # noqa: BLE001 - 제공처 예외에 원문/비밀이 있을 수 있어 고정 코드만 남긴다.
        store.fail(request_id, "GENERATION_RESULT_UNKNOWN", now)
        raise NewsError("generation_result_unknown") from None
    if (
        response.input_tokens > limits.max_input_tokens
        or response.output_tokens > limits.max_output_tokens
    ):
        store.fail(request_id, "USAGE_EXCEEDS_RESERVED_MAXIMUM", now)
        raise NewsError("usage_exceeds_reserved_maximum")
    store.finish(
        request_id,
        limits.cost(response.input_tokens, response.output_tokens),
        None,
        None,
        None,
        now,
    )
    output = response.output
    if (output.source_id, output.content_version) != (
        item.source_id,
        item.content_version,
    ) or len(output.claims) != len(item.facts):
        store.fail(request_id, "SUMMARY_SOURCE_OR_CLAIMS_MISMATCH", now)
        raise NewsError("summary_source_or_claims_mismatch")
    for claim, fact in zip(output.claims, item.facts, strict=True):
        if (
            claim.claim_id != fact.claim_id
            or claim.evidence_span != fact.evidence_span
            or claim.text_ko not in fact.allowed_texts
        ):
            store.fail(request_id, "SUMMARY_FACTS_MISMATCH", now)
            raise NewsError("summary_facts_mismatch")
    return NewsItem.model_validate(
        item.model_dump() | {"summary_ko": " ".join(c.text_ko for c in output.claims)}
    )


def integrate(
    sources,
    *,
    as_of,
    finished_at,
    run_id,
    seen_keys=(),
    last_success=None,
    summary=None,
):
    as_of, finished_at = aware(as_of), aware(finished_at)
    if as_of > finished_at or (
        last_success is not None and aware(last_success) > as_of
    ):
        raise NewsError("invalid_collection_times")
    if len(sources) != 4 or {s.provider for s in sources} != set(PROVIDERS):
        raise NewsError("required_sources_missing")
    lower = as_of - timedelta(hours=96)
    seen, excluded, eligible = set(seen_keys), Counter(), []
    for source in sources:
        for item in source.items:
            if (
                item.provider != source.provider
                or not lower <= item.published_at <= as_of
                or item.retrieved_at > finished_at
            ):
                excluded["outside_window_or_source_time"] += 1
                continue
            if (
                last_success
                and item.published_at < as_of - timedelta(hours=24)
                and item.published_at <= aware(last_success)
            ):
                excluded["before_last_success"] += 1
                continue
            eligible.append(item)
    # 24h 우선, 동일 사건에서는 공식 발표 우선, 이후 최신순·안정 ID.
    eligible.sort(
        key=lambda i: (
            i.published_at < as_of - timedelta(hours=24),
            i.kind != "official",
            -i.published_at.timestamp(),
            i.source_id,
        )
    )
    selected, summary_failed = [], False
    for item in eligible:
        if len(selected) == 3:
            excluded["selection_limit"] += 1
            continue
        if seen.intersection(item.keys):
            excluded["already_sent_or_duplicate"] += 1
            continue
        if item.kind == "official":
            if summary is None:
                excluded["summary_not_configured"] += 1
                summary_failed = True
                continue
            try:
                item = summary(item)
                if not item.summary_ko:
                    raise NewsError("summary_missing")
            except (NewsError, ValueError):
                excluded["summary_failed"] += 1
                summary_failed = True
                continue
        seen.update(item.keys)
        selected.append(item)
    successes = sum(s.status != "failed" for s in sources)
    status = (
        "failed"
        if not successes
        else (
            "complete"
            if all(s.status == "complete" for s in sources) and not summary_failed
            else "partial"
        )
    )
    return NewsResult(
        run_id=run_id,
        as_of=as_of,
        finished_at=finished_at,
        status=status,
        sources=tuple(sources),
        selected=tuple(selected),
        excluded=dict(excluded),
    )


def collect(
    client,
    *,
    api_key,
    as_of,
    clock=lambda: datetime.now(UTC),
    seen_keys=(),
    last_success=None,
    summary=None,
):
    from uuid import uuid4

    from xfolio.official_releases import collect_official

    as_of = aware(as_of)
    sources = [collect_finnhub(client, api_key=api_key, as_of=as_of, clock=clock)]
    sources.extend(
        collect_official(client, provider=p, as_of=as_of, clock=clock)
        for p in PROVIDERS[1:]
    )
    result = integrate(
        sources,
        as_of=as_of,
        finished_at=clock(),
        run_id=str(uuid4()),
        seen_keys=seen_keys,
        last_success=last_success,
        summary=summary,
    )
    return NewsResult.model_validate(
        result.model_dump() | {"finished_at": aware(clock())}
    )
