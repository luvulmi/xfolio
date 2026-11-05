"""제목 기반 중요도 v1. 점수는 시장 영향의 규칙값이며 수익률 예측이 아니다."""

import re

from pydantic import Field

from xfolio.news_contracts import Contract

VERSION = "market_impact_v1:2026-11-05"
RULES = (
    (
        "systemic_risk",
        100,
        r"\b(?:financial crisis|bank(?:ing)? crisis|bank failure|market crash|trading halt|debt default|emergency rate)\b",
    ),
    (
        "monetary_policy",
        95,
        r"\b(?:fomc|federal funds|interest.rate decision|fed(?:eral reserve)? (?:cuts?|raises?|holds?|keeps?|hikes?)|federal reserve.*(?:rates?|statement))\b",
    ),
    (
        "inflation",
        90,
        r"\b(?:cpi|pce|inflation|consumer price index|personal income and outlays)\b",
    ),
    (
        "employment",
        85,
        r"\b(?:nonfarm|payrolls?|unemployment|jobs report|employment situation)\b",
    ),
    ("growth", 80, r"\b(?:gdp|gross domestic product|recession|economic growth)\b"),
    (
        "government_policy",
        75,
        r"\b(?:tariffs?|sanctions?|export (?:ban|controls?)|trade war|fiscal stimulus|debt ceiling|midterms?)\b",
    ),
    (
        "major_company_results",
        60,
        r"\b(?:apple|microsoft|nvidia|amazon|alphabet|google|meta|tesla|broadcom)\b.*\b(?:earnings|results|guidance|profit|revenue)\b|\b(?:earnings|results|guidance)\b.*\b(?:apple|microsoft|nvidia|amazon|alphabet|google|meta|tesla|broadcom)\b",
    ),
    (
        "broad_market",
        50,
        r"\b(?:s&p\s*500|nasdaq|dow jones|wall street|us stocks|u\.s\. stocks|treasury yields?|treasuries)\b",
    ),
)


class Importance(Contract):
    score: int = Field(ge=0, le=100)
    reasons: tuple[str, ...] = Field(min_length=1)
    version: str = VERSION


def assess(title: str, *, official=False) -> Importance:
    matches = [
        (code, weight)
        for code, weight, pattern in RULES
        if re.search(pattern, title, re.IGNORECASE)
    ]
    reasons = tuple(code for code, _ in matches) or ("other_market_news",)
    score = max((weight for _, weight in matches), default=20)
    if official:
        score = min(100, score + 5)
        reasons += ("official_primary_source",)
    return Importance(score=score, reasons=reasons)
