"""검사를 통과한 가격·뉴스의 Telegram 표시. 원본 데이터/선정 로직과 분리."""

from dataclasses import dataclass
from datetime import datetime, timedelta

from xfolio.domestic.calendar import KST
from xfolio.domestic.models import CloseQuote
from xfolio.jobs.telegram import text_units


def one_line(value):
    return " ".join(value.split())


@dataclass(frozen=True)
class PriceRow:
    name: str
    quote: CloseQuote | None
    corrected: bool = False


@dataclass(frozen=True)
class StoryRow:
    title: str
    publisher: str
    published_at: datetime
    kind: str
    url: str
    summary_ko: str | None = None
    title_ko: str | None = None
    translation_requested: bool = False


@dataclass(frozen=True)
class RenderedMessage:
    text: str
    entities: tuple[dict, ...]


class _Message:
    def __init__(self):
        self.lines, self.entities, self.units = [], [], 0

    def line(self, text="", *, bold=False, url=None):
        text = one_line(text)
        if self.lines:
            self.units += 1
        start = self.units
        if url is not None:
            prefix = text + " · "
            self.entities.append(
                {
                    "type": "text_link",
                    "offset": start + text_units(prefix),
                    "length": text_units("원문 보기"),
                    "url": url,
                }
            )
            text = prefix + "원문 보기"
        if bold:
            self.entities.append(
                {"type": "bold", "offset": start, "length": text_units(text)}
            )
        self.lines.append(text)
        self.units += text_units(text)

    def finish(self):
        return RenderedMessage("\n".join(self.lines), tuple(self.entities))


def render_morning(
    *,
    day,
    send_at,
    frozen_at,
    prices,
    stories,
    news_status,
    normal_zero,
    synthetic=False,
    preview=False,
    acceptance=False,
    reused=False,
):
    message = _Message()
    local = send_at.astimezone(KST)
    weekday = "월화수목금토일"[day.weekday()]
    message.line(f"☀️ XFolio | {day:%m.%d}({weekday}) {local:%H:%M}", bold=True)
    if reused:
        message.line(f"형식 확인 · {day:%m.%d} {local:%H:%M} 수신 자료 재사용")
    elif synthetic:
        message.line("시험 미리보기 · 합성 자료")
    elif preview:
        message.line("시험 미리보기")
    elif acceptance:
        message.line("본인 전송 시험")
    available = [row.quote for row in prices if row.quote is not None]
    trade_date = available[0].latest.trade_date if available else None
    message.line(
        f"국내 ETF 종가 · {trade_date:%m.%d} 정규장 기준"
        if trade_date
        else "국내 ETF 종가 · 확인 불가"
    )
    for row in prices:
        if row.quote is None:
            message.line(f"{row.name} · 종가 확인 불가")
            continue
        quote = row.quote
        price = f"{quote.latest.close:,.4f}".rstrip("0").rstrip(".")
        change = None if row.corrected else quote.change_pct
        percent = f"{change:+.2f}%" if change is not None else "등락률 확인 불가"
        suffix = " · 정정 가격" if row.corrected else ""
        message.line(f"{row.name} {price}원 | {percent}{suffix}")
    if not available:
        message.line("⚠️ 가격 데이터 장애")
    kind = None
    for index, story in enumerate(stories, 1):
        message.line()
        if story.kind != kind:
            message.line(
                "📌 공식 발표 · AI 요약"
                if story.kind == "official"
                else "📰 일반 뉴스",
                bold=True,
            )
            kind = story.kind
        if story.title_ko:
            message.line(f"{index}. {story.title_ko}", bold=True)
            message.line(f"({story.title})")
        elif story.translation_requested:
            message.line(f"{index}. 제목 번역 확인 불가", bold=True)
            message.line(f"({story.title})")
        else:
            message.line(f"{index}. {story.title}", bold=True)
        if story.kind == "official":
            message.line(f"AI 요약: {story.summary_ko}")
        published = story.published_at.astimezone(KST)
        old = (
            " · 24시간 이전 발행 보완"
            if story.published_at < frozen_at - timedelta(hours=24)
            else ""
        )
        message.line(
            f"{story.publisher} · {published:%m.%d %H:%M} KST{old}", url=story.url
        )
    if not stories:
        message.line()
        message.line("📰 뉴스", bold=True)
        if normal_zero:
            message.line("적격 뉴스 없음")
        elif news_status == "complete":
            message.line("검사를 통과한 뉴스 없음")
    if news_status == "failed":
        message.line("⚠️ 뉴스 수집 실패")
    elif news_status == "partial":
        message.line("⚠️ 뉴스 수집 일부 실패 · 확인된 자료만 포함")
    message.line()
    if available:
        retrieved = sorted(
            q.retrieved_at.astimezone(KST).strftime("%H:%M") for q in available
        )
        clock = (
            retrieved[0]
            if retrieved[0] == retrieved[-1]
            else retrieved[0] + "~" + retrieved[-1]
        )
        message.line(f"가격 출처 KIS · 조회 {clock} KST")
        message.line("비수정 종가 · 가격 등락률 기준")
        if any(
            q.change_reason == "price_change_excludes_distribution" for q in available
        ):
            message.line("※ 분배락: 분배금을 포함하지 않은 가격 변동률")
    message.line(f"뉴스 기준 {frozen_at.astimezone(KST):%H:%M} KST")
    return message.finish()
