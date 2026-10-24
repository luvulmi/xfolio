"""Marketaux 표본 메타데이터 조회. 기본은 dry-run이며 원문·발췌를 저장하지 않는다."""

import argparse
import json
import os
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit
from uuid import UUID

import httpx

ENDPOINT = "https://api.marketaux.com/v1/news/all"
QUERIES = (
    ("macro_policy", '"Federal Reserve"|"interest rate"', None),
    ("macro_indicators", "inflation|CPI|employment|payroll", None),
    ("company_results", "earnings|guidance", "AAPL,MSFT,NVDA"),
    (
        "company_changes",
        'acquisition|merger|contract|"regulatory approval"',
        "AAPL,MSFT,NVDA",
    ),
)


class ProbeError(Exception):
    """토큰이나 응답 본문을 포함하지 않는 조회 실패."""


def article_metadata(item, query, after, before):
    if not isinstance(item, dict):
        raise ProbeError("schema: article must be an object")
    for field in ("uuid", "url", "source"):
        if not isinstance(item.get(field), str) or not item[field].strip():
            raise ProbeError(f"schema: missing/invalid {field}")
    try:
        UUID(item["uuid"])
        url = urlsplit(item["url"])
        if url.scheme not in ("http", "https") or not url.netloc:
            raise ValueError
    except ValueError:
        raise ProbeError("schema: invalid UUID/URL") from None
    states, lengths = {}, {}
    for field in ("title", "description", "snippet"):
        value = item.get(field)
        if value is not None and not isinstance(value, str):
            raise ProbeError(f"schema: invalid {field}")
        states[field] = "present" if value else "missing_or_empty"
        lengths[f"{field}_chars"] = len(value or "")
    published = item.get("published_at")
    try:
        timestamp = datetime.fromisoformat(published)
        if timestamp.utcoffset() is None:
            raise ValueError
        states["published_at"] = (
            "in_window" if after <= timestamp <= before else "outside_window"
        )
    except (AttributeError, TypeError, ValueError):
        timestamp = None
        states["published_at"] = "unknown"
    entities = item.get("entities", [])
    if not isinstance(entities, list) or any(not isinstance(e, dict) for e in entities):
        raise ProbeError("schema: invalid entities")
    selected = []
    for entity in entities:
        if isinstance(entity.get("symbol"), str) and entity["symbol"] in {
            "AAPL",
            "MSFT",
            "NVDA",
        }:
            name = entity.get("name")
            if name is not None and not isinstance(name, str):
                raise ProbeError("schema: invalid entity name")
            selected.append({"symbol": entity["symbol"], "name": name})
    return {
        "uuid": item["uuid"],
        "url": item["url"],
        "source": item["source"],
        "published_at": timestamp.astimezone(UTC).isoformat() if timestamp else None,
        "query": query,
        **lengths,
        "field_states": states,
        "selected_entities": selected,
        "eligible_for_review": states["published_at"] == "in_window",
    }


def probe(*, run=False, token=None, pages=1, days=2, now=None, transport=None):
    if pages not in (1, 2) or not 1 <= days <= 7:
        raise ProbeError("config: pages=1..2 and days=1..7 required")
    before = now or datetime.now(UTC)
    if before.utcoffset() is None:
        raise ProbeError("config: timezone-aware reference time required")
    before = before.astimezone(UTC)
    after = before - timedelta(days=days)
    result = {
        "mode": "run" if run else "dry_run",
        "as_of_utc": before.isoformat(),
        "published_after_utc": after.isoformat(),
        "sample_status": "limited_sample",
        "universe_note": "AAPL/MSFT/NVDA are trial symbols, not a confirmed watchlist",
        "max_requests": len(QUERIES) * pages,
        "queries": [],
        "articles": [],
    }
    if run and not token:
        raise ProbeError("config: MARKETAUX_API_TOKEN is required with --run")
    seen = set()
    with httpx.Client(
        transport=transport, timeout=15, follow_redirects=False
    ) as client:
        for name, search, symbols in QUERIES:
            params = {
                "search": search,
                "language": "en",
                "limit": 3,
                "published_after": after.strftime("%Y-%m-%dT%H:%M:%S"),
                "published_before": before.strftime("%Y-%m-%dT%H:%M:%S"),
                "sort": "published_at",
            }
            if symbols:
                params.update(symbols=symbols, filter_entities="true")
            report = {"query": name, "parameters": params.copy(), "pages": []}
            result["queries"].append(report)
            if not run:
                continue
            for page in range(1, pages + 1):
                try:
                    response = client.get(
                        ENDPOINT, params={**params, "page": page, "api_token": token}
                    )
                except httpx.RequestError:
                    raise ProbeError(
                        f"request: {name} page {page} transport failure"
                    ) from None
                if response.status_code != 200:
                    raise ProbeError(
                        f"http: {name} page {page} status {response.status_code}"
                    )
                try:
                    payload = response.json()
                except ValueError:
                    raise ProbeError("schema: invalid JSON") from None
                if (
                    not isinstance(payload, dict)
                    or payload.get("error")
                    or payload.get("errors")
                ):
                    raise ProbeError("api: invalid response or API error")
                meta, data = payload.get("meta"), payload.get("data")
                if not isinstance(meta, dict) or not isinstance(data, list):
                    raise ProbeError("schema: meta object and data array required")
                if any(
                    type(meta.get(k)) is not int or meta[k] < 0
                    for k in ("found", "returned", "page", "limit")
                ):
                    raise ProbeError("schema: invalid pagination metadata")
                if (
                    meta["page"] != page
                    or meta["limit"] != 3
                    or meta["returned"] != len(data)
                    or len(data) > 3
                    or meta["found"] < (page - 1) * 3 + len(data)
                ):
                    raise ProbeError("schema: inconsistent pagination metadata")
                report["pages"].append(
                    {k: meta[k] for k in ("found", "returned", "page", "limit")}
                )
                for item in data:
                    article = article_metadata(item, name, after, before)
                    if article["uuid"] in seen:
                        matches = next(
                            a
                            for a in result["articles"]
                            if a["uuid"] == article["uuid"]
                        )["matched_queries"]
                        if name not in matches:
                            matches.append(name)
                    else:
                        seen.add(article["uuid"])
                        result["articles"].append(
                            {**article, "matched_queries": [name]}
                        )
                incomplete = page * 3 < meta["found"]
                report.update(incomplete=incomplete, zero_results=meta["found"] == 0)
                if not incomplete or not data:
                    break

    # 응답 메타데이터가 우연히 토큰을 포함하더라도 표준 출력에서 제거한다.
    def redact(value):
        if isinstance(value, str):
            return value.replace(token, "[REDACTED]") if token else value
        if isinstance(value, list):
            return [redact(item) for item in value]
        if isinstance(value, dict):
            return {key: redact(item) for key, item in value.items()}
        return value

    return redact(result)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--pages", type=int, choices=(1, 2), default=1)
    parser.add_argument("--days", type=int, choices=range(1, 8), default=2)
    args = parser.parse_args(argv)
    try:
        result = probe(
            run=args.run,
            token=os.environ.get("MARKETAUX_API_TOKEN"),
            pages=args.pages,
            days=args.days,
        )
    except ProbeError as exc:
        parser.exit(1, f"Marketaux probe failed: {exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
