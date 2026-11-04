"""개발용 제목 필터·공급자 원문 주소/정상 경유 시험. 본문 저장·송신은 없다."""

import argparse
import hashlib
import json
from collections import Counter
from contextlib import nullcontext
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from xfolio.finnhub import (
    canonical_url,
    event_bucket,
    filter_rows,
    is_article_url,
    relevance,
    resolve_link,
    response_statistics,
    title_key,
)

__all__ = [
    "ProbeError",
    "canonical_url",
    "event_bucket",
    "filter_rows",
    "is_article_url",
    "relevance",
    "resolve_link",
    "response_statistics",
    "run_probe",
    "title_key",
]


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
