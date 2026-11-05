"""Exa 단일 API 수집기. 본문은 메모리에서만 유지하고 충분성을 추정하지 않는다."""

import json
import re
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from urllib.parse import quote, quote_plus, urlsplit

import httpx
from pydantic import (
    AwareDatetime,
    Field,
    SecretStr,
    TypeAdapter,
    ValidationError,
    model_validator,
)

from xfolio.news.collector import _without_credential_logs
from xfolio.news.contracts import digest
from xfolio.news.input import (
    ContentEvidence,
    Identifier,
    InputContract,
    InputRights,
    NewsInput,
    NewsInputCollection,
    PublicationTime,
    ScopeReport,
)

ADAPTER_VERSION = "exa_v1"


class ExaError(ValueError):
    """비밀이나 외부 응답을 포함하지 않는 오류 코드."""


class ExaQuery(InputContract):
    query_id: Identifier
    query: Identifier
    include_domains: tuple[Identifier, ...] = ()
    exclude_domains: tuple[Identifier, ...] = ()

    @model_validator(mode="after")
    def domains_only(self):
        if any(
            not re.fullmatch(r"[A-Za-z0-9.-]+", d)
            for d in (*self.include_domains, *self.exclude_domains)
        ):
            raise ValueError("invalid_domain")
        if set(self.include_domains) & set(self.exclude_domains):
            raise ValueError("conflicting_domains")
        return self


class ExaConfig(InputContract):
    query_version: Identifier = "us_morning_v1"
    queries: tuple[ExaQuery, ...] = (
        ExaQuery(
            query_id="market",
            query="US stock market major developments and market moving news",
        ),
        ExaQuery(
            query_id="sector",
            query="US industry sectors major business and policy developments",
        ),
        ExaQuery(
            query_id="companies",
            query="NVIDIA Apple Microsoft Amazon Alphabet Meta Tesla JPMorgan Johnson & Johnson ExxonMobil earnings acquisitions and other major US company developments",
        ),
    )
    num_results: int = Field(default=5, ge=1, le=10, strict=True)
    max_characters: int = Field(default=20000, ge=100, le=20000, strict=True)
    max_requests: int = Field(default=6, ge=1, le=12, strict=True)
    max_response_cost_usd: Decimal = Field(
        default=Decimal("0.10"), gt=0, allow_inf_nan=False
    )
    request_cost_reserve_usd: Decimal = Field(
        default=Decimal("0.02"), gt=0, allow_inf_nan=False
    )

    @model_validator(mode="after")
    def valid_queries(self):
        if not self.queries or len({q.query_id for q in self.queries}) != len(
            self.queries
        ):
            raise ValueError("invalid_query_set")
        if self.request_cost_reserve_usd > self.max_response_cost_usd:
            raise ValueError("invalid_cost_reserve")
        return self

    @property
    def fingerprint(self):
        values = self.model_dump(
            mode="json", include={"queries", "num_results", "max_characters"}
        )
        return digest(json.dumps(values, sort_keys=True, separators=(",", ":")))


class ExaResult(InputContract):
    configuration: ExaConfig
    collection: NewsInputCollection


def require_collection_rights(rights, now):
    if not rights.allows("collection", now=now):
        raise ExaError("collection_not_permitted")


def _publication(raw):
    if raw is None:
        return PublicationTime()
    if not isinstance(raw, str):
        raise ExaError("invalid_publication_time")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        # 날짜형은 UTC 자정으로 만들지 않는다.
        date.fromisoformat(raw)
        return PublicationTime(raw=raw, precision="date")
    value = TypeAdapter(AwareDatetime).validate_python(raw)
    return PublicationTime(
        raw=raw, value=value, timezone=str(value.tzinfo), precision="unknown"
    )


def _record(item, *, run_id, received_at, config, rights, synthetic):
    if not isinstance(item, dict):
        raise ExaError("invalid_payload")
    url = item.get("url")
    if (
        not isinstance(url, str)
        or not isinstance(item.get("id"), str)
        or not item["id"].strip()
    ):
        raise ExaError("invalid_payload")
    text = item.get("text")
    if text is not None and not isinstance(text, str):
        raise ExaError("invalid_payload")
    if text is not None and len(text) > config.max_characters:
        raise ExaError("invalid_payload")
    publication = _publication(item.get("publishedDate"))
    if publication.value and publication.value > received_at:
        raise ExaError("invalid_publication_time")
    content_hash = digest(text) if text else None
    return NewsInput(
        input_id=digest(json.dumps([url, content_hash, publication.raw])),
        source_id="exa",
        source_record_id=item["id"],
        source_url=url,
        publisher=urlsplit(url).hostname or "unknown",
        document_type="unknown",
        publication=publication,
        retrieved_at=received_at,
        available_at=received_at if text else None,
        last_checked_at=received_at,
        collection_run_id=run_id,
        content=ContentEvidence(
            text=text or None,
            text_chars=len(text or ""),
            title_only=bool(
                text
                and isinstance(item.get("title"), str)
                and text.strip() == item["title"].strip()
            ),
            requested_max_chars=config.max_characters,
            truncation="detected"
            if text and len(text) >= config.max_characters
            else "unknown",
        ),
        content_hash=content_hash,
        source_revision=content_hash,
        revision_kind="content_hash" if content_hash else "unknown",
        data_origin="synthetic_fixture" if synthetic else "live_capture",
        synthetic=synthetic,
        rights=rights,
    )


class _Requester:
    def __init__(self, client, key, config):
        self.client, self.key, self.config = client, key, config
        self.requests, self.cost, self.stopped = 0, Decimal(0), False

    def post(self, endpoint, body):
        if self.stopped or self.requests >= self.config.max_requests:
            return None, None, "request_budget", 0
        if (
            self.cost + self.config.request_cost_reserve_usd
            > self.config.max_response_cost_usd
        ):
            self.stopped = True
            return None, None, "cost_budget", 0
        self.requests += 1
        try:
            with _without_credential_logs(self.key):
                response = self.client.post(
                    "https://api.exa.ai/" + endpoint,
                    json=body,
                    headers={"x-api-key": self.key},
                    timeout=20,
                    follow_redirects=False,
                )
        except httpx.RequestError:
            self.stopped = True
            return None, None, "transport_error", 1
        if response.status_code != 200:
            if response.status_code in {401, 402, 403, 429}:
                self.stopped = True
            return (
                None,
                None,
                "rate_limit" if response.status_code == 429 else "http_error",
                1,
            )
        try:
            if any(
                secret in response.text
                for secret in (self.key, quote(self.key, safe=""), quote_plus(self.key))
            ):
                self.stopped = True
                return None, None, "credential_echo", 1
            data = response.json()
            decoded = json.dumps(data, ensure_ascii=False)
            if any(
                secret in decoded
                for secret in (self.key, quote(self.key, safe=""), quote_plus(self.key))
            ):
                self.stopped = True
                return None, None, "credential_echo", 1
            if not isinstance(data, dict) or data.get("error") or data.get("errors"):
                raise ValueError
            raw_cost = data.get("costDollars", {}).get("total")
            if isinstance(raw_cost, bool):
                raise TypeError
            cost = Decimal(str(raw_cost))
            if not cost.is_finite() or cost < 0:
                raise ValueError
        except (ValueError, TypeError, AttributeError, ArithmeticError):
            self.stopped = True
            return (
                data if "data" in locals() and isinstance(data, dict) else None,
                None,
                "cost_unknown",
                1,
            )
        self.cost += cost
        if (
            cost > self.config.request_cost_reserve_usd
            or self.cost > self.config.max_response_cost_usd
        ):
            self.stopped = True
            return data, cost, "cost_budget", 1
        return data, cost, None, 1


def collect_exa(
    *,
    client: httpx.Client,
    api_key: SecretStr,
    rights: InputRights,
    window_start: datetime,
    window_end: datetime,
    run_id: str,
    config: ExaConfig | None = None,
    clock=lambda: datetime.now(UTC),
    synthetic: bool = False,
    previous_records: tuple[NewsInput, ...] = (),
) -> ExaResult:
    """설정한 상위 결과만 수집한다. 호출한 경우만 네트워크가 발생한다."""
    config = config or ExaConfig()
    started = TypeAdapter(AwareDatetime).validate_python(clock()).astimezone(UTC)
    start, end = (
        TypeAdapter(AwareDatetime).validate_python(t).astimezone(UTC)
        for t in (window_start, window_end)
    )
    if (
        not start < end <= started
        or end - start > timedelta(days=7)
        or not run_id.strip()
    ):
        raise ExaError("invalid_collection_window")
    require_collection_rights(rights, started)
    history = {str(r.source_url): r for r in previous_records}
    if len(history) != len(previous_records) or any(
        r.source_id != "exa" or r.synthetic != synthetic for r in previous_records
    ):
        raise ExaError("invalid_previous_records")
    key = api_key.get_secret_value().strip()
    if not key or any(c in key for c in "\r\n"):
        raise ExaError("missing_api_key")
    requester = _Requester(client, key, config)
    required = [f"search:{q.query_id}" for q in config.queries]
    reports, records = [], {}

    def merge(item):
        collision = next(
            (
                r
                for r in records.values()
                if r.source_record_id == item.source_record_id
                and r.source_url != item.source_url
            ),
            None,
        )
        if collision:
            return collision.input_id, "article_conflict"
        previous = records.get(str(item.source_url))
        if previous and (
            (
                previous.content_hash
                and item.content_hash
                and previous.content_hash != item.content_hash
            )
            or previous.publication != item.publication
        ):
            return previous.input_id, "article_conflict"
        if previous and not previous.content_hash and item.content_hash:
            item = NewsInput.model_validate(
                item.model_dump()
                | {"input_id": previous.input_id, "retrieved_at": previous.retrieved_at}
            )
            records[str(item.source_url)] = item
        else:
            records[str(item.source_url)] = previous or item
        return records[str(item.source_url)].input_id, None

    for query in config.queries:
        body = {
            "query": query.query,
            "type": "auto",
            "category": "news",
            "startPublishedDate": start.isoformat(),
            "endPublishedDate": end.isoformat(),
            "numResults": config.num_results,
            "contents": {
                "text": {"maxCharacters": config.max_characters},
                "maxAgeHours": -1,
            },
        }
        if query.include_domains:
            body["includeDomains"] = list(query.include_domains)
        if query.exclude_domains:
            body["excludeDomains"] = list(query.exclude_domains)
        data, cost, error, requests = requester.post("search", body)
        ids, missing, errors = [], [], [error] if error else []
        received = clock()
        results = data.get("results") if data else None
        if not isinstance(results, list) or len(results) > config.num_results:
            errors.append("invalid_payload")
            results = []
        for raw in results:
            try:
                item = _record(
                    raw,
                    run_id=run_id,
                    received_at=received,
                    config=config,
                    rights=rights,
                    synthetic=synthetic,
                )
                host = urlsplit(str(item.source_url)).hostname.lower()

                def matches(domain, host=host):
                    return host == domain.lower() or host.endswith("." + domain.lower())

                if (
                    query.include_domains
                    and not any(matches(d) for d in query.include_domains)
                ) or any(matches(d) for d in query.exclude_domains):
                    raise ExaError("invalid_payload")
                if (
                    item.publication.value
                    and not start <= item.publication.value <= end
                ):
                    raise ExaError("invalid_publication_time")
                key_id, conflict = merge(item)
                ids.append(key_id)
                if conflict:
                    errors.append(conflict)
                if not item.content.text and not conflict:
                    missing.append(str(item.source_url))
            except (ValueError, ValidationError):
                errors.append("invalid_payload")
        reports.append(
            ScopeReport(
                scope_id=f"search:{query.query_id}",
                kind="search",
                status="partial"
                if errors and ids
                else "failed"
                if errors
                else "complete",
                requests=requests,
                input_ids=tuple(dict.fromkeys(ids)),
                error_codes=tuple(dict.fromkeys(errors)),
                response_cost_usd=cost,
            )
        )
        if missing:
            scope_id = f"contents:{query.query_id}"
            required.append(scope_id)
            data, cost, error, requests = requester.post(
                "contents",
                {
                    "urls": list(dict.fromkeys(missing)),
                    "text": {"maxCharacters": config.max_characters},
                    "maxAgeHours": -1,
                },
            )
            errors, ids = [error] if error else [], []
            received = clock()
            statuses = data.get("statuses") if data else None
            results = data.get("results") if data else None
            if not isinstance(statuses, list) or not isinstance(results, list):
                errors.append("content_fetch_failed")
                results, statuses = [], []
            if any(
                not isinstance(r, dict) or r.get("url") not in missing for r in results
            ) or any(
                not isinstance(s, dict) or s.get("id") not in missing for s in statuses
            ):
                errors.append("content_fetch_failed")
            for url in dict.fromkeys(missing):
                matched = [
                    r for r in results if isinstance(r, dict) and r.get("url") == url
                ]
                states = [
                    s for s in statuses if isinstance(s, dict) and s.get("id") == url
                ]
                if (
                    len(matched) != 1
                    or len(states) != 1
                    or states[0].get("status") != "success"
                ):
                    errors.append("content_fetch_failed")
                    continue
                try:
                    old = records[url]
                    raw = matched[0] | {
                        "id": matched[0].get("id", url),
                        "publishedDate": matched[0].get(
                            "publishedDate", old.publication.raw
                        ),
                    }
                    item = _record(
                        raw,
                        run_id=run_id,
                        received_at=received,
                        config=config,
                        rights=rights,
                        synthetic=synthetic,
                    )
                    if (
                        not item.content.text
                        or item.publication != old.publication
                        or item.source_record_id != old.source_record_id
                    ):
                        raise ExaError("content_fetch_failed")
                    item = NewsInput.model_validate(
                        item.model_dump() | {"retrieved_at": old.retrieved_at}
                    )
                    # 이미 다른 검색 scope가 참조한 메타데이터 ID를 유지한다.
                    item = NewsInput.model_validate(
                        item.model_dump() | {"input_id": old.input_id}
                    )
                    records[url] = item
                    ids.append(item.input_id)
                except (ValueError, ValidationError):
                    errors.append("content_fetch_failed")
            reports.append(
                ScopeReport(
                    scope_id=scope_id,
                    kind="contents",
                    status="partial"
                    if errors and ids
                    else "failed"
                    if errors
                    else "complete",
                    requests=requests,
                    input_ids=tuple(dict.fromkeys(ids)),
                    error_codes=tuple(dict.fromkeys(errors)),
                    response_cost_usd=cost,
                )
            )
    for url, item in list(records.items()):
        old = history.get(url)
        if old and old.content_hash and item.content_hash:
            if old.content_hash == item.content_hash:
                conflict = old.publication != item.publication
                records[url] = NewsInput.model_validate(
                    item.model_dump()
                    | {
                        "retrieved_at": old.retrieved_at,
                        "available_at": old.available_at,
                        "is_new_version": conflict,
                        "supersedes": old.input_id if conflict else item.supersedes,
                        "change_reason": "source_publication_metadata_changed"
                        if conflict
                        else item.change_reason,
                    }
                )
                if conflict:
                    reports = [
                        ScopeReport.model_validate(
                            r.model_dump()
                            | {
                                "status": "partial",
                                "error_codes": tuple(
                                    dict.fromkeys((*r.error_codes, "article_conflict"))
                                ),
                            }
                        )
                        if item.input_id in r.input_ids
                        else r
                        for r in reports
                    ]
            else:
                records[url] = NewsInput.model_validate(
                    item.model_dump()
                    | {
                        "supersedes": old.input_id,
                        "change_reason": "source_content_changed",
                    }
                )
    progress = any(r.status != "failed" for r in reports)
    complete = all(r.status == "complete" for r in reports)
    return ExaResult(
        configuration=config,
        collection=NewsInputCollection(
            collection_run_id=run_id,
            source_id="exa",
            adapter_version=ADAPTER_VERSION,
            query_version=config.query_version + ":" + config.fingerprint,
            scope="configured_search_top_results",
            window_start=start,
            window_end=end,
            finished_at=clock(),
            required_scope_ids=tuple(required),
            reports=tuple(reports),
            records=tuple(records.values()),
            status="complete" if complete else "partial" if progress else "failed",
        ),
    )
