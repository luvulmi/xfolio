"""개발용 제목 필터·공급자 원문 주소/정상 경유 시험. 본문 저장·송신은 없다."""

import argparse
import hashlib
import json
import math
import re
import unicodedata
from collections import Counter
from contextlib import nullcontext
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlencode, urljoin, urlsplit, urlunsplit

import httpx
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

PUBLISHERS = {"cnbc": "cnbc.com", "reuters": "reuters.com"}
US_MARKET = re.compile(
    r"\b(?:u\.?s\.?\s+(?:stocks?|equit(?:y|ies)|markets?|econom\w*|inflation|jobs?|voters?|midterms?|treasur\w*)|"
    r"united states|wall street|s&p\s*500|nasdaq|dow jones|federal reserve|fomc)\b",
    re.IGNORECASE,
)
US_COMPANY = re.compile(
    r"\b(?:apple|microsoft|nvidia|amazon|alphabet|google|meta|tesla|oracle|"
    r"broadcom|berkshire|jpmorgan|walmart|exxon|chevron)\b",
    re.IGNORECASE,
)
BUSINESS = re.compile(
    r"\b(?:stock|share|earnings|revenue|profit|bond|finance|financing|"
    r"sell|sales|buyback|acquisition|dividend|buildout|investment)\b",
    re.IGNORECASE,
)
EXCLUDED = re.compile(
    r"\b(?:bitcoin|crypto|ethereum|buy the dip|buying the dip|"
    r"top picks|stocks to buy|our portfolio)\b",
    re.IGNORECASE,
)


def canonical_url(url: str) -> str:
    """HTTPS·정해진 공개 제공처만 허용한다. 임의 호스트/DNS에는 연결하지 않는다."""
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        allowed = host == "news.google.com" or any(
            host in (domain, "www." + domain) for domain in PUBLISHERS.values()
        )
        if (
            parts.scheme != "https"
            or not allowed
            or parts.username
            or parts.password
            or parts.port not in (None, 443)
            or "\\" in url
            or any(ord(char) < 32 for char in url)
        ):
            return ""
        query = urlencode(
            [
                (key, value)
                for key, value in parse_qsl(parts.query, keep_blank_values=True)
                if not key.lower().startswith("utm_")
                and key.lower() not in {"oc", "gclid", "fbclid", "cmpid", "__source"}
            ]
        )
        return urlunsplit(("https", host, parts.path or "/", query, ""))
    except (ValueError, TypeError):
        return ""


def relevance(headline: str, url: str) -> str:
    if EXCLUDED.search(headline) or any(
        marker in urlsplit(url).path.lower()
        for marker in ("/investingclub/", "/opinion/")
    ):
        return "excluded_opinion_or_crypto"
    if US_MARKET.search(headline):
        return "us_market"
    if US_COMPANY.search(headline) and BUSINESS.search(headline):
        return "us_company"
    return "no_explicit_us_relevance"


def title_key(headline: str, source: str) -> str:
    title = unicodedata.normalize("NFKC", headline).casefold()
    title = re.sub(r"\s*[-–—|]\s*" + re.escape(source.casefold()) + r"\s*$", "", title)
    return " ".join(re.findall(r"[a-z0-9]+", title))


def event_bucket(headline: str) -> str:
    # 사건군당 1건의 편성 제한이다. 다른 관점의 기사를 같은 기사라고 단정하지 않는다.
    if re.search(
        r"\bus\s+midterm|\bus\s+voters?\b.*\bmidterm", headline, re.IGNORECASE
    ):
        return "us_midterms"
    return ""


def filter_rows(rows: list, as_of: datetime, seen_ids=(), seen_urls=()):
    """96시간 미전달 후보. 수신/검토만으로 발송 완료 ID를 갱신하지 않는다."""
    counts = Counter()
    candidates = []
    ids, urls, titles = set(seen_ids), set(seen_urls), set()
    valid = []
    for row in rows:
        try:
            published = datetime.fromtimestamp(row["datetime"], UTC)
            if not isinstance(row["id"], int) or isinstance(row["id"], bool):
                raise TypeError
            if not all(
                isinstance(row[key], str) and row[key].strip()
                for key in ("headline", "source", "url")
            ):
                raise ValueError
        except (KeyError, ValueError, TypeError, OverflowError, OSError):
            counts["invalid_row"] += 1
            continue
        age = (as_of - published).total_seconds()
        if not 0 <= age <= 96 * 3600:
            counts["future_or_older_than_96h"] += 1
            continue
        valid.append((published, row))
    for published, row in sorted(valid, key=lambda item: item[0], reverse=True):
        url = canonical_url(row["url"])
        source = row["source"].casefold().strip()
        if not url or source not in PUBLISHERS:
            counts["unsupported_source_or_url"] += 1
            continue
        reason = relevance(row["headline"], url)
        if reason not in {"us_market", "us_company"}:
            counts[reason] += 1
            continue
        title = title_key(row["headline"], source)
        if row["id"] in ids or url in urls or title in titles:
            counts["duplicate_id_url_or_title"] += 1
            continue
        ids.add(row["id"])
        urls.add(url)
        titles.add(title)
        candidates.append(
            {
                **row,
                "url": url,
                "reason": reason,
                "age_hours": round((as_of - published).total_seconds() / 3600, 2),
            }
        )
    return candidates, counts


def response_statistics(rows: list, observed_at: datetime) -> dict:
    """응답 확보 시점 대비 발행 경과시간이다. 공급자의 수집/전달 지연이 아니다."""
    published_times, hosts = [], Counter()
    invalid = future = within_24h = within_96h = 0
    for row in rows:
        try:
            value = row["datetime"]
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or value < 0
                or (isinstance(value, float) and not math.isfinite(value))
            ):
                raise ValueError
            published = datetime.fromtimestamp(value, UTC)
        except (KeyError, ValueError, TypeError, OverflowError, OSError):
            invalid += 1
        else:
            published_times.append(published)
            age = (observed_at - published).total_seconds()
            future += age < 0
            within_24h += 0 <= age <= 24 * 3600
            within_96h += 0 <= age <= 96 * 3600
        try:
            raw_url = row["url"]
            if not isinstance(raw_url, str) or any(ord(char) < 33 for char in raw_url):
                raise ValueError
            parts = urlsplit(raw_url)
            host = parts.hostname
            if (
                parts.scheme not in {"https", "http"}
                or parts.username
                or parts.password
                or not host
                or len(host) > 253
                or not all(
                    re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
                    for label in host.split(".")
                )
            ):
                raise ValueError
            # malformed port도 유효한 URL 집계로 통과시키지 않는다.
            _ = parts.port
        except (KeyError, ValueError, TypeError, AttributeError):
            continue
        hosts[host] += 1
    return {
        "valid_timestamp_count": len(published_times),
        "invalid_timestamp_count": invalid,
        "future_timestamp_count": future,
        "within_24h_of_query": within_24h,
        "within_96h_of_query": within_96h,
        "newest_published_at_utc": max(published_times).isoformat()
        if published_times
        else None,
        "oldest_published_at_utc": min(published_times).isoformat()
        if published_times
        else None,
        "source_hosts": dict(sorted(hosts.items())),
        "publication_age_is_provider_delay": False,
    }


def is_article_url(url: str, domain: str) -> bool:
    """지원 매체의 개별 기사 경로만 인정한다. URL 식별이며 열람 성공 검증은 아니다."""
    path = unquote(urlsplit(url).path)
    if any(part in {".", ".."} for part in path.split("/")):
        return False
    if domain == "cnbc.com":
        return bool(re.fullmatch(r"/\d{4}/\d{2}/\d{2}/[^/]+\.html", path))
    if domain == "reuters.com":
        return bool(
            re.fullmatch(
                r"/(?:business|markets|technology|world|legal|sustainability|economy|investigates)"
                r"(?:/[^/]+)*/[^/]+-\d{4}-\d{2}-\d{2}/?",
                path,
            )
            or re.fullmatch(r"/article/[^/]*id[A-Z0-9]+/?", path)
        )
    return False


def resolve_link(client, url: str, source: str, max_requests=4):
    """공급자 직접 주소는 무통신, Google은 HEAD 경유만. 원문 가용성을 보장하지 않는다."""
    domain = PUBLISHERS.get(source.casefold().strip())
    current = canonical_url(url)
    calls = 0

    def result(status, resolved=""):
        return {
            "status": status,
            "calls": calls,
            "url": resolved,
            "article_availability_verified": False,
        }

    while True:
        if not current or not domain:
            return result("unsafe_or_unknown_source")
        host = urlsplit(current).hostname
        if host not in ("news.google.com", domain, "www." + domain):
            return result("publisher_mismatch")
        if host != "news.google.com":
            if not is_article_url(current, domain):
                return result("not_article_url")
            return result(
                "provider_direct_url" if calls == 0 else "publisher_redirect_url",
                current,
            )
        if not re.fullmatch(r"/(?:rss/)?articles/[^/]+", urlsplit(current).path):
            return result("not_google_article_url")
        if calls >= max_requests:
            return result("redirect_limit" if calls else "request_budget_exhausted")
        try:
            calls += 1
            # HEAD에 본문이 잘못 붙어도 다운로드하지 않는다.
            with client.stream("HEAD", current, follow_redirects=False) as response:
                status = response.status_code
                location = response.headers.get("location")
        except httpx.HTTPError:
            return result("network_error")
        if status in (301, 302, 303, 307, 308) and location:
            current = canonical_url(urljoin(current, location))
            continue
        return result("google_interstitial" if status == 200 else f"http_{status}")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    finnhub_api_key: SecretStr


class ProbeError(RuntimeError):
    """원문/인증 값을 포함하지 않는 개발용 관측 실패."""


def run_probe(
    output: Path,
    *,
    as_of: datetime | None = None,
    client: httpx.Client | None = None,
    api_key: str | None = None,
) -> dict:
    """API1회·Google HEAD 최대12회. 실제 시각과 선택 기준을 구분한 집계만 기록한다."""
    # 기존 파일 덮어쓰기를 막고 지정 증거 폴더에 집계만 저장한다.
    output = output.resolve()
    root = Path("tasks/verification/assets/news_samples").resolve()
    if not output.is_relative_to(root) or output.exists():
        raise ProbeError(
            "output must be a new file under tasks/verification/assets/news_samples"
        )
    if as_of is not None and as_of.tzinfo is None:
        raise ProbeError("as_of must include a timezone")
    if api_key is None:
        try:
            api_key = Settings().finnhub_api_key.get_secret_value()
        except ValueError:
            raise ProbeError("Finnhub configuration missing; values omitted") from None
    if not api_key.strip():
        raise ProbeError("Finnhub configuration missing; values omitted")
    client_context = (
        nullcontext(client)
        if client
        else httpx.Client(timeout=15, follow_redirects=False)
    )
    with client_context as request_client:
        requested_at = datetime.now(UTC)
        try:
            response = request_client.get(
                "https://finnhub.io/api/v1/news",
                params={"category": "general", "minId": 0},
                headers={"X-Finnhub-Token": api_key},
                follow_redirects=False,
            )
            response.raise_for_status()
            rows = response.json()
            if not isinstance(rows, list):
                raise TypeError
        except (httpx.HTTPError, ValueError, TypeError):
            raise ProbeError(
                "Finnhub probe failed; credentials/response omitted"
            ) from None
        observed_at = datetime.now(UTC)
        selection_as_of = (as_of or observed_at).astimezone(UTC)
        candidates, counts = filter_rows(rows, selection_as_of)
        selection_rejections = Counter()
        links, total, selected, events, final_urls = [], 0, [], set(), set()
        for row in candidates:
            if len(selected) == 3:
                break
            result = resolve_link(
                request_client, row["url"], row["source"], min(4, 12 - total)
            )
            total += result["calls"]
            bucket = event_bucket(row["headline"])
            usable = bool(result["url"])
            if usable and (
                result["url"] in final_urls or (bucket and bucket in events)
            ):
                usable = False
                selection_rejections["duplicate_final_url_or_event_cap"] += 1
            if usable:
                final_urls.add(result["url"])
                if bucket:
                    events.add(bucket)
                selected.append(row["id"])
            links.append(
                {
                    "id": row["id"],
                    "source": row["source"],
                    "input_host": urlsplit(row["url"]).hostname,
                    "status": result["status"],
                    "head_calls": result["calls"],
                    "article_availability_verified": result[
                        "article_availability_verified"
                    ],
                    "selected_for_development": usable,
                }
            )
    output.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "requested_at_utc": requested_at.isoformat(),
        "observed_at_utc": observed_at.isoformat(),
        "completed_at_utc": datetime.now(UTC).isoformat(),
        "selection_as_of_utc": selection_as_of.isoformat(),
        "api_calls": 1,
        "http_status": 200,
        "response_sha256": hashlib.sha256(response.content).hexdigest(),
        "returned_count": len(rows),
        "candidate_count": len(candidates),
        "rejections": dict(counts),
        "selection_rejections": dict(selection_rejections),
        "head_calls": total,
        "links": links,
        "development_selected_ids": selected,
        "raw_content_saved": False,
        "telegram_sent": False,
        "permission_verified": False,
        "permission_verification_scope": "no_individual_provider_reply",
        **response_statistics(rows, observed_at),
    }
    try:
        with output.open("x", encoding="utf-8", newline="\n") as evidence:
            evidence.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    except FileExistsError:
        raise ProbeError("output already exists; not overwritten") from None
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live", action="store_true", help="본인 키로 API1회·HEAD 최대12회"
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.live:
        parser.error("실제 통신에는 --live가 필요합니다")
    try:
        report = run_probe(args.output)
    except ProbeError as exc:
        raise SystemExit(str(exc)) from None
    print(json.dumps(report, ensure_ascii=True))


if __name__ == "__main__":
    main()
