"""Marketaux를 수집하되 텍스트는 메모리에만 두고 공개 이용을 활성화하지 않는다."""

import logging
import re
import time
from contextlib import contextmanager, nullcontext
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qsl, quote, quote_plus, urlsplit
from uuid import UUID

import httpx
from pydantic import ValidationError

from xfolio.news_models import NewsArticle, NewsCollection, NewsQueryReport
from xfolio.news_queries import FOCUSED_QUERIES, NewsQuery

ENDPOINT = "https://api.marketaux.com/v1/news/all"
MIN_REQUEST_INTERVAL_SECONDS = 3.0
SAFE_LIMIT_HEADERS = (
    "x-usagelimit-limit",
    "x-usagelimit-remaining",
    "x-ratelimit-limit",
    "x-ratelimit-remaining",
)


class NewsCollectionError(ValueError):
    """외부 요청 전에 거부한 설정 오류. 메시지는 고정 코드다."""


class _StopCollection(Exception):
    pass


class _CredentialLogFilter(logging.Filter):
    def __init__(self, token):
        super().__init__()
        self.needles = {
            value.casefold()
            for value in (token, quote(token, safe=""), quote_plus(token))
        }

    def filter(self, record):
        if not any(
            record.name == name or record.name.startswith(name + ".")
            for name in ("httpx", "httpcore")
        ):
            return True
        message = record.getMessage().casefold()
        return "api_token" not in message and not any(
            value in message for value in self.needles
        )


@contextmanager
def _without_credential_logs(token):
    """로거 레벨은 유지하고 수집 범위의 인증 URL·키 로그만 버린다."""
    for name in ("httpx", "httpcore"):
        logging.getLogger(name)
    loggers = [
        logger
        for name, logger in logging.Logger.manager.loggerDict.items()
        if isinstance(logger, logging.Logger)
        and any(
            name == prefix or name.startswith(prefix + ".")
            for prefix in ("httpx", "httpcore")
        )
    ]
    # Parent logger filters do not inspect propagated child records; handlers do.
    targets = {
        *loggers,
        *(
            handler
            for logger in (*loggers, logging.getLogger())
            for handler in logger.handlers
        ),
    }
    guard = _CredentialLogFilter(token)
    for target in targets:
        target.addFilter(guard)
    try:
        yield
    finally:
        for target in targets:
            target.removeFilter(guard)


class _Requester:
    def __init__(self, client, token, budget, clock, sleep):
        self.client, self.token, self.budget = client, token, budget
        self.clock, self.sleep = clock, sleep
        self.requests, self.last_started = 0, None

    def fetch(self, params, page, report):
        if self.requests >= self.budget:
            raise _StopCollection("request_budget")
        if self.last_started is not None:
            while (
                delay := self.last_started + MIN_REQUEST_INTERVAL_SECONDS - self.clock()
            ) > 0:
                self.sleep(delay)
        self.last_started = self.clock()
        self.requests += 1
        report["requests"] += 1
        try:
            response = self.client.get(
                ENDPOINT,
                params={**params, "page": page, "api_token": self.token},
                timeout=15,
                follow_redirects=False,
            )
        except httpx.RequestError:
            raise _StopCollection("transport_error") from None
        report["responses"].append(
            {
                "status_code": response.status_code,
                "limit_headers": {
                    name: value
                    for name in SAFE_LIMIT_HEADERS
                    if (value := response.headers.get(name)) is not None
                    and re.fullmatch(r"[0-9]+", value)
                    and self.token not in value
                },
            }
        )
        if response.status_code != 200:
            raise _StopCollection(
                {402: "daily_request_limit", 429: "rate_limit_60_seconds"}.get(
                    response.status_code, "http_error"
                )
            )
        try:
            payload = response.json()
        except ValueError:
            raise _StopCollection("invalid_payload") from None
        if not isinstance(payload, dict) or any(
            payload.get(k) is not None for k in ("error", "errors")
        ):
            raise _StopCollection("invalid_payload")
        meta, data = payload.get("meta"), payload.get("data")
        if not isinstance(meta, dict) or not isinstance(data, list):
            raise _StopCollection("invalid_payload")
        if any(
            type(meta.get(k)) is not int or meta[k] < 0
            for k in ("found", "returned", "limit", "page")
        ):
            raise _StopCollection("invalid_pagination")
        if (
            meta["page"] != page
            or meta["limit"] != 3
            or meta["returned"] != len(data)
            or len(data) > 3
            or meta["found"] < (page - 1) * 3 + len(data)
        ):
            raise _StopCollection("invalid_pagination")
        report["pages"].append(
            {k: meta[k] for k in ("found", "returned", "limit", "page")}
        )
        return meta, data


def _article(item, token):
    if not isinstance(item, dict):
        raise _StopCollection("invalid_article")
    values = {
        key: item.get(key)
        for key in (
            "uuid",
            "title",
            "description",
            "snippet",
            "source",
            "url",
            "published_at",
        )
    }
    if any(token in value for value in values.values() if isinstance(value, str)):
        raise _StopCollection("credential_echo")
    try:
        if not isinstance(values["uuid"], str):
            raise TypeError
        values["uuid"] = str(UUID(values["uuid"]))
        url = urlsplit(values["url"])
        if (
            url.username
            or url.password
            or any(
                k.lower()
                in {"api_token", "api_key", "apikey", "token", "authorization"}
                for k, _ in parse_qsl(url.query)
            )
        ):
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        raise _StopCollection("invalid_article") from None
    published = values["published_at"]
    try:
        published = (
            datetime.fromisoformat(published) if isinstance(published, str) else None
        )
    except ValueError:
        published = None
    if published is None or published.utcoffset() is None:
        return None
    try:
        return NewsArticle(
            article_id=values["uuid"],
            title=values["title"],
            source=values["source"],
            url=values["url"],
            description=values["description"]
            if values["description"] is not None
            else "",
            snippet=values["snippet"] if values["snippet"] is not None else "",
            published_at=published,
            retrieved_at=datetime.now(UTC),
        )
    except ValidationError:
        raise _StopCollection("invalid_article") from None


def _collect_query(requester, query, start, end, max_pages, report, articles):
    params = {
        "search": query.search,
        "language": "en",
        "limit": 3,
        "sort": "published_at",
        "group_similar": "false",
        "published_after": start.isoformat().removesuffix("+00:00"),
        "published_before": end.isoformat().removesuffix("+00:00"),
    }
    if query.domains:
        params["domains"] = ",".join(query.domains)
    if query.symbols:
        params.update(symbols=",".join(query.symbols), filter_entities="true")
    local_ids, issue, first_found = set(), None, None
    for page in range(1, max_pages + 1):
        if requester.requests >= requester.budget:
            return "request_budget"
        meta, data = requester.fetch(params, page, report)
        if first_found is None:
            first_found = meta["found"]
        elif first_found != meta["found"]:
            issue = "pagination_changed"
        for item in data:
            article = _article(item, requester.token)
            if article is None:
                issue = issue or "invalid_publication_time"
                continue
            if not start <= article.published_at <= end:
                issue = issue or "article_outside_window"
                continue
            if article.article_id in local_ids:
                issue = issue or "duplicate_page"
            local_ids.add(article.article_id)
            previous = articles.get(article.article_id)
            if previous is not None and previous.model_dump(
                exclude={"retrieved_at"}
            ) != article.model_dump(exclude={"retrieved_at"}):
                issue = issue or "article_conflict"
            else:
                articles.setdefault(article.article_id, article)
        if page * 3 >= max(first_found, meta["found"]) or not data:
            if len(local_ids) != first_found:
                issue = issue or "invalid_pagination"
            return issue
    return issue or "page_budget"


def _validate(start, end, queries, token, max_requests, max_pages):
    if (
        not isinstance(start, datetime)
        or not isinstance(end, datetime)
        or start.utcoffset() is None
        or end.utcoffset() is None
    ):
        raise NewsCollectionError("timezone_required")
    start, end = start.astimezone(UTC), end.astimezone(UTC)
    if start >= end or end - start > timedelta(days=7) or end > datetime.now(UTC):
        raise NewsCollectionError("invalid_time_window")
    if not isinstance(token, str) or not token.strip():
        raise NewsCollectionError("missing_api_token")
    token = token.strip()
    if any(type(v) is not int or v < 1 for v in (max_requests, max_pages)):
        raise NewsCollectionError("invalid_request_limits")
    try:
        queries = tuple(queries)
    except TypeError:
        raise NewsCollectionError("invalid_query") from None
    if not queries or any(not isinstance(q, NewsQuery) for q in queries):
        raise NewsCollectionError("invalid_query")
    ids = set()
    for query in queries:
        if not isinstance(query.domains, tuple) or not isinstance(query.symbols, tuple):
            raise NewsCollectionError("invalid_query")
        fields = (query.query_id, query.search, *query.domains, *query.symbols)
        if (
            any(not isinstance(v, str) or not v.strip() or token in v for v in fields)
            or query.query_id in ids
        ):
            raise NewsCollectionError("invalid_query")
        ids.add(query.query_id)
    return start, end, queries, token


def collect_news(
    *,
    start,
    end,
    queries=FOCUSED_QUERIES,
    token=None,
    max_requests=12,
    max_pages=5,
    client: httpx.Client | None = None,
    clock=None,
    sleep=None,
) -> NewsCollection:
    """정의한 검색 범위를 수집한다. complete는 전체 시장 보도 완전성을 뜻하지 않는다."""
    start, end, queries, token = _validate(
        start, end, queries, token, max_requests, max_pages
    )
    articles, reports, error, failed = {}, [], None, False
    manager = (
        nullcontext(client)
        if client is not None
        else httpx.Client(
            timeout=15, follow_redirects=False, transport=httpx.HTTPTransport(retries=0)
        )
    )
    with _without_credential_logs(token), manager as http:
        requester = _Requester(
            http, token, max_requests, clock or time.monotonic, sleep or time.sleep
        )
        for query in queries:
            report = {
                "query_id": query.query_id,
                "search": query.search,
                "domains": query.domains,
                "symbols": query.symbols,
                "status": "skipped",
                "requests": 0,
                "pages": [],
                "responses": [],
                "error": None,
            }
            reports.append(report)
            if failed:
                continue
            if requester.requests >= max_requests:
                report["error"] = "request_budget"
                error = error or "request_budget"
                continue
            try:
                issue = _collect_query(
                    requester, query, start, end, max_pages, report, articles
                )
                report.update(status="partial" if issue else "complete", error=issue)
                error = error or issue
            except _StopCollection as exc:
                code = str(exc)
                report.update(status="failed", error=code)
                error, failed = code, True
    return NewsCollection(
        status="failed" if failed else "partial" if error else "complete",
        window_start=start,
        window_end=end,
        collected_at=datetime.now(UTC),
        articles=tuple(articles.values()),
        requests=requester.requests,
        query_reports=tuple(
            NewsQueryReport.model_validate(report) for report in reports
        ),
        error=error,
    )


def metadata_report(collection: NewsCollection) -> dict:
    """기사 텍스트·인증정보를 제외한 명시적 허용 필드만 반환한다."""
    return {
        "provider": "Marketaux",
        "status": collection.status,
        "window_start": collection.window_start.isoformat(),
        "window_end": collection.window_end.isoformat(),
        "collected_at": collection.collected_at.isoformat(),
        "requests": collection.requests,
        "checkpoint_eligible": collection.checkpoint_eligible,
        "error": collection.error,
        "min_request_interval_seconds": MIN_REQUEST_INTERVAL_SECONDS,
        "max_retries": 0,
        "query_reports": [
            {
                **report.model_dump(mode="json", exclude={"pages", "responses"}),
                "pages": [
                    {
                        key: value
                        for key in ("found", "returned", "page", "limit")
                        if type(value := page.get(key)) is int and value >= 0
                    }
                    for page in report.pages
                ],
                "responses": [
                    {
                        "status_code": row.get("status_code"),
                        "limit_headers": {
                            key: value
                            for key in SAFE_LIMIT_HEADERS
                            if isinstance(headers := row.get("limit_headers"), dict)
                            and isinstance(value := headers.get(key), str)
                            and re.fullmatch(r"[0-9]+", value)
                        },
                    }
                    for row in report.responses
                ],
            }
            for report in collection.query_reports
        ],
        "articles": [
            {
                "provider": a.provider,
                "article_id": a.article_id,
                "source": a.source,
                "url": str(a.url),
                "published_at": a.published_at.isoformat(),
                "retrieved_at": a.retrieved_at.isoformat(),
                "field_lengths": {
                    "title": len(a.title),
                    "description": len(a.description),
                    "snippet": len(a.snippet),
                },
            }
            for a in collection.articles
        ],
    }
