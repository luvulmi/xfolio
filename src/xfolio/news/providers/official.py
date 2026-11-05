"""공식 자체 발표의 제한 형식 수집. 피드/본문 불일치·모르는 형식은 보류한다."""

import re
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, DecimalException
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from urllib.parse import urlsplit

import httpx

from xfolio.news.collection import Fact, NewsError, NewsItem, SourceResult, aware
from xfolio.news.contracts import digest
from xfolio.news.providers.bls import EASTERN, MONTHS, RELEASE_URL, parse_release

FEEDS = {
    "BEA": "https://apps.bea.gov/rss/rss.xml",
    "Board": "https://www.federalreserve.gov/feeds/press_monetary.xml",
}


def official_url(provider, url):
    try:
        p = urlsplit(url)
        if (
            p.scheme != "https"
            or p.username
            or p.password
            or p.port not in (None, 443)
            or p.query
            or p.fragment
            or "\\" in url
            or any(ord(c) <= 32 for c in url)
        ):
            return False
        if provider == "BLS":
            return p.hostname == "www.bls.gov" and p.path in (
                "/news.release/cpi.htm",
                "/news.release/empsit.nr0.htm",
            )
        if provider == "BEA":
            return p.hostname == "www.bea.gov" and bool(
                re.fullmatch(
                    r"/news/\d{4}/(?:gdp|gross-domestic-product|personal-income-and-outlays)[a-z0-9-]*",
                    p.path,
                )
            )
        return (
            provider == "Board"
            and p.hostname == "www.federalreserve.gov"
            and bool(
                re.fullmatch(r"/newsevents/pressreleases/monetary\d{8}a.htm", p.path)
            )
        )
    except (ValueError, TypeError):
        return False


def fetch(client, url, *, xml=False):
    try:
        with client.stream(
            "GET",
            url,
            headers={"User-Agent": "XFolio/0.1 personal research"},
            timeout=20,
            follow_redirects=False,
        ) as response:
            if response.status_code != 200:
                raise NewsError("http_" + str(response.status_code))
            content_type = response.headers.get("content-type", "").lower()
            if (xml and not any(x in content_type for x in ("xml", "rss"))) or (
                not xml and "text/html" not in content_type
            ):
                raise NewsError("unexpected_content_type")
            raw = b""
            for chunk in response.iter_bytes():
                raw += chunk
                if len(raw) > (1_000_000 if xml else 2_000_000):
                    raise NewsError("response_limit")
            return raw.decode("utf-8-sig", errors="strict")
    except (httpx.HTTPError, UnicodeError):
        raise NewsError("transport_or_encoding") from None


def feed_entries(xml, provider):
    if "<!DOCTYPE" in xml.upper() or "<!ENTITY" in xml.upper():
        raise NewsError("unsafe_feed")
    try:
        root = ET.fromstring(xml)
        if root.tag != "rss" or root.find("channel") is None:
            raise NewsError("feed_schema")
        result = []
        for item in root.findall("./channel/item"):
            title, url, stamp = (
                item.findtext(k) or "" for k in ("title", "link", "pubDate")
            )
            supported = (
                bool(
                    re.match(
                        r"(?:GDP \(|Gross Domestic Product,|Personal Income and Outlays,)",
                        title,
                        re.IGNORECASE,
                    )
                )
                if provider == "BEA"
                else title.strip() == "Federal Reserve issues FOMC statement"
            )
            if not supported:
                continue
            # RFC date에 명시된 EDT/EST도 숫자 UTC offset으로 변환한다.
            stamp = re.sub(r"\bEDT$", "-0400", stamp.strip())
            stamp = re.sub(r"\bEST$", "-0500", stamp)
            published = aware(parsedate_to_datetime(stamp))
            result.append((title.strip(), url, published))
        return result
    except (ET.ParseError, ValueError, TypeError, AttributeError):
        raise NewsError("feed_schema_or_time") from None


class Body(HTMLParser):
    """기관 본문 div의 문단·h1·시각만. 표·스크립트·주변 탐색은 제외."""

    def __init__(self, provider):
        super().__init__(convert_charrefs=True)
        self.provider, self.stack, self.parts = provider, [], []
        self.paragraphs, self.headings, self.dates = [], [], []
        self.rights_text = []
        self.target_depth = None
        self.capture = None
        self.suppressed = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ("meta", "link", "img", "br", "hr", "input", "source", "wbr"):
            if tag == "br" and self.capture:
                self.parts.append(" ")
            return
        self.stack.append(tag)
        cls = attrs.get("class", "").split()
        if self.target_depth is None and (
            (self.provider == "BEA" and "field--name-body" in cls)
            or (
                self.provider == "Board"
                and {"col-xs-12", "col-sm-8", "col-md-8"} <= set(cls)
                and "heading" not in cls
            )
        ):
            self.target_depth = len(self.stack)
        if tag in ("script", "style", "table"):
            self.suppressed += 1
        if self.suppressed:
            return
        date = (
            "field--name-field-release-date" in cls
            or "releaseTime" in cls
            or "article__time" in cls
        )
        heading = tag == "h1" or (tag == "h3" and "title" in cls)
        if date or heading or (self.target_depth is not None and tag == "p"):
            self.capture = (
                len(self.stack),
                "date" if date else "heading" if heading else "paragraph",
            )
            self.parts = []

    def handle_data(self, data):
        if self.target_depth is not None and not self.suppressed:
            self.rights_text.append(data)
        if self.capture and not self.suppressed:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if not self.stack or tag not in self.stack:
            return
        depth = len(self.stack) - self.stack[::-1].index(tag)
        if self.capture and depth <= self.capture[0]:
            value = " ".join("".join(self.parts).split())
            {
                "date": self.dates,
                "heading": self.headings,
                "paragraph": self.paragraphs,
            }[self.capture[1]].append(value)
            self.capture, self.parts = None, []
        if self.target_depth is not None and depth <= self.target_depth:
            self.target_depth = None
        if tag in ("script", "style", "table"):
            self.suppressed = max(0, self.suppressed - 1)
        self.stack = self.stack[: depth - 1]


def _fact(claim_id, span, text):
    return Fact(claim_id=claim_id, evidence_span=span, allowed_texts=(text,))


def _rate(value):
    # FOMC의 3-3/4, 3 3/4, 1/4, 소수 표기를 Decimal로 계산한다.
    value = value.strip()
    match = re.fullmatch(r"(?:(\d+)[ -])?(\d+)/(\d+)", value)
    try:
        if match:
            result = Decimal(match[1] or 0) + Decimal(match[2]) / Decimal(match[3])
        else:
            result = Decimal(value)
    except DecimalException:
        raise NewsError("invalid_target_rate") from None
    if not 0 <= result <= 30:
        raise NewsError("rate_out_of_range")
    return format(result.normalize(), "f")


def parse_official(html, *, provider, url, title, published_at, retrieved_at):
    if not official_url(provider, url):
        raise NewsError("unsupported_official_url")
    published_at, retrieved_at = aware(published_at), aware(retrieved_at)
    if published_at > retrieved_at:
        raise NewsError("publication_after_retrieval")
    parser = Body(provider)
    parser.feed(html)
    if parser.capture or parser.target_depth is not None:
        raise NewsError("truncated_body")
    text = "\n\n".join(parser.paragraphs)
    if not text or re.search(
        r"copyright|all rights reserved|used (?:with|by) permission|third.party|courtesy of",
        " ".join(parser.rights_text),
        re.IGNORECASE,
    ):
        raise NewsError("body_or_rights_unverified")
    date_text = " ".join(parser.dates)
    if not date_text:
        raise NewsError("page_time_missing")
    page_date = re.search(
        r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),?\s+(\d{4})",
        date_text,
    )
    if (
        not page_date
        or date(int(page_date[3]), MONTHS[page_date[1].lower()], int(page_date[2]))
        != published_at.astimezone(EASTERN).date()
    ):
        raise NewsError("feed_page_date_mismatch")
    clock = re.search(
        r"(\d{1,2}):(\d{2})\s*(a\.m\.|p\.m\.)\s*(EDT|EST)", date_text, re.IGNORECASE
    )
    local = published_at.astimezone(EASTERN)
    if not clock or (
        int(clock[1]) % 12 + (12 if clock[3].lower() == "p.m." else 0),
        int(clock[2]),
        clock[4].upper(),
    ) != (local.hour, local.minute, local.tzname()):
        raise NewsError("feed_page_time_mismatch")
    if provider == "Board":
        if "Federal Reserve issues FOMC statement" not in " ".join(parser.headings):
            raise NewsError("unsupported_statement")
        match = re.search(
            r"The Committee decided to (maintain|lower|raise) the target range for the federal funds rate (?:by [0-9 ./-]+ percentage points? )?(?:at|to) ([0-9 ./-]+?) to ([0-9 ./-]+?) percent",
            text,
        )
        if not match:
            raise NewsError("unsupported_fomc_facts")
        low, high = _rate(match[2]), _rate(match[3])
        if Decimal(low) > Decimal(high):
            raise NewsError("invalid_target_range")
        day = published_at.astimezone(EASTERN).date().isoformat()
        action = {"maintain": "유지", "lower": "인하", "raise": "인상"}[match[1]]
        facts = (
            _fact(
                "fomc_target",
                match[0],
                f"미국 FOMC는 {day} 발표에서 연방기금금리 목표 범위를 {low}~{high}%로 {action}하기로 결정했다.",
            ),
        )
        event = "FOMC:" + published_at.date().isoformat()
    elif "personal-income-and-outlays" in url:
        identity = re.search(
            r"Personal Income and Outlays, ([A-Za-z]+) (\d{4})",
            " ".join(parser.headings),
        )
        if not identity or identity[1].lower() not in MONTHS:
            raise NewsError("pce_period_missing")
        feed_identity = re.fullmatch(
            r"Personal Income and Outlays, ([A-Za-z]+) (\d{4})", title
        )
        if not feed_identity or feed_identity.groups() != identity.groups():
            raise NewsError("pce_title_body_mismatch")
        period = f"{identity[2]}년 {MONTHS[identity[1].lower()]}월"
        facts = []
        for label, pattern, basis in (
            (
                "pce_month",
                r"From the preceding month, the PCE price index for ([A-Za-z]+) (increased|decreased) (\d+(?:\.\d+)?) percent\.",
                "전월 대비",
            ),
            (
                "pce_year",
                r"From the same month one year ago, the PCE price index for ([A-Za-z]+) (increased|decreased) (\d+(?:\.\d+)?) percent\.",
                "전년 동월 대비",
            ),
        ):
            m = re.search(pattern, text)
            if not m or m[1].lower() != identity[1].lower():
                raise NewsError("pce_basis_missing")
            action = "상승" if m[2] == "increased" else "하락"
            facts.append(
                _fact(
                    label,
                    m[0],
                    f"미국 BEA의 {period} PCE 물가지수는 {basis} {m[3]}% {action}했다.",
                )
            )
        event = "PCE:" + published_at.date().isoformat()
    else:
        m = re.search(
            r"Real gross domestic product \(GDP\) (increased|decreased) at an annual rate of (\d+(?:\.\d+)?) percent in the (first|second|third|fourth) quarter of (\d{4}).*?according to the (advance|second|third) estimate",
            text,
        )
        if not m:
            raise NewsError("gdp_period_or_estimate_missing")
        q = {"first": 1, "second": 2, "third": 3, "fourth": 4}[m[3]]
        identity = re.search(
            r"([1-4])(?:st|nd|rd|th) Quarter (\d{4})", title, re.IGNORECASE
        )
        estimate = re.search(
            r"\b(advance|second|third) estimate\b", title, re.IGNORECASE
        )
        if (
            not identity
            or not estimate
            or (int(identity[1]), identity[2], estimate[1].lower()) != (q, m[4], m[5])
        ):
            raise NewsError("gdp_title_body_mismatch")
        stage = {"advance": "속보치", "second": "2차 추정", "third": "3차 추정"}[m[5]]
        action = "증가" if m[1] == "increased" else "감소"
        facts = (
            _fact(
                "gdp_annualized",
                m[0],
                f"미국 BEA의 {m[4]}년 {q}분기 실질 GDP {stage}는 전기 대비 연율 {m[2]}% {action}했다.",
            ),
        )
        event = "GDP:" + published_at.date().isoformat()
    return NewsItem(
        provider=provider,
        kind="official",
        source_id=url,
        url=url,
        title=title,
        publisher="BEA" if provider == "BEA" else "Federal Reserve Board",
        published_at=published_at,
        retrieved_at=retrieved_at,
        content_version=digest(text),
        event_key=event,
        facts=tuple(facts),
        permission_reference="official_self_authored:2026-11-02",
    )


def _bls_item(html, retrieved_at):
    from xfolio.news.providers.bls import BLSError

    try:
        bundle = parse_release(html, retrieved_at=retrieved_at, run_id="newsletter")
    except (BLSError, ValueError):
        raise NewsError("bls_parse_failed") from None
    if re.search(
        r"copyright|all rights reserved|used with permission|courtesy of",
        bundle.source.text,
        re.IGNORECASE,
    ):
        raise NewsError("bls_rights_unverified")
    facts = []
    for claim in bundle.event.claims:
        period = bundle.event.period_or_transaction
        year, month = period.split("-")
        basis = (
            "전월 대비(계절조정)"
            if claim.comparison_basis == "previous_month_seasonally_adjusted"
            else "전년 동월 대비(비계절조정)"
        )
        action = "상승" if claim.action == "increased" else "하락"
        facts.append(
            _fact(
                claim.comparison_basis,
                claim.evidence_span,
                f"미국 BLS의 {year}년 {int(month)}월 CPI-U는 {basis} {claim.value}% {action}했다.",
            )
        )
    if len(facts) != 2:
        raise NewsError("bls_facts_missing")
    return NewsItem(
        provider="BLS",
        kind="official",
        source_id=bundle.source.source_id,
        url=RELEASE_URL,
        title="Consumer Price Index " + bundle.event.period_or_transaction,
        publisher="BLS",
        published_at=bundle.source.published_at,
        retrieved_at=retrieved_at,
        content_version=bundle.source.content_version,
        event_key="CPI:" + bundle.source.published_at.date().isoformat(),
        facts=tuple(facts),
        permission_reference="bls_public_text:2026-11-02",
    )


def collect_official(client, *, provider, as_of, clock=lambda: datetime.now(UTC)):
    as_of, calls, errors, items, excluded = aware(as_of), 0, [], [], Counter()
    try:
        calls += 1
        if provider == "BLS":
            html = fetch(client, RELEASE_URL)
            item = _bls_item(html, aware(clock()))
            if as_of - timedelta(hours=96) <= item.published_at <= as_of:
                items.append(item)
            else:
                excluded["outside_96h_or_cutoff"] += 1
        else:
            xml = fetch(client, FEEDS[provider], xml=True)
            entries = feed_entries(xml, provider)
            entries = sorted(set(entries), key=lambda e: e[2], reverse=True)
            eligible = [
                e for e in entries if as_of - timedelta(hours=96) <= e[2] <= as_of
            ]
            excluded["outside_96h_or_cutoff"] += len(entries) - len(eligible)
            if len(eligible) > 6:
                errors.append("release_request_limit")
            for title, url, published in eligible[:6]:
                if not official_url(provider, url):
                    errors.append("unsupported_feed_url")
                    continue
                calls += 1
                try:
                    html = fetch(client, url)
                    items.append(
                        parse_official(
                            html,
                            provider=provider,
                            url=url,
                            title=title,
                            published_at=published,
                            retrieved_at=clock(),
                        )
                    )
                except ValueError as exc:
                    errors.append(
                        str(exc) if isinstance(exc, NewsError) else "page_schema"
                    )
        return SourceResult(
            provider=provider,
            status="partial" if errors else "complete",
            items=tuple(items),
            requests=calls,
            errors=tuple(errors),
            excluded=dict(excluded),
        )
    except NewsError as exc:
        return SourceResult(
            provider=provider,
            status="failed",
            items=tuple(items),
            requests=calls,
            errors=(str(exc),),
            excluded=dict(excluded),
        )
