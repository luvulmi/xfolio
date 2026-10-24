"""직접 작성한 가상 자료 6건으로 요약·usage를 시험한다. 기본은 무통신이다."""

import argparse
import json
import os
import re
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from openai import APIError, OpenAI, OpenAIError
from pydantic import BaseModel, ConfigDict, ValidationError

MODEL = "gpt-5.4-mini"
PROMPT_VERSION = "synthetic_summary_v2_scope_conditions"
MAX_OUTPUT_TOKENS = 600
INPUT_USD_PER_MILLION = 0.75
OUTPUT_USD_PER_MILLION = 4.50
SAFE_ERROR_CODES = frozenset(
    {
        "credit_balance_exhausted",
        "insufficient_quota",
        "rate_limit_exceeded",
        "invalid_api_key",
        "model_not_found",
        "context_length_exceeded",
        "invalid_request_error",
        "insufficient_permissions",
        "billing_hard_limit_reached",
    }
)
SAFE_API_ERROR_TYPES = frozenset(
    {
        "insufficient_quota",
        "invalid_request_error",
        "rate_limit_error",
        "server_error",
        "authentication_error",
        "permission_error",
        "billing_error",
    }
)
NOTICE = "기계 검사는 사실 정확성을 보장하지 않습니다. 한국어 품질·근거 함의의 인간 평가가 필요합니다."
INSTRUCTIONS = """직접 작성한 가상 뉴스 자료의 한국어 요약 시험이다. 실제 뉴스가 아니다.
주체·확정 사건·시점/대상 기간이 충분할 때만 selected=true로 판정한다.
미완성 조건이나 누락 기간을 추정하지 않는다. 부족하면 selected=false, summary_ko는 빈 문자열.
reason_ko는 한국어로 설명한다. source_id는 입력과 동일하게 유지한다.
evidence는 입력 text에서 그대로 가져온 연속 부분 문자열이다.
선정 시 summary_ko는 한국어로 작성하고 required_literals의 표기를 그대로 보존한다.
주체·수치·단위·대상 기간뿐 아니라 적용 범위(예: 업종 전반)와 확정/조건 표현도 보존한다.
보류 이유는 실제로 누락되거나 잘린 부분만 설명한다. 이미 주어진 날짜·값을 없다고 쓰지 않는다.
기사 외부 지식·가격 전망·투자 권유·추정 인과관계를 덧붙이지 않는다."""


@dataclass(frozen=True)
class Sample:
    source_id: str
    category: str
    text: str
    required_literals: tuple[str, ...]
    expected_selected: bool = True


SAMPLES = (
    Sample(
        "macro",
        "거시",
        "Fictional Statistics Office announced on 2026-10-10: "
        "2026-09 CPI rose 2.5% year-on-year.",
        ("2026-10-10", "2026-09", "2.5%"),
    ),
    Sample(
        "sector",
        "업종",
        "Fictional Energy Board confirmed on 2026-10-11 a "
        "sector-wide electricity tariff cut of 3% effective 2026-11-01.",
        ("2026-10-11", "3%", "2026-11-01"),
    ),
    Sample(
        "earnings",
        "실적",
        "Fictional Acme reported on 2026-10-12 that "
        "2026-Q3 revenue was USD 10 million, versus USD 8 million in 2025-Q3.",
        ("2026-10-12", "2026-Q3", "USD 10 million", "USD 8 million", "2025-Q3"),
    ),
    Sample(
        "business",
        "확정 사업 변화",
        "Fictional Beta confirmed on 2026-10-13 "
        "that its Delta acquisition closed on 2026-10-12 for USD 20 million.",
        ("2026-10-13", "2026-10-12", "USD 20 million"),
    ),
    Sample(
        "missing_period",
        "기간 누락",
        "Fictional Acme announced revenue of "
        "USD 10 million. The reporting period and announcement date are absent.",
        (),
        False,
    ),
    Sample(
        "cut_condition",
        "조건 잘림",
        "Fictional Gamma announced on 2026-10-14 "
        "that a factory will open on 2027-01-01 only if [source truncated].",
        (),
        False,
    ),
)


class Summary(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    selected: bool
    reason_ko: str
    summary_ko: str
    source_id: str
    evidence: str


def checks(sample: Sample, result: Summary) -> dict[str, bool]:
    def korean(text: str) -> bool:
        return bool(re.search(r"[가-힣]", text))

    numbers = re.findall(r"\d+(?:\.\d+)?", result.summary_ko)
    return {
        "source_id_matches": result.source_id == sample.source_id,
        "evidence_present": bool(result.evidence.strip())
        and result.evidence in sample.text,
        "korean_reason": korean(result.reason_ko),
        "korean_summary": not result.selected or korean(result.summary_ko),
        "held_summary_empty": result.selected or result.summary_ko == "",
        "selection_matches_expected": result.selected == sample.expected_selected,
        "required_facts_present": not result.selected
        or all(
            value in result.evidence and value in result.summary_ko
            for value in sample.required_literals
        ),
        "no_new_numbers": all(value in sample.text for value in numbers),
    }


def probe(client: OpenAI, sample: Sample) -> dict:
    report = {
        "sample_id": sample.source_id,
        "observed_at_utc": datetime.now(UTC).isoformat(),
        "model": MODEL,
        "prompt_version": PROMPT_VERSION,
        "status": "failed",
        "usage": None,
        "cost_usd": None,
        "checks": {},
        "summary_ko": "",
        "human_review_required": True,
        "batch_stop": False,
    }
    started = time.perf_counter()
    try:
        # Raw wrapper preserves billed usage even if Pydantic parsing fails.
        raw = client.responses.with_raw_response.parse(
            model=MODEL,
            instructions=INSTRUCTIONS,
            input=json.dumps(
                {
                    "source_id": sample.source_id,
                    "text": sample.text,
                    "required_literals": sample.required_literals,
                },
                ensure_ascii=False,
            ),
            text_format=Summary,
            store=False,
            reasoning={"effort": "none"},
            max_output_tokens=MAX_OUTPUT_TOKENS,
            tools=[],
        )
        payload = raw.http_response.json()
        report["usage"] = payload.get("usage")
        usage = report["usage"]
        valid_usage = isinstance(usage, dict) and all(
            type(usage.get(key)) is int and usage[key] >= 0
            for key in ("input_tokens", "output_tokens", "total_tokens")
        )
        if valid_usage:
            valid_usage = (
                usage["total_tokens"] == usage["input_tokens"] + usage["output_tokens"]
            )
        if valid_usage:
            report["cost_usd"] = round(
                (
                    usage["input_tokens"] * INPUT_USD_PER_MILLION
                    + usage["output_tokens"] * OUTPUT_USD_PER_MILLION
                )
                / 1e6,
                10,
            )
        if not valid_usage:
            report["error_type"] = "MissingOrInvalidUsage"
        else:
            response = raw.parse()
            report["response_model"] = response.model
            report["response_status"] = response.status
            result = response.output_parsed
            if response.status == "completed" and result is not None:
                report.update(result.model_dump())
                report["checks"] = checks(sample, result)
                if all(report["checks"].values()):
                    report["status"] = "mechanical_checks_passed"
    except APIError as exc:
        # Only fixed protocol codes are retained; arbitrary error text is secret-bearing.
        report["error_type"] = type(exc).__name__
        status_code = getattr(exc, "status_code", None)
        report["status_code"] = status_code if type(status_code) is int else None
        report["error_code"] = (
            exc.code
            if isinstance(exc.code, str) and exc.code in SAFE_ERROR_CODES
            else None
        )
        report["api_error_type"] = (
            exc.type
            if isinstance(exc.type, str) and exc.type in SAFE_API_ERROR_TYPES
            else None
        )
        report["batch_stop"] = True
    except (OpenAIError, ValidationError, ValueError, TypeError, AttributeError) as exc:
        # Exception messages/body/request can contain credentials or response text.
        report["error_type"] = type(exc).__name__
    report["latency_seconds"] = round(time.perf_counter() - started, 3)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run", action="store_true", help="실제 API로 가상 자료만 최대 6회 시험"
    )
    args = parser.parse_args(argv)
    config = {
        "model": MODEL,
        "prompt_version": PROMPT_VERSION,
        "max_calls": len(SAMPLES),
        "max_output_tokens": MAX_OUTPUT_TOKENS,
        "timeout_seconds": 30,
        "max_retries": 0,
        "store": False,
        "reasoning": "none",
        "tools": [],
        "input_usd_per_million": INPUT_USD_PER_MILLION,
        "output_usd_per_million": OUTPUT_USD_PER_MILLION,
        "notice": NOTICE,
    }
    if not args.run:
        print(
            json.dumps(
                {
                    "mode": "dry_run",
                    "network_requests": 0,
                    "config": config,
                    "samples": [asdict(sample) for sample in SAMPLES],
                },
                ensure_ascii=False,
            )
        )
        return 0
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        print(
            json.dumps(
                {
                    "status": "missing_api_key",
                    "network_requests": 0,
                    "notice": "OPENAI_API_KEY 환경변수가 없습니다.",
                },
                ensure_ascii=False,
            )
        )
        return 2
    reports = []
    with OpenAI(
        api_key=api_key, base_url="https://api.openai.com/v1", timeout=30, max_retries=0
    ) as client:
        for sample in SAMPLES:
            report = probe(client, sample)
            reports.append(report)
            print(json.dumps(report, ensure_ascii=False))
            if report["batch_stop"]:
                break
    failed = any(item["status"] != "mechanical_checks_passed" for item in reports)
    print(
        json.dumps(
            {
                "mode": "run",
                "calls": len(reports),
                "planned_calls": len(SAMPLES),
                "skipped_calls": len(SAMPLES) - len(reports),
                "batch_stopped": any(item["batch_stop"] for item in reports),
                "config": config,
                "known_usage_cost_usd": round(
                    sum(item["cost_usd"] or 0 for item in reports), 10
                ),
                "usage_complete": all(item["cost_usd"] is not None for item in reports),
                "unknown_calls": sum(item["cost_usd"] is None for item in reports),
                "missing_usage_calls": sum(item["usage"] is None for item in reports),
                "status": "failed" if failed else "human_review_required",
            },
            ensure_ascii=False,
        )
    )
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
