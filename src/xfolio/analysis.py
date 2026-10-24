"""직접 작성한 가상 자료만 OpenAI로 분석하는 공통 경로."""

import json
import re
import time
from datetime import UTC, datetime

from openai import APIError, OpenAIError
from pydantic import BaseModel, ConfigDict, ValidationError

PROMPT_VERSION = "synthetic_summary_v2_scope_conditions"
MAX_OUTPUT_TOKENS = 600
DEFAULT_MODEL = "gpt-6-luna"
MODEL_PRICES = {
    "gpt-5.4-mini": (0.75, 4.50),
    "gpt-6-luna": (0.10, 0.50),
}
CACHED_INPUT_PRICES = {"gpt-5.4-mini": 0.075, "gpt-6-luna": 0.01}
CACHE_WRITE_PRICES = {"gpt-5.4-mini": 0.75, "gpt-6-luna": 0.125}
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
INSTRUCTIONS = """직접 작성한 가상 뉴스 자료의 한국어 요약 시험이다. 실제 뉴스가 아니다.
주체·확정 사건·시점/대상 기간이 충분할 때만 selected=true로 판정한다.
미완성 조건이나 누락 기간을 추정하지 않는다. 부족하면 selected=false, summary_ko는 빈 문자열.
reason_ko는 한국어로 설명한다. source_id는 입력과 동일하게 유지한다.
evidence는 입력 text에서 그대로 가져온 연속 부분 문자열이다.
선정 시 summary_ko는 한국어로 작성하고 required_literals의 표기를 그대로 보존한다.
주체·수치·단위·대상 기간뿐 아니라 적용 범위(예: 업종 전반)와 확정/조건 표현도 보존한다.
보류 이유는 실제로 누락되거나 잘린 부분만 설명한다. 이미 주어진 날짜·값을 없다고 쓰지 않는다.
기사 외부 지식·가격 전망·투자 권유·추정 인과관계를 덧붙이지 않는다."""


class Summary(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    selected: bool
    reason_ko: str
    summary_ko: str
    source_id: str
    evidence: str


def checks(
    source_id: str,
    source_text: str,
    required_literals: tuple[str, ...],
    result: Summary,
    expected_selected: bool | None = None,
) -> dict[str, bool]:
    def korean(text: str) -> bool:
        return bool(re.search(r"[가-힣]", text))

    numbers = re.findall(r"\d+(?:\.\d+)?", result.summary_ko)
    checks = {
        "source_id_matches": result.source_id == source_id,
        "evidence_present": bool(result.evidence.strip())
        and result.evidence in source_text,
        "korean_reason": korean(result.reason_ko),
        "korean_summary": not result.selected or korean(result.summary_ko),
        "held_summary_empty": result.selected or result.summary_ko == "",
        "required_facts_present": not result.selected
        or all(
            value in result.evidence and value in result.summary_ko
            for value in required_literals
        ),
        "no_new_numbers": all(value in source_text for value in numbers),
    }
    if expected_selected is not None:
        checks["selection_matches_expected"] = result.selected == expected_selected
    return checks


def usage_cost_usd(usage: dict, model: str) -> float:
    """응답 usage의 캐시 읽기·쓰기까지 포함한 공시 단가 기준 추정액."""
    if model not in MODEL_PRICES:
        raise ValueError("지원하지 않는 비교 모델입니다.")
    if (
        any(
            type(usage.get(key)) is not int or usage[key] < 0
            for key in ("input_tokens", "output_tokens", "total_tokens")
        )
        or usage["total_tokens"] != usage["input_tokens"] + usage["output_tokens"]
    ):
        raise ValueError("사용량이 유효하지 않습니다.")
    details = usage.get("input_tokens_details") or {}
    if not isinstance(details, dict):
        raise TypeError("입력 토큰 상세가 유효하지 않습니다.")
    cached = details.get("cached_tokens", 0)
    written = details.get("cache_write_tokens", 0)
    if (
        type(cached) is not int
        or type(written) is not int
        or cached < 0
        or written < 0
        or cached + written > usage["input_tokens"]
    ):
        raise ValueError("캐시 토큰 상세가 유효하지 않습니다.")
    standard = usage["input_tokens"] - cached - written
    input_price, output_price = MODEL_PRICES[model]
    return round(
        (
            standard * input_price
            + cached * CACHED_INPUT_PRICES[model]
            + written * CACHE_WRITE_PRICES[model]
            + usage["output_tokens"] * output_price
        )
        / 1e6,
        10,
    )


def analyze_synthetic(
    client,
    *,
    source_id: str,
    source_text: str,
    required_literals: tuple[str, ...] = (),
    model: str = DEFAULT_MODEL,
    expected_selected: bool | None = None,
) -> dict:
    """가상 입력만 전달한다. 완료+기계검사도 인간 검토를 대체하지 않는다."""
    if model not in MODEL_PRICES:
        raise ValueError("지원하지 않는 비교 모델입니다.")
    if (
        not source_id
        or not source_text
        or any(not value for value in required_literals)
    ):
        raise ValueError("가상 입력·필수 표현이 비어 있습니다.")
    report = {
        "observed_at_utc": datetime.now(UTC).isoformat(),
        "model": model,
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
        raw = client.responses.with_raw_response.parse(
            model=model,
            instructions=INSTRUCTIONS,
            input=json.dumps(
                {
                    "source_id": source_id,
                    "text": source_text,
                    "required_literals": required_literals,
                },
                ensure_ascii=False,
            ),
            text_format=Summary,
            store=False,
            reasoning={"effort": "none"},
            max_output_tokens=MAX_OUTPUT_TOKENS,
            tools=[],
        )
        usage = raw.http_response.json().get("usage")
        report["usage"] = usage
        valid_usage = isinstance(usage, dict) and all(
            type(usage.get(key)) is int and usage[key] >= 0
            for key in ("input_tokens", "output_tokens", "total_tokens")
        )
        if valid_usage:
            valid_usage = (
                usage["total_tokens"] == usage["input_tokens"] + usage["output_tokens"]
            )
        if not valid_usage:
            report["error_type"] = "MissingOrInvalidUsage"
        else:
            report["cost_usd"] = usage_cost_usd(usage, model)
            response = raw.parse()
            report["response_model"] = response.model
            report["response_status"] = response.status
            result = response.output_parsed
            if response.status == "completed" and result is not None:
                report.update(result.model_dump())
                report["checks"] = checks(
                    source_id,
                    source_text,
                    required_literals,
                    result,
                    expected_selected,
                )
                if all(report["checks"].values()):
                    report["status"] = "mechanical_checks_passed"
    except APIError as exc:
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
        report["error_type"] = type(exc).__name__
    report["latency_seconds"] = round(time.perf_counter() - started, 3)
    return report
