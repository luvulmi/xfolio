"""가상 자료의 아침 dry_run 미리보기. 외부 AI·게시 호출은 하지 않는다."""

import hashlib
import json
import re
import unicodedata
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from xfolio.market import INDICES, completed_sessions, display_number
from xfolio.models import MarketSnapshot
from xfolio.news_models import NewsCollection

KST = ZoneInfo("Asia/Seoul")
URL = re.compile(r"https?://[^\s]+")


class NewsSelection(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    article_id: str
    summary_ko: str = Field(min_length=1)
    evidence: str = Field(min_length=1)


class PostPreview(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    text: str
    weighted_length_estimate: int
    source_ids: tuple[str, ...] = ()


class MorningPreview(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    preview_id: str
    input_version: str
    mode: Literal["dry_run"] = "dry_run"
    synthetic: Literal[True] = True
    can_publish: Literal[False] = False
    status: Literal["ready", "held"]
    information_cutoff: AwareDatetime
    prepared_at: AwareDatetime
    posts: tuple[PostPreview, ...] = ()
    reasons: tuple[str, ...] = ()
    evidence: tuple[dict, ...] = ()
    length_notice: str = "가중 길이 참고값이며 실제 게시 승인이 아닙니다."


def weighted_length_estimate(text: str) -> int:
    """NFC·일반 한글·공백 구분 URL의 참고값. 공식 twitter-text 파서가 아니다."""
    normalized = unicodedata.normalize("NFC", text)
    urls = list(URL.finditer(normalized))
    characters = URL.sub("", normalized)
    return len(urls) * 23 + sum(
        1
        if (
            ord(char) <= 0x10FF
            or 0x2000 <= ord(char) <= 0x200D
            or 0x2010 <= ord(char) <= 0x201F
            or 0x2032 <= ord(char) <= 0x2037
        )
        else 2
        for char in characters
    )


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def build_morning_preview(
    *,
    market: MarketSnapshot | None,
    news: NewsCollection,
    selection: NewsSelection | None,
    information_cutoff: datetime,
    prepared_at: datetime,
) -> MorningPreview:
    """가상 fixture만 허용한다. ready는 게시 승인이나 사실 검토 합격을 뜻하지 않는다."""
    if any(t.utcoffset() is None for t in (information_cutoff, prepared_at)):
        raise ValueError("미리보기 시각에는 시간대가 필요합니다.")
    cutoff = information_cutoff.astimezone(UTC)
    prepared = prepared_at.astimezone(UTC)
    source_input = {
        "market": market.model_dump(mode="json") if market else None,
        "news": news.model_dump(mode="json"),
        "selection": selection.model_dump(mode="json") if selection else None,
        "cutoff": cutoff.isoformat(),
    }
    input_version = _digest(source_input)
    reasons = []
    if prepared < cutoff:
        reasons.append("작성 시각이 정보 기준보다 이릅니다.")
    if not news.checkpoint_eligible or any(
        report.status != "complete" or report.error is not None
        for report in news.query_reports
    ):
        reasons.append("뉴스 수집이 불완전하거나 실패해 전체 보류합니다.")
    if news.window_end != cutoff or news.collected_at > prepared:
        reasons.append("뉴스 수집 범위 또는 완료 시각이 정보 기준과 맞지 않습니다.")
    if any(article.provider != "synthetic" for article in news.articles):
        reasons.append("실기사의 AI·공개·보관 조건 미확인: 가상 미리보기만 허용합니다.")
    if market is None:
        reasons.append("필수 두 지수가 없습니다.")
    else:
        by_id = {index.index_id: index for index in market.indices}
        if set(by_id) != {spec.index_id for spec in INDICES}:
            reasons.append("필수 두 지수가 없거나 중복입니다.")
        else:
            for spec in INDICES:
                index = by_id[spec.index_id]
                previous, day, close_at = completed_sessions(cutoff, spec.calendar)
                change = ((index.close / index.previous_close - 1) * 100).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )
                if (
                    index.symbol != spec.symbol
                    or index.trade_date != day
                    or market.trade_date != day
                    or index.previous_trade_date != previous
                    or index.market_closed_at != close_at
                    or not close_at <= index.retrieved_at <= prepared
                    or index.change_pct != change
                    or market.as_of > cutoff
                ):
                    reasons.append(
                        "지수 거래일·종가·등락률·수집 시각 대조에 실패했습니다."
                    )
                    break
    evidence = []
    news_post = None
    exclusion = None
    if selection is not None:
        article = next(
            (a for a in news.articles if a.article_id == selection.article_id), None
        )
        if article is None:
            reasons.append("선정 뉴스의 출처 ID가 수집 결과에 없습니다.")
        elif (
            not news.window_start <= article.published_at <= cutoff
            or not article.published_at <= article.retrieved_at <= cutoff
            or not any(
                selection.evidence in text
                for text in (article.description, article.snippet)
            )
            or not re.search(r"[가-힣]", selection.summary_ko)
        ):
            reasons.append("선정 뉴스의 기준 전 근거·시각·한국어 대조에 실패했습니다.")
        else:
            text = (
                f"[가상 예시] 주요 뉴스\n{selection.summary_ko}\n"
                f"출처: {article.source}\n{article.url}"
            )
            length = weighted_length_estimate(text)
            if length > 280:
                exclusion = "뉴스가 280가중 길이를 넘어 제외됐습니다."
            else:
                news_post = PostPreview(
                    text=text,
                    weighted_length_estimate=length,
                    source_ids=(article.article_id,),
                )
                evidence.append(
                    {
                        "article_id": article.article_id,
                        "quote": selection.evidence,
                        "published_at": article.published_at.isoformat(),
                        "retrieved_at": article.retrieved_at.isoformat(),
                        "url": str(article.url),
                        "notice": "직접 작성한 가상 근거. 부분 문자열 대조만 수행했습니다.",
                    }
                )
    posts = []
    if not reasons:
        by_id = {index.index_id: index for index in market.indices}
        lines = [f"[가상 예시] 미국 증시 {market.trade_date:%m/%d} 마감"]
        for spec in INDICES:
            index = by_id[spec.index_id]
            close = format(Decimal(display_number(index.close)), ",.2f")
            change = display_number(index.change_pct)
            if index.change_pct > 0:
                change = "+" + change
            lines.append(f"{spec.name} {close} ({change}%)")
        lines.append("출처: 가상 시세")
        lines.append(
            f"기준 {cutoff.astimezone(KST):%m/%d %H:%M}·"
            f"작성 {prepared.astimezone(KST):%H:%M} KST"
        )
        if news_post is None:
            lines.append("이번 수집 범위 내 선정 뉴스 없음")
        index_text = "\n".join(lines)
        length = weighted_length_estimate(index_text)
        if length > 280:
            reasons.append("필수 지수 정보가 280가중 길이를 넘었습니다.")
        else:
            posts.append(PostPreview(text=index_text, weighted_length_estimate=length))
            if news_post:
                posts.append(news_post)
    if reasons:
        posts, evidence = [], []
    payload = {
        "input_version": input_version,
        "prepared_at": prepared.isoformat(),
        "posts": [p.model_dump() for p in posts],
        "reasons": reasons,
        "exclusion": exclusion,
    }
    return MorningPreview(
        preview_id=_digest(payload),
        input_version=input_version,
        status="held" if reasons else "ready",
        information_cutoff=cutoff,
        prepared_at=prepared,
        posts=tuple(posts),
        reasons=tuple(reasons or ([exclusion] if exclusion else [])),
        evidence=tuple(evidence),
        length_notice="NFC·한글·URL 기준 참고값. 공식 파서·실제 전송 검증 전입니다.",
    )
