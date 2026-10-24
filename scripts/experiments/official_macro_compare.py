"""BLS 원문 직접 조회와 제한된 OpenAI Web search를 한 사건으로 비교한다."""

import argparse
import json
import os
import re
from datetime import UTC, datetime
from html import unescape
from pathlib import Path

import httpx
from openai import APIError, OpenAI

BLS_URL = "https://www.bls.gov/news.release/archives/cpi_10142026.htm"
OUTPUT = Path("tasks/verification/assets/ai_compare/bls_direct_web_20261025.json")


def direct_bls() -> dict:
    with httpx.Client(timeout=25, follow_redirects=True) as client:
        response = client.get(BLS_URL, headers={"User-Agent": "XFolio-Research/1.0"})
    response.raise_for_status()
    text = unescape(re.sub(r"<[^>]+>", " ", response.text))
    text = re.sub(r"\s+", " ", text).lower()
    return {
        "url": str(response.url),
        "http_status": response.status_code,
        "bytes": len(response.content),
        "release_date_present": "october 14, 2026" in text,
        "cpi_12_month_3_7_present": "3.7 percent" in text,
        "cpi_month_0_6_present": "0.6 percent" in text,
        "credential_needed": False,
        "openai_cost_usd": 0,
    }


def web_search(client) -> dict:
    result = client.responses.create(
        model="gpt-6-luna",
        instructions=(
            "Find only the official BLS September 2026 CPI release dated "
            "October 14, 2026. Give the 12-month all-items unadjusted percent "
            "and the 1-month seasonally adjusted percent, with the official "
            "source URL. Do not discuss market impact. Cite the source."
        ),
        input="Report the two CPI figures from the official BLS archive.",
        tools=[{"type": "web_search", "filters": {"allowed_domains": ["bls.gov"]}}],
        tool_choice="required",
        include=["web_search_call.action.sources"],
        reasoning={"effort": "none"},
        max_output_tokens=350,
        store=False,
    )
    calls = [item for item in result.output if item.type == "web_search_call"]
    sources = []
    for call in calls:
        action = call.action
        sources.extend(
            source.url
            for source in (getattr(action, "sources", None) or [])
            if getattr(source, "url", None)
        )
    usage = result.usage
    annotations = []
    for item in result.output:
        if item.type == "message":
            for content in item.content:
                annotations.extend(
                    annotation.url
                    for annotation in (getattr(content, "annotations", None) or [])
                    if getattr(annotation, "url", None)
                )
    return {
        "status": result.status,
        "model": result.model,
        "web_search_calls": len(calls),
        "source_urls": sorted(set(sources)),
        "citation_urls": sorted(set(annotations)),
        "answer": result.output_text,
        "usage": usage.model_dump() if usage is not None else None,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args(argv)
    if not args.run:
        print(json.dumps({"mode": "dry_run", "requests": 0, "url": BLS_URL}))
        return 0
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        print(json.dumps({"status": "missing_api_key", "requests": 0}))
        return 2
    report = {"observed_at_utc": datetime.now(UTC).isoformat(), "direct": direct_bls()}
    try:
        with OpenAI(
            api_key=key,
            base_url="https://api.openai.com/v1",
            timeout=35,
            max_retries=0,
        ) as client:
            report["web_search"] = web_search(client)
    except (APIError, httpx.HTTPError) as exc:
        report["web_search"] = {"status": "failed", "error_type": type(exc).__name__}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"output": str(args.output), **report}, ensure_ascii=False))
    return int(report["web_search"]["status"] != "completed")


if __name__ == "__main__":
    raise SystemExit(main())
