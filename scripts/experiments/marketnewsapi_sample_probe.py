"""Collect a bounded MarketNewsAPI sample without saving article text or secrets."""

import argparse
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

import httpx

ENDPOINT = "https://api.marketnewsapi.com/v1/news"
SYMBOLS = ("NVDA", "AAPL", "MSFT")
TYPES = ("press_release", "news")


class ProbeError(Exception):
    """A safe error that excludes keys and article response bodies."""


def _timestamp(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return (
        parsed.astimezone(UTC).isoformat() if parsed.utcoffset() is not None else None
    )


def _article_metadata(item, *, symbol, kind):
    if not isinstance(item, dict) or not isinstance(item.get("id"), str):
        raise ProbeError("schema: invalid article id")
    url = item.get("url")
    if (
        not isinstance(url, str)
        or urlsplit(url).scheme not in ("http", "https")
        or not urlsplit(url).netloc
    ):
        raise ProbeError("schema: invalid article URL")
    source = item.get("source")
    if not isinstance(source, dict) or not isinstance(source.get("name"), str):
        raise ProbeError("schema: invalid article source")
    tickers = item.get("tickers")
    if not isinstance(tickers, list) or not all(
        isinstance(value, str) for value in tickers
    ):
        raise ProbeError("schema: invalid article tickers")
    fields = {}
    for name in ("title", "snippet", "summary", "body"):
        value = item.get(name)
        if value is not None and not isinstance(value, str):
            raise ProbeError(f"schema: invalid {name}")
        fields[f"{name}_chars"] = len(value or "")
    return {
        "id": item["id"],
        "url": url,
        "source": source["name"],
        "type": item.get("type"),
        "published_at_utc": _timestamp(item.get("published_at")),
        "ingested_at_utc": _timestamp(item.get("ingested_at")),
        "tickers": tickers,
        "query_symbol": symbol,
        "query_type": kind,
        "symbol_tag_matches": symbol in tickers,
        "type_matches": item.get("type") == kind,
        **fields,
    }


def probe(*, run=False, key=None, limit=3, days=90, now=None, transport=None):
    if not 1 <= limit <= 5 or not 1 <= days <= 365:
        raise ProbeError("config: limit 1..5 and days 1..365 required")
    as_of = now or datetime.now(UTC)
    if as_of.utcoffset() is None:
        raise ProbeError("config: timezone-aware reference time required")
    as_of = as_of.astimezone(UTC)
    start = as_of - timedelta(days=days)
    result = {
        "mode": "run" if run else "dry_run",
        "as_of_utc": as_of.isoformat(),
        "from_utc": start.isoformat(),
        "max_requests": len(SYMBOLS) * len(TYPES),
        "sample_status": "first_page_only",
        "article_text_saved": False,
        "queries": [],
    }
    if run and not key:
        raise ProbeError("config: MARKETNEWSAPI_KEY required with --run")
    with httpx.Client(
        transport=transport, timeout=15, follow_redirects=False
    ) as client:
        for symbol in SYMBOLS:
            for kind in TYPES:
                params = {
                    "tickers": symbol,
                    "type": kind,
                    "from": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "to": as_of.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "limit": limit,
                }
                query = {"symbol": symbol, "type": kind, "params": params}
                result["queries"].append(query)
                if not run:
                    continue
                try:
                    response = client.get(
                        ENDPOINT,
                        params=params,
                        headers={"Authorization": f"Bearer {key}"},
                    )
                except httpx.RequestError:
                    raise ProbeError(
                        f"request: {symbol}/{kind} transport failure"
                    ) from None
                if response.status_code != 200:
                    raise ProbeError(
                        f"http: {symbol}/{kind} status {response.status_code}"
                    )
                try:
                    payload = response.json()
                except ValueError:
                    raise ProbeError(f"schema: {symbol}/{kind} invalid JSON") from None
                if not isinstance(payload, dict):
                    raise ProbeError(f"schema: {symbol}/{kind} invalid envelope")
                data, meta = payload.get("data"), payload.get("meta")
                if not isinstance(data, list) or not isinstance(meta, dict):
                    raise ProbeError(f"schema: {symbol}/{kind} invalid envelope")
                query["response"] = {
                    "returned": len(data),
                    "count": meta.get("count"),
                    "plan": meta.get("plan"),
                    "delayed_minutes": meta.get("delayed_minutes"),
                    "has_next_cursor": bool(meta.get("next_cursor")),
                    "articles": [
                        _article_metadata(item, symbol=symbol, kind=kind)
                        for item in data
                    ],
                }
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        result = probe(
            run=args.run,
            key=os.getenv("MARKETNEWSAPI_KEY"),
            limit=args.limit,
            days=args.days,
        )
    except ProbeError as exc:
        parser.exit(1, f"{exc}\n")
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
