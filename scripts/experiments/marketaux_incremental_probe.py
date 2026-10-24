"""두 30분 창의 Marketaux 페이지·겹침·중복 실험. 기본 dry-run, 서비스 커서 없음."""

import argparse
import importlib.util
import json
import os
import re
import time
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path

import httpx

SPEC = importlib.util.spec_from_file_location(
    "marketaux_metadata", Path(__file__).with_name("marketaux_sample_probe.py")
)
metadata = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(metadata)
ProbeError = metadata.ProbeError
EXPERIMENT_VERSION = "marketaux_incremental_v2_pacing"
MIN_REQUEST_INTERVAL_SECONDS = 3.0
SAFE_LIMIT_HEADERS = (
    "x-usagelimit-limit",
    "x-usagelimit-remaining",
    "x-ratelimit-limit",
    "x-ratelimit-remaining",
)


class RequestPacer:
    """이 프로세스의 요청 시작 간격만 보장한다. 계정 전체 쿼터는 예약하지 않는다."""

    def __init__(self, clock, sleep):
        self.clock, self.sleep = clock, sleep
        self.last_started = None

    def wait(self):
        if self.last_started is not None:
            while (
                remaining := self.last_started
                + MIN_REQUEST_INTERVAL_SECONDS
                - self.clock()
            ) > 0:
                self.sleep(remaining)
        self.last_started = self.clock()


def windows(now):
    if now.utcoffset() is None:
        raise ProbeError("config: reference time must have a timezone")
    end = now.astimezone(UTC).replace(microsecond=0)
    return [
        (end - timedelta(minutes=60), end - timedelta(minutes=30)),
        (end - timedelta(minutes=30), end),
    ]


def replay_plan(day, reference):
    kst = timezone(timedelta(hours=9))
    today = reference.astimezone(kst).date()
    if not 1 <= (today - day).days <= 6 or day.weekday() >= 5:
        raise ProbeError(
            "config: replay date must be a weekday in the previous six days"
        )
    opening = datetime.combine(day, datetime.min.time(), tzinfo=kst) + timedelta(
        hours=9
    )
    last = opening - timedelta(hours=15, minutes=30)
    plans = [(1, last.astimezone(UTC), opening.astimezone(UTC), metadata.QUERIES[2:])]
    for index in range(1, 18):
        start = opening + timedelta(minutes=30 * (index - 1))
        end = opening + timedelta(minutes=30 * index)
        plans.append(
            (
                index + 1,
                start.astimezone(UTC),
                end.astimezone(UTC),
                metadata.QUERIES[2:],
            )
        )
    morning = opening - timedelta(hours=1, minutes=30)
    plans.append(
        (
            "morning",
            (morning - timedelta(days=1)).astimezone(UTC),
            morning.astimezone(UTC),
            metadata.QUERIES[:2],
        )
    )
    return plans


def evidence_signals(item):
    """반환된 짧은 텍스트의 어휘 존재만 표시한다. 사실·충분성 판정이 아니다."""
    text = " ".join(item.get(key) or "" for key in ("description", "snippet"))
    names = [
        e.get("name")
        for e in item.get("entities", [])
        if isinstance(e.get("name"), str)
    ]
    return {
        "subject_name_present": any(name.lower() in text.lower() for name in names),
        "change_verb_present": bool(
            re.search(
                r"\b(announced|reported|completed|signed|approved|halted|suspended|raised|cut)\b",
                text,
                re.IGNORECASE,
            )
        ),
        "period_or_date_present": bool(
            re.search(
                r"\b(20\d{2}|Q[1-4]|quarter|October|November|September|Monday|Tuesday|Wednesday|Thursday|Friday)\b",
                text,
                re.IGNORECASE,
            )
        ),
        "number_present": bool(re.search(r"\d", text)),
        "condition_marker_present": bool(
            re.search(
                r"\b(if|subject to|unless|pending|expected|forecast|guidance)\b",
                text,
                re.IGNORECASE,
            )
        ),
        "classification": "lexical_presence_only_not_fact_validation",
    }


def fetch_page(client, params, token, page, counter, pacer, observations):
    if counter[0] >= counter[1]:
        raise ProbeError("budget: request cap reached")
    pacer.wait()
    counter[0] += 1
    try:
        response = client.get(
            metadata.ENDPOINT, params={**params, "page": page, "api_token": token}
        )
    except httpx.RequestError:
        raise ProbeError("transport failure; no retry") from None
    observations.append(
        {
            "request_number": counter[0],
            "status_code": response.status_code,
            "limit_headers": {
                name: value
                for name in SAFE_LIMIT_HEADERS
                if (value := response.headers.get(name)) is not None
                and re.fullmatch(r"[0-9]+", value)
                and not (token and token in value)
            },
            "limit_classification": {
                402: "daily_request_limit",
                429: "recent_60_second_rate_limit",
            }.get(response.status_code),
        }
    )
    if response.status_code != 200:
        raise ProbeError(f"HTTP {response.status_code}; no retry")
    try:
        payload = response.json()
    except ValueError:
        raise ProbeError("schema: invalid JSON") from None
    if not isinstance(payload, dict) or payload.get("error") or payload.get("errors"):
        raise ProbeError("API error; response body omitted")
    meta, data = payload.get("meta"), payload.get("data")
    if not isinstance(meta, dict) or not isinstance(data, list):
        raise ProbeError("schema: meta/data required")
    if any(
        type(meta.get(k)) is not int or meta[k] < 0
        for k in ("found", "returned", "page", "limit")
    ):
        raise ProbeError("schema: invalid pagination")
    if (
        meta["page"] != page
        or meta["limit"] != 3
        or meta["returned"] != len(data)
        or len(data) > 3
        or meta["found"] < (page - 1) * 3 + len(data)
    ):
        raise ProbeError("schema: inconsistent pagination")
    return {key: meta[key] for key in ("found", "returned", "page", "limit")}, data


def probe(
    *,
    run=False,
    token=None,
    repeat=False,
    now=None,
    transport=None,
    replay_date=None,
    clock=None,
    sleep=None,
):
    reference = now or datetime.now(UTC)
    periods = windows(reference)
    if replay_date and repeat:
        raise ProbeError("config: day replay cannot use --repeat")
    plans = (
        replay_plan(replay_date, reference)
        if replay_date
        else [
            (index, start, end, metadata.QUERIES)
            for index, (start, end) in enumerate(periods, 1)
        ]
    )
    if run and not token:
        raise ProbeError("config: MARKETAUX_API_TOKEN required with --run")
    result = {
        "mode": "run" if run else "dry_run",
        "experiment_version": EXPERIMENT_VERSION,
        "min_request_interval_seconds": MIN_REQUEST_INTERVAL_SECONDS,
        "max_retries": 0,
        "as_of_utc": reference.astimezone(UTC).isoformat(),
        "state": "dry_run",
        "sample_status": "limited_sample",
        "request_cap": 60 if replay_date else 16 + int(repeat),
        "replay_date_kst": replay_date.isoformat() if replay_date else None,
        "pages_per_query_cap": 10 if replay_date else 2,
        "request_count": 0,
        "request_observations": [],
        "overlap_minutes": 1,
        "checkpoint_advance": False,
        "cursor_written": False,
        "queries": [],
        "articles": [],
        "repeat": None,
        "limitations": [
            "two short windows cannot prove daily Free quota sufficiency",
            "weekend sample cannot establish weekday volume",
            "UUID deduplication does not identify the same event across different UUIDs",
            "late indexing after this run remains unmeasured",
            "AAPL/MSFT/NVDA are trial symbols, not a confirmed watchlist",
            "3-second spacing buffers an assumed 30 requests/minute; shared account quota is not guaranteed",
        ],
    }
    if replay_date:
        result["limitations"][:2] = [
            "one historical weekday replay is not live 18-poll or weekday-volume validation",
            "only complete observed jobs can support this replay day's request demand",
        ]
    for index, start, end, queries in plans:
        for name, search, symbols in queries:
            after = start - timedelta(minutes=1)
            params = {
                "search": search,
                "language": "en",
                "limit": 3,
                "sort": "published_at",
                "published_after": after.strftime("%Y-%m-%dT%H:%M:%S"),
                "published_before": end.strftime("%Y-%m-%dT%H:%M:%S"),
            }
            if symbols:
                params.update(symbols=symbols, filter_entities="true")
            result["queries"].append(
                {
                    "window": index,
                    "query": name,
                    "nominal_after_utc": start.isoformat(),
                    "nominal_before_utc": end.isoformat(),
                    "parameters": params,
                    "state": "planned",
                    "checkpoint_advance": False,
                    "pages": [],
                    "new_uuids": 0,
                    "duplicate_uuids": 0,
                    "unique_uuids": 0,
                }
            )
    if not run:
        return result
    pacer = RequestPacer(clock or time.monotonic, sleep or time.sleep)
    counter, all_seen = [0, result["request_cap"]], {}
    current = None
    with httpx.Client(
        transport=transport, timeout=15, follow_redirects=False
    ) as client:
        try:
            for current in result["queries"]:
                if counter[0] >= counter[1]:
                    current.update(
                        state="skipped", skip_reason="request_budget_exhausted"
                    )
                    continue
                after = datetime.fromisoformat(
                    current["parameters"]["published_after"]
                ).replace(tzinfo=UTC)
                before = datetime.fromisoformat(current["nominal_before_utc"])
                local_ids, first_page_ids, dates_valid = set(), set(), True
                for page in range(1, result["pages_per_query_cap"] + 1):
                    if counter[0] >= counter[1]:
                        break
                    meta, data = fetch_page(
                        client,
                        current["parameters"],
                        token,
                        page,
                        counter,
                        pacer,
                        result["request_observations"],
                    )
                    current["pages"].append(meta)
                    for item in data:
                        article = metadata.article_metadata(
                            item, current["query"], after, before
                        )
                        if replay_date:
                            article["evidence_signals"] = evidence_signals(item)
                        dates_valid &= article["eligible_for_review"]
                        uuid = article["uuid"]
                        local_ids.add(uuid)
                        if page == 1:
                            first_page_ids.add(uuid)
                        if uuid in all_seen:
                            current["duplicate_uuids"] += 1
                            all_seen[uuid]["observations"].append(
                                {"window": current["window"], "query": current["query"]}
                            )
                        else:
                            current["new_uuids"] += 1
                            all_seen[uuid] = {
                                **article,
                                "observations": [
                                    {
                                        "window": current["window"],
                                        "query": current["query"],
                                    }
                                ],
                            }
                    if page * 3 >= meta["found"] or not data:
                        break
                current["first_page_uuids"] = sorted(first_page_ids)
                current["unique_uuids"] = len(local_ids)
                current["required_pages_first_found"] = max(
                    1, (current["pages"][0]["found"] + 2) // 3
                )
                stable = len({p["found"] for p in current["pages"]}) == 1
                complete = (
                    stable
                    and len(local_ids) == current["pages"][0]["found"]
                    and dates_valid
                )
                current.update(
                    state="complete" if complete else "partial",
                    checkpoint_advance=complete,
                    zero_results=complete and not local_ids,
                )
            result["state"] = (
                "complete"
                if all(q["checkpoint_advance"] for q in result["queries"])
                else "partial"
            )
            result["checkpoint_advance"] = result["state"] == "complete"
            if repeat:
                target = result["queries"][4]
                current = target
                meta, data = fetch_page(
                    client,
                    target["parameters"],
                    token,
                    1,
                    counter,
                    pacer,
                    result["request_observations"],
                )
                after = datetime.fromisoformat(
                    target["parameters"]["published_after"]
                ).replace(tzinfo=UTC)
                before = datetime.fromisoformat(target["nominal_before_utc"])
                checked = [
                    metadata.article_metadata(item, target["query"], after, before)
                    for item in data
                ]
                ids = {article["uuid"] for article in checked}
                original = set(target["first_page_uuids"])
                result["repeat"] = {
                    "window": 2,
                    "query": target["query"],
                    "page": meta,
                    "same_uuids": len(ids & original),
                    "new_uuids": len(ids - original),
                    "missing_previous_uuids": len(original - ids),
                    "scope": "one first page only; not a second complete collection",
                }
                if ids != original or not all(
                    a["eligible_for_review"] for a in checked
                ):
                    result.update(state="partial", checkpoint_advance=False)
                    target.update(state="partial", checkpoint_advance=False)
        except ProbeError as exc:
            if current is not None:
                current.update(state="failed", checkpoint_advance=False)
            for pending in result["queries"]:
                if pending["state"] == "planned":
                    pending.update(
                        state="skipped", skip_reason="previous_collection_failed"
                    )
            result.update(state="failed", checkpoint_advance=False, error=str(exc))
    result.update(
        request_count=counter[0],
        articles=list(all_seen.values()),
        unique_uuids=len(all_seen),
        completed_at_utc=datetime.now(UTC).isoformat(),
    )

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
    parser.add_argument(
        "--repeat",
        action="store_true",
        help="repeat window 2 macro_policy first page once",
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--replay-date",
        type=date.fromisoformat,
        help="historical KST weekday, e.g. 2026-10-23; cap 60 GETs",
    )
    args = parser.parse_args(argv)
    try:
        result = probe(
            run=args.run,
            repeat=args.repeat,
            token=os.environ.get("MARKETAUX_API_TOKEN"),
            replay_date=args.replay_date,
        )
    except ProbeError as exc:
        parser.exit(1, f"Marketaux incremental probe failed: {exc}\n")
    output = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(output + "\n", encoding="utf-8")
    print(output)
    return 1 if result["state"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
