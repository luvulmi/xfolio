"""동일한 가상 6사례·같은 프롬프트로 Mini와 Luna를 비교한다."""

import argparse
import json
import os
from pathlib import Path

from openai import OpenAI

from scripts.experiments.news_summary_probe import SAMPLES
from xfolio.analysis import MODEL_PRICES, PROMPT_VERSION, analyze_synthetic

MAX_COST_USD = 0.05
OUTPUT = Path("tasks/verification/assets/ai_compare/mini_luna_20261025.jsonl")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="실제 모델 최대12회 호출")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args(argv)
    models = tuple(MODEL_PRICES)
    if not args.run:
        print(
            json.dumps(
                {
                    "mode": "dry_run",
                    "network_requests": 0,
                    "models": models,
                    "cases": [sample.source_id for sample in SAMPLES],
                    "max_calls": len(models) * len(SAMPLES),
                    "max_known_cost_usd": MAX_COST_USD,
                    "prompt_version": PROMPT_VERSION,
                },
                ensure_ascii=False,
            )
        )
        return 0
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        print(json.dumps({"status": "missing_api_key", "calls": 0}))
        return 2
    reports = []
    known_cost = 0.0
    with OpenAI(
        api_key=key,
        base_url="https://api.openai.com/v1",
        timeout=30,
        max_retries=0,
    ) as client:
        for sample in SAMPLES:
            for model in models:
                if known_cost >= MAX_COST_USD:
                    break
                result = analyze_synthetic(
                    client,
                    source_id=sample.source_id,
                    source_text=sample.text,
                    required_literals=sample.required_literals,
                    expected_selected=sample.expected_selected,
                    model=model,
                )
                reports.append({"case_id": sample.source_id, **result})
                if result["cost_usd"] is not None:
                    known_cost += result["cost_usd"]
                if result["batch_stop"] or result["cost_usd"] is None:
                    break
            if len(reports) < (list(SAMPLES).index(sample) + 1) * len(models):
                break
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="\n") as file:
        for report in reports:
            file.write(json.dumps(report, ensure_ascii=False) + "\n")
    summary = {
        "mode": "run",
        "calls": len(reports),
        "expected_calls": len(models) * len(SAMPLES),
        "known_cost_usd": round(known_cost, 10),
        "usage_complete": all(item["cost_usd"] is not None for item in reports),
        "all_mechanical_checks_passed": all(
            item["status"] == "mechanical_checks_passed" for item in reports
        ),
        "human_review_required": True,
        "output": str(args.output),
    }
    print(json.dumps(summary, ensure_ascii=False))
    return int(
        not summary["usage_complete"] or not summary["all_mechanical_checks_passed"]
    )


if __name__ == "__main__":
    raise SystemExit(main())
