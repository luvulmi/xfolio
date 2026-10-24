"""좁힌 질의의 고정 아침 창과 최근 표본. GET 최대12회, 3초 간격, 기본 dry-run."""

import argparse
import importlib.util
import json
import os
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

from xfolio.news_queries import FOCUSED_QUERIES

SPEC = importlib.util.spec_from_file_location(
    "marketaux_experiment", Path(__file__).with_name("marketaux_incremental_probe.py")
)
helper = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(helper)
ProbeError = helper.ProbeError


def redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[REDACTED]") if token else value
    if isinstance(value, list):
        return [redact(item, token) for item in value]
    if isinstance(value, dict):
        return {key: redact(item, token) for key, item in value.items()}
    return value


def probe(
    *,
    run=False,
    token=None,
    now=None,
    transport=None,
    clock=None,
    sleep=None,
    review_callback=None,
):
    reference = now or datetime.now(UTC)
    if reference.utcoffset() is None:
        raise ProbeError("config: reference timezone required")
    reference = reference.astimezone(UTC).replace(microsecond=0)
    fixed_end = datetime(2026, 10, 22, 22, 30, tzinfo=UTC)
    if not fixed_end <= reference <= fixed_end + timedelta(days=6):
        raise ProbeError(
            "config: fixed replay is outside this experiment's seven-day scope"
        )
    if run and not token:
        raise ProbeError("config: MARKETAUX_API_TOKEN required with --run")
    result = {
        "mode": "run" if run else "dry_run",
        "as_of_utc": reference.isoformat(),
        "state": "dry_run",
        "request_cap": 12,
        "request_count": 0,
        "min_request_interval_seconds": 3,
        "checkpoint_advance": False,
        "fixed_window_checkpoint_eligible": False,
        "cursor_written": False,
        "sample_status": "limited_sample",
        "queries": [],
        "requests": [],
        "articles": [],
        "limitations": [
            "historical retrieval is not live collection or proof of pre-briefing availability",
            "zero on a day without US announcements does not establish reliable coverage",
            "domain/ticker restrictions can omit relevant articles",
            "UUID deduplication does not identify the same event across different UUIDs",
            "description/snippet presence is not evidence sufficiency or publication permission",
        ],
    }
    for scope, after, before in (
        ("fixed_morning", fixed_end - timedelta(days=1, minutes=1), fixed_end),
        ("recent_five_days_first_page", reference - timedelta(days=5), reference),
    ):
        for query in FOCUSED_QUERIES:
            params = {
                "search": query.search,
                "language": "en",
                "limit": 3,
                "sort": "published_at",
                "group_similar": "false",
                "published_after": after.strftime("%Y-%m-%dT%H:%M:%S"),
                "published_before": before.strftime("%Y-%m-%dT%H:%M:%S"),
                "domains": ",".join(query.domains),
            }
            if query.symbols:
                params.update(symbols=",".join(query.symbols), filter_entities="true")
            result["queries"].append(
                {
                    "scope": scope,
                    "query_id": query.query_id,
                    "parameters": params,
                    "state": "planned",
                    "checkpoint_advance": False,
                    "pages": [],
                    "unique_uuids": 0,
                    "duplicate_uuids": 0,
                }
            )
    if not run:
        return result
    pacer = helper.RequestPacer(clock or time.monotonic, sleep or time.sleep)
    counter, seen, current = [0, 12], {}, None
    with httpx.Client(
        transport=transport, timeout=15, follow_redirects=False
    ) as client:
        try:
            for current in result["queries"]:
                if counter[0] >= 12:
                    current.update(state="skipped", reason="request_budget_exhausted")
                    continue
                params = current["parameters"]
                after = datetime.fromisoformat(params["published_after"]).replace(
                    tzinfo=UTC
                )
                before = datetime.fromisoformat(params["published_before"]).replace(
                    tzinfo=UTC
                )
                ids, valid_times = set(), True
                page_cap = 12 if current["scope"] == "fixed_morning" else 1
                for page in range(1, page_cap + 1):
                    if counter[0] >= 12:
                        break
                    meta, data = helper.fetch_page(
                        client, params, token, page, counter, pacer, result["requests"]
                    )
                    current["pages"].append(meta)
                    for item in data:
                        article = helper.metadata.article_metadata(
                            item, current["query_id"], after, before
                        )
                        valid_times &= article["eligible_for_review"]
                        uuid = article["uuid"]
                        if uuid in ids:
                            current["duplicate_uuids"] += 1
                        ids.add(uuid)
                        match = {
                            "scope": current["scope"],
                            "query_id": current["query_id"],
                        }
                        if uuid in seen:
                            seen[uuid]["observations"].append(match)
                        else:
                            seen[uuid] = {
                                **article,
                                "retrieved_at_utc": datetime.now(UTC).isoformat(),
                                "observations": [match],
                            }
                            if review_callback:
                                review_callback(
                                    redact(item, token),
                                    current["scope"],
                                    current["query_id"],
                                )
                    if page * 3 >= meta["found"] or not data:
                        break
                stable = len({p["found"] for p in current["pages"]}) == 1
                complete = (
                    stable and valid_times and len(ids) == current["pages"][0]["found"]
                )
                current.update(
                    state="complete" if complete else "partial",
                    unique_uuids=len(ids),
                    checkpoint_advance=complete and current["scope"] == "fixed_morning",
                    zero_results=complete and not ids,
                    required_pages_first_found=max(
                        1, (current["pages"][0]["found"] + 2) // 3
                    ),
                )
            baseline = result["queries"][:4]
            result["fixed_window_checkpoint_eligible"] = all(
                q["checkpoint_advance"] for q in baseline
            )
            result["state"] = (
                "complete"
                if all(q["state"] == "complete" for q in result["queries"])
                else "partial"
            )
            result["checkpoint_advance"] = result["state"] == "complete"
        except ProbeError as exc:
            if current is not None:
                current.update(state="failed", checkpoint_advance=False)
            for pending in result["queries"]:
                if pending["state"] == "planned":
                    pending.update(state="skipped", reason="previous_collection_failed")
            result.update(state="failed", checkpoint_advance=False, error=str(exc))
    result.update(
        request_count=counter[0],
        articles=list(seen.values()),
        unique_uuids=len(seen),
        completed_at_utc=datetime.now(UTC).isoformat(),
    )

    return redact(result, token)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        result = probe(run=args.run, token=os.environ.get("MARKETAUX_API_TOKEN"))
    except ProbeError as exc:
        parser.exit(1, f"Marketaux focused probe failed: {exc}\n")
    output = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(output + "\n", encoding="utf-8")
    print(output)
    return int(result["state"] == "failed")


if __name__ == "__main__":
    raise SystemExit(main())
