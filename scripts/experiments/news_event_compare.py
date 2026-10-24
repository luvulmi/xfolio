"""이미 확인한 사건의 Marketaux 첫 페이지 비교. 원문 저장·모델 호출 없음."""

import argparse
import importlib.util
import json
import os
import re
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

SPEC = importlib.util.spec_from_file_location(
    "focused_event_helper", Path(__file__).with_name("marketaux_focused_probe.py")
)
focused = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(focused)
redact = focused.redact
ProbeError = focused.ProbeError
RequestPacer = focused.helper.RequestPacer
fetch_page = focused.helper.fetch_page
metadata = focused.helper.metadata

MANIFEST = Path("tasks/verification/assets/news_cases/events_20261025.json")
OUTPUT = Path("tasks/verification/assets/news_cases/marketaux_events_20261025.json")
OFFICIAL_OUTPUT = Path(
    "tasks/verification/assets/news_cases/official_fetch_20261025.json"
)


def official_probe(manifest, *, run=False, transport=None):
    """공식 주소 GET의 접근성만 검사한다. PDF/HTML 내용 파싱 합격이 아니다."""
    report = {
        "mode": "run" if run else "dry_run",
        "request_count": 0,
        "cases": [],
        "content_saved": False,
    }
    with httpx.Client(transport=transport, timeout=20, follow_redirects=True) as client:
        for case in manifest["cases"]:
            row = {
                "case_id": case["id"],
                "url": case["official_url"],
                "state": "planned",
            }
            report["cases"].append(row)
            if not run:
                continue
            report["request_count"] += 1
            row["observed_at_utc"] = datetime.now(UTC).isoformat()
            try:
                response = client.get(
                    case["official_url"], headers={"User-Agent": "XFolio-Research/1.0"}
                )
            except httpx.RequestError:
                row.update(state="failed", error="transport_error")
                continue
            row.update(
                state="retrieved" if response.status_code == 200 else "failed",
                http_status=response.status_code,
                content_type=response.headers.get("content-type"),
                bytes=len(response.content),
                redirects=len(response.history),
                parsed=False,
            )
    return report


def marker_report(item, markers):
    text = " ".join(item.get(key) or "" for key in ("title", "description", "snippet"))
    return {
        key: bool(re.search(pattern, text, re.IGNORECASE))
        for key, pattern in markers.items()
    }


def compare(
    manifest, *, token=None, run=False, transport=None, now=None, clock=None, sleep=None
):
    start = datetime.fromisoformat(manifest["window_start"])
    end = datetime.fromisoformat(manifest["window_end"])
    now = now or datetime.now(UTC)
    if any(value.utcoffset() is None for value in (start, end, now)):
        raise ProbeError("timezone required")
    if not now - timedelta(days=7) <= start < end <= now:
        raise ProbeError(
            "fixed comparison window is outside the seven-day experiment scope"
        )
    if run and not token:
        raise ProbeError("MARKETAUX_API_TOKEN required")
    cases = manifest["cases"]
    if not 1 <= len(cases) <= 20:
        raise ProbeError("case count must be 1..20")
    report = {
        "mode": "run" if run else "dry_run",
        "observed_at_utc": now.isoformat(),
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "manifest_version": manifest["version"],
        "state": "dry_run",
        "request_cap": 20,
        "request_count": 0,
        "requests": [],
        "cases": [],
        "cursor_written": False,
        "can_publish": False,
        "lexical_matches_are_not_event_or_evidence_validation": True,
    }
    counter = [0, 20]
    pacer = RequestPacer(clock or time.monotonic, sleep or time.sleep)
    stopped = False
    with httpx.Client(
        transport=transport, timeout=20, follow_redirects=False
    ) as client:
        for case in cases:
            row = {
                "case_id": case["id"],
                "event_key": case["event_key"],
                "state": "planned",
                "articles": [],
            }
            report["cases"].append(row)
            if case["kind"] == "outside_window":
                row.update(state="skipped", reason="reference_event_outside_window")
                continue
            if stopped:
                row.update(state="skipped", reason="previous_failure")
                continue
            params = {
                "search": case["search"],
                "language": "en",
                "limit": 3,
                "sort": "relevance_score",
                "group_similar": "false",
                "published_after": start.strftime("%Y-%m-%dT%H:%M:%S"),
                "published_before": end.strftime("%Y-%m-%dT%H:%M:%S"),
            }
            row["parameters"] = params
            if not run:
                continue
            try:
                meta, data = fetch_page(
                    client, params, token, 1, counter, pacer, report["requests"]
                )
                row["pagination"] = meta
                for item in data:
                    article = metadata.article_metadata(item, case["id"], start, end)
                    article.pop("selected_entities", None)
                    if not article["eligible_for_review"]:
                        raise ProbeError("returned article outside time window")
                    row["articles"].append(
                        {
                            **article,
                            "marker_matches": marker_report(item, case["markers"]),
                            "meaning_review": "not_performed",
                        }
                    )
                ids = {article["uuid"] for article in row["articles"]}
                row["state"] = (
                    "complete" if len(ids) == meta["found"] else "partial_sample"
                )
            except ProbeError as exc:
                row.update(state="failed", error=str(exc))
                stopped = True
    report["request_count"] = counter[0]
    if run:
        report["state"] = "failed" if stopped else "sampled"
    return redact(report, token)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true")
    parser.add_argument(
        "--official", action="store_true", help="키 없이 공식 주소 GET 접근성만 확인"
    )
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        report = (
            official_probe(manifest, run=args.run)
            if args.official
            else compare(manifest, token=os.getenv("MARKETAUX_API_TOKEN"), run=args.run)
        )
    except ProbeError as exc:
        print(json.dumps({"state": "configuration_error", "error": str(exc)}))
        return 2
    if args.run:
        output = args.output or (OFFICIAL_OUTPUT if args.official else OUTPUT)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    print(json.dumps(report, ensure_ascii=False))
    return int(
        report.get("state") == "failed"
        or any(row["state"] == "failed" for row in report["cases"])
    )


if __name__ == "__main__":
    raise SystemExit(main())
