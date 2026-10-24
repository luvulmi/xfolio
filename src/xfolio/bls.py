"""BLS CPI HTML 도입 어댑터. 첫 설명문만 추출하며 표/PDF는 지원하지 않는다."""

import re
from datetime import UTC, datetime
from html.parser import HTMLParser
from zoneinfo import ZoneInfo

import httpx
from pydantic import AwareDatetime

from xfolio.news_contracts import (
    Contract,
    EvidenceBundle,
    EvidenceClaim,
    NewsEvent,
    SourceRecord,
    digest,
)

RELEASE_URL = "https://www.bls.gov/news.release/cpi.htm"
SCHEDULE_URL = "https://www.bls.gov/schedule/news_release/cpi.htm"
EASTERN = ZoneInfo("America/New_York")
MONTHS = {
    m.lower(): i
    for i, m in enumerate(
        (
            "January",
            "February",
            "March",
            "April",
            "May",
            "June",
            "July",
            "August",
            "September",
            "October",
            "November",
            "December",
        ),
        1,
    )
}


class BLSError(ValueError):
    """안정적인 오류 코드만 노출한다."""


class _HTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.pre, self.in_pre, self.blocks = [], False, []
        self.in_table, self.in_cell, self.cell = False, False, []
        self.row, self.rows = [], []

    def handle_starttag(self, tag, attrs):
        if tag == "pre":
            self.in_pre, self.pre = True, []
        if tag == "br" and self.in_pre:
            self.pre.append("\n")
        if tag == "table" and "release-list" in dict(attrs).get("class", "").split():
            self.in_table = True
        if self.in_table and tag == "tr":
            self.row = []
        if self.in_table and tag == "td":
            self.in_cell, self.cell = True, []

    def handle_data(self, data):
        if self.in_pre:
            self.pre.append(data)
        if self.in_cell:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag == "pre" and self.in_pre:
            self.blocks.append("".join(self.pre))
            self.in_pre = False
        if tag == "td" and self.in_cell:
            self.row.append(" ".join("".join(self.cell).split()))
            self.in_cell = False
        if tag == "tr" and self.in_table and self.row:
            self.rows.append(self.row)
            self.row = []
        if tag == "table":
            self.in_table = False


class ScheduledRelease(Contract):
    period: str
    scheduled_at: AwareDatetime


def _month(value):
    value = value.lower().rstrip(".")
    matches = [n for name, n in MONTHS.items() if name == value or name[:3] == value]
    if len(matches) != 1:
        raise BLSError("unknown_month")
    return matches[0]


def _eastern(year, month, day, hour, minute, ampm):
    hour, minute = int(hour), int(minute)
    if not 1 <= hour <= 12 or not 0 <= minute <= 59:
        raise BLSError("invalid_release_time")
    hour = hour % 12 + (12 if ampm.lower().replace(".", "") == "pm" else 0)
    return datetime(
        int(year), _month(month), int(day), hour, minute, tzinfo=EASTERN
    ).astimezone(UTC)


def parse_schedule(html: str) -> tuple[ScheduledRelease, ...]:
    parser = _HTML()
    parser.feed(html)
    result = []
    for row in parser.rows:
        if len(row) != 3:
            raise BLSError("invalid_schedule_row")
        period = re.fullmatch(r"([A-Za-z]+) (\d{4})", row[0])
        day = re.fullmatch(r"([A-Za-z.]+) (\d{1,2}), (\d{4})", row[1])
        clock = re.fullmatch(r"(\d{1,2}):(\d{2}) (AM|PM)", row[2])
        if not all((period, day, clock)):
            raise BLSError("invalid_schedule_row")
        result.append(
            ScheduledRelease(
                period=f"{period[2]}-{_month(period[1]):02d}",
                scheduled_at=_eastern(
                    day[3], day[1], day[2], clock[1], clock[2], clock[3]
                ),
            )
        )
    if not result or len({r.period for r in result}) != len(result):
        raise BLSError("missing_or_duplicate_schedule")
    return tuple(result)


def parse_release(html: str, *, retrieved_at: datetime, run_id: str) -> EvidenceBundle:
    if retrieved_at.utcoffset() is None:
        raise BLSError("timezone_required")
    parser = _HTML()
    parser.feed(html)
    if not parser.blocks:
        raise BLSError("missing_release_body")
    # 문단 경계는 유지하고 HTML의 시각적 줄바꿈만 정규화한다.
    paragraphs = [
        " ".join(p.split()) for p in re.split(r"\n\s*\n", parser.blocks[0]) if p.strip()
    ]
    text = "\n\n".join(paragraphs)
    stamp = re.search(
        r"embargoed until\s+(\d{1,2}):(\d{2})\s+(a\.m\.|p\.m\.)\s+\(ET\)\s+(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s+([A-Za-z]+)\s+(\d{1,2}),\s+(\d{4})",
        text,
    )
    title = re.search(r"CONSUMER PRICE INDEX\s*-\s*([A-Z]+) (\d{4})", text)
    release_id = re.search(r"USDL-\d{2}-\d+", text)
    if not all((stamp, title, release_id)):
        raise BLSError("missing_release_identity_or_time")
    published = _eastern(stamp[7], stamp[5], stamp[6], stamp[1], stamp[2], stamp[3])
    if published.astimezone(EASTERN).strftime("%A") != stamp[4]:
        raise BLSError("weekday_mismatch")
    if published > retrieved_at:
        raise BLSError("not_released")
    period = f"{title[2]}-{_month(title[1]):02d}"
    source_id = "BLS:CPI:" + release_id[0]
    source = SourceRecord(
        provider="BLS",
        source_id=source_id,
        source_url=RELEASE_URL,
        published_at=published,
        retrieved_at=retrieved_at,
        timestamp_precision="minute",
        content_version=digest(text),
        permission_scope="bls_public_text",
        collection_run_id=run_id,
        text=text,
        text_scope="CPI first PRE narrative; tables excluded",
    )
    claims = []
    opening = next(
        (
            p
            for p in paragraphs
            if p.startswith("The Consumer Price Index for All Urban Consumers (CPI-U)")
        ),
        "",
    )
    monthly = re.search(
        r"\(CPI-U\) (increased|decreased) (\d+(?:\.\d+)?) percent on a seasonally adjusted basis in ([A-Za-z]+)",
        opening,
    )
    annual = re.search(
        r"Over the last 12 months, the all items index (increased|decreased) (\d+(?:\.\d+)?) percent before seasonal adjustment\.",
        opening,
    )
    if monthly and annual and _month(monthly[3]) == _month(title[1]):
        for match, basis in (
            (monthly, "previous_month_seasonally_adjusted"),
            (annual, "12_months_unadjusted"),
        ):
            claims.append(
                EvidenceClaim(
                    source_id=source_id,
                    content_version=source.content_version,
                    subject="US:CPI-U:all_items",
                    event_type="cpi_release",
                    action=match[1],
                    certainty="confirmed",
                    period=period,
                    value=match[2],
                    unit="percent",
                    comparison_basis=basis,
                    evidence_span=opening,
                )
            )
    # 추출 성공이어도 정정/일정/선정은 사람이 확인하는 초기 구현이다.
    event = NewsEvent(
        subject_id="US:CPI-U",
        event_type="cpi_release",
        period_or_transaction=period,
        claims=tuple(claims),
        reason_codes=("semantic_review_required",)
        if claims
        else ("unsupported_narrative",),
    )
    return EvidenceBundle(source=source, event=event)


def fetch_html(client: httpx.Client, url: str) -> str:
    if url not in (RELEASE_URL, SCHEDULE_URL):
        raise BLSError("unsupported_url")
    try:
        response = client.get(
            url,
            headers={"User-Agent": "XFolio-Research/1.0"},
            timeout=20,
            follow_redirects=False,
        )
    except httpx.RequestError:
        raise BLSError("transport_error") from None
    if response.status_code != 200:
        raise BLSError(f"http_{response.status_code}")
    if "text/html" not in response.headers.get("content-type", ""):
        raise BLSError("unexpected_content_type")
    return response.text


def inspect_bls(*, client: httpx.Client, run_id: str, now=None):
    """최신 CPI와 미래 일정의 진단 스냅샷. 과거 창 완주/커서 전진이 아니다."""
    schedule = parse_schedule(fetch_html(client, SCHEDULE_URL))
    html = fetch_html(client, RELEASE_URL)
    now = now or datetime.now(UTC)
    bundle = parse_release(html, retrieved_at=now, run_id=run_id)
    overdue = [
        s
        for s in schedule
        if s.scheduled_at <= now and s.period > bundle.event.period_or_transaction
    ]
    report = {
        "run_id": run_id,
        "observed_at": now.isoformat(),
        "requests": 2,
        "state": "expected_release_missing" if overdue else "snapshot_parsed",
        "published_at": bundle.source.published_at.isoformat(),
        "period": bundle.event.period_or_transaction,
        "content_version": bundle.source.content_version,
        "claims": [
            c.model_dump(mode="json", exclude={"evidence_span"})
            for c in bundle.event.claims
        ],
        "schedule": [s.model_dump(mode="json") for s in schedule],
        "cursor_advanced": False,
        "can_publish": False,
    }
    return bundle, report
