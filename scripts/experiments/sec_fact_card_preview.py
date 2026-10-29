"""SEC 공시의 직접 대조한 사실 카드 3건으로 한국어 비게시 미리보기를 시험한다."""

import argparse
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path

from openai import OpenAI
from pydantic import BaseModel, ConfigDict

from xfolio.analysis import usage_cost_usd
from xfolio.compose import weighted_length_estimate

MODEL = "gpt-5.4-mini"
OUTPUT = Path(
    "tasks/verification/assets/news_cases/sec_fact_card_preview_20261025.json"
)
INSTRUCTIONS = (
    "다음은 SEC EDGAR 공시에서 사람이 대조해 직접 작성한 사실 카드다. "
    "본문 인용·외부 검색 없이 이 카드만으로 과거 실적 발표의 한국어 X 초안 한 문장을 작성한다. "
    "주체, 회계연도 분기, 매출, 전년 동기 증가율을 정확히 보존한다. "
    "제공된 사실 밖의 주가 영향·원인·전망을 추정하지 않는다. "
    "원문 URL은 답변에 넣지 않는다."
)


class Draft(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    summary_ko: str
    review_note_ko: str


CASES = (
    {
        "id": "NVDA-FY27-Q2",
        "subject": "NVIDIA",
        "period": "2027회계연도 2분기",
        "revenue": "962억 달러",
        "growth": "106%",
        "filing_date": "2026-08-26",
        "period_end": "2026-07-26",
        "source_url": "https://www.sec.gov/Archives/edgar/data/1045810/000104581026000073/q2fy27pr.htm",
    },
    {
        "id": "AAPL-FY26-Q3",
        "subject": "Apple",
        "period": "2026회계연도 3분기",
        "revenue": "1,094억 달러",
        "growth": "16%",
        "filing_date": "2026-07-30",
        "period_end": "2026-06-27",
        "source_url": "https://www.sec.gov/Archives/edgar/data/320193/000032019326000018/a8-kex991q3202606272026.htm",
    },
    {
        "id": "MSFT-FY26-Q4",
        "subject": "Microsoft",
        "period": "2026회계연도 4분기",
        "revenue": "900억 달러",
        "growth": "18%",
        "filing_date": "2026-07-29",
        "period_end": "2026-06-30",
        "source_url": "https://www.sec.gov/Archives/edgar/data/789019/000119312526323632/msft-ex99_1.htm",
    },
)


def assess(case: dict, draft: Draft) -> dict:
    summary = draft.summary_ko.strip()
    post = summary + "\n원문: " + case["source_url"]
    required = (case["subject"], case["period"], case["revenue"], case["growth"])
    numbers = re.findall(r"\d+(?:,\d{3})*(?:\.\d+)?%?", summary)
    card_text = " ".join(str(value) for value in case.values())
    checks = {
        "required_facts": all(fact in summary for fact in required),
        "no_new_numbers": all(number in card_text for number in numbers),
        "korean": bool(re.search(r"[가-힣]", summary)),
        "length": weighted_length_estimate(post) <= 280,
    }
    return {
        "case_id": case["id"],
        "source_url": case["source_url"],
        "post_preview": post,
        "review_note_ko": draft.review_note_ko,
        "weighted_length_estimate": weighted_length_estimate(post),
        "checks": checks,
        "mechanical_checks_passed": all(checks.values()),
        "human_review_required": True,
        "can_publish": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run", action="store_true", help="OpenAI에 사실 카드 최대 3건 전송"
    )
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args(argv)
    if not args.run:
        print(
            json.dumps(
                {"mode": "dry_run", "requests": 0, "case_ids": [c["id"] for c in CASES]}
            )
        )
        return 0
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        print(json.dumps({"status": "missing_api_key", "requests": 0}))
        return 2
    reports = []
    with OpenAI(api_key=key, timeout=30, max_retries=0) as client:
        for case in CASES:
            card = {name: value for name, value in case.items() if name != "source_url"}
            raw = client.responses.with_raw_response.parse(
                model=MODEL,
                instructions=INSTRUCTIONS,
                input=json.dumps(card, ensure_ascii=False),
                text_format=Draft,
                store=False,
                tools=[],
                reasoning={"effort": "none"},
                max_output_tokens=300,
            )
            response = raw.parse()
            usage = raw.http_response.json().get("usage")
            if response.status != "completed" or response.output_parsed is None:
                print(
                    json.dumps({"status": "incomplete", "requests": len(reports) + 1})
                )
                return 1
            report = assess(case, response.output_parsed)
            report["usage"] = usage
            report["cost_usd_estimate"] = usage_cost_usd(usage, MODEL)
            reports.append(report)
            if not report["mechanical_checks_passed"]:
                break
    payload = {
        "mode": "run",
        "observed_at_utc": datetime.now(UTC).isoformat(),
        "model": MODEL,
        "source": "SEC EDGAR EX-99.1 factual cards; no article body sent",
        "requests": len(reports),
        "all_checks_passed": len(reports) == len(CASES)
        and all(report["mechanical_checks_passed"] for report in reports),
        "human_review_required": True,
        "can_publish": False,
        "results": reports,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {key: value for key, value in payload.items() if key != "results"},
            ensure_ascii=False,
        )
    )
    return int(not payload["all_checks_passed"])


if __name__ == "__main__":
    raise SystemExit(main())
