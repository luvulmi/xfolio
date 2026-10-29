"""BLS CPI 두 주장 전용 의미·완성 글 검사. 범용 뉴스/이모지 판정기가 아니다."""

import re
import unicodedata
from itertools import product
from zoneinfo import ZoneInfo

from xfolio.bls import RELEASE_URL

PROFILE = "bls_cpi_v1"
BASES = {
    "previous_month_seasonally_adjusted": "전월 대비(계절조정)",
    "12_months_unadjusted": "전년 동월 대비(비계절조정)",
}


class DraftValidationError(ValueError):
    """원문·응답·비밀을 포함하지 않는 검증 실패 코드."""


def cpi_claim_contract(claims, period):
    if (
        len(claims) != 2
        or {claim.comparison_basis for claim in claims} != set(BASES)
        or not re.fullmatch(r"\d{4}-(?:0[1-9]|1[0-2])", period)
    ):
        raise DraftValidationError("UNSUPPORTED_CLAIM")
    required = []
    for index, claim in enumerate(claims):
        if (
            claim.certainty != "confirmed"
            or claim.subject != "US:CPI-U:all_items"
            or claim.event_type != "cpi_release"
            or claim.unit != "percent"
            or not claim.value
            or not re.fullmatch(r"\d+(?:\.\d+)?", claim.value)
            or claim.period != period
            or claim.conditions
            or claim.action not in {"increased", "decreased"}
        ):
            raise DraftValidationError("UNSUPPORTED_CLAIM")
        required.append(
            {
                "claim_id": f"claim-{index}",
                "required_literals": [
                    "미국 CPI-U",
                    period,
                    claim.value + "%",
                    "상승" if claim.action == "increased" else "하락",
                    BASES[claim.comparison_basis],
                ],
                "evidence_span": claim.evidence_span,
            }
        )
    return required


def claim_text_choices(contract):
    subject, period, value, direction, basis = contract["required_literals"]
    return (
        f"{subject} {period} {basis} {value} {direction}",
        f"{subject} {period} {value} {direction} {basis}",
    )


def cpi_post_text(claim_texts, published_at):
    day = published_at.astimezone(ZoneInfo("America/New_York")).date().isoformat()
    return (
        f"발표일(미국 동부) {day}. "
        + ". ".join(claim_texts)
        + ". 출처: BLS "
        + RELEASE_URL
    )


def cpi_weighted_length(text):
    """NFC, ASCII=1·완성 한글=2·고정 BLS URL=23. 다른 문자는 거절한다.

    twitter-text v3의 이 문형 부분집합만 지원한다. 일반 URL 인식·이모지
    시퀀스를 잘못 세어 합격시키지 않으며 다른 입력에는 사용할 수 없다.
    """
    text = unicodedata.normalize("NFC", text)
    if text.count(RELEASE_URL) != 1 or not text.endswith(" " + RELEASE_URL):
        raise DraftValidationError("UNSUPPORTED_POST_URL")
    body = text[: -len(RELEASE_URL)]
    if "http" in body or "www." in body:
        raise DraftValidationError("UNSUPPORTED_POST_URL")
    if any(not (32 <= ord(c) <= 126 or 0xAC00 <= ord(c) <= 0xD7A3) for c in body):
        raise DraftValidationError("UNSUPPORTED_TEXT_CHARACTER")
    return sum(1 if ord(c) <= 126 else 2 for c in body) + 23


def validate_cpi_generation(output, required, published_at):
    texts = [unicodedata.normalize("NFC", claim.text_ko) for claim in output.claims]
    for text, contract in zip(texts, required, strict=True):
        if text not in claim_text_choices(contract):
            raise DraftValidationError("OUTPUT_SEMANTIC_MISMATCH")
    text = cpi_post_text(texts, published_at)
    length = cpi_weighted_length(text)
    if length > 280:
        raise DraftValidationError("X_WEIGHTED_LENGTH_EXCEEDED")
    return text, length


def validate_stored_cpi_post(text, claims, period, published_at):
    contracts = cpi_claim_contract(claims, period)
    normalized = unicodedata.normalize("NFC", text)
    if normalized != text or text not in {
        cpi_post_text(parts, published_at)
        for parts in product(*(claim_text_choices(c) for c in contracts))
    }:
        raise DraftValidationError("OUTPUT_SEMANTIC_MISMATCH")
    length = cpi_weighted_length(text)
    if length > 280:
        raise DraftValidationError("X_WEIGHTED_LENGTH_EXCEEDED")
    return length
