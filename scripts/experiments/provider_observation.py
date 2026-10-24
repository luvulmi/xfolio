"""5운영일 제공처 관측. 기본 무통신, 일별 최대2회·Marketaux 최대12요청."""

import argparse
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

import httpx
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from xfolio.bls import BLSError, inspect_bls
from xfolio.news import collect_news, metadata_report
from xfolio.news_queries import NewsQuery
from xfolio.news_store import NewsStore

QUERIES = (
    NewsQuery("market", '("S&P 500"|Nasdaq)+(stocks|market)'),
    NewsQuery(
        "sector",
        "(semiconductor|energy|banking)+(industry|sector)+(rose|fell|demand|supply)",
    ),
)
KST = ZoneInfo("Asia/Seoul")
OUTPUT = Path("tasks/verification/assets/provider_observations")


class Credentials(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    token: SecretStr = Field(default="", validation_alias="MARKETAUX_API_TOKEN")


def observe(*, run=False, output=OUTPUT, token=None, now=None, review=False):
    now = (now or datetime.now(UTC)).replace(microsecond=0)
    if now.utcoffset() is None:
        raise ValueError("timezone_required")
    local = now.astimezone(KST)
    report = {
        "mode": "run" if run else "dry_run",
        "observed_at": now.isoformat(),
        "scope": "market_sector_sample_v1",
        "max_marketaux_requests": 6,
        "full_operating_day": False,
        "can_publish": False,
        "started_before_morning_cutoff": (local.hour, local.minute) < (7, 30),
    }
    if not run:
        return report
    if not token:
        raise ValueError("missing_api_token")
    output.mkdir(parents=True, exist_ok=True)
    # 실패·중단에도 예약 파일을 남겨 같은 날 무제한 재시도를 막는다.
    # 이 실험의 예산이며 계정 전체 사용량을 예약하는 것은 아니다.
    day = local.strftime("%Y%m%d")
    for slot in (1, 2):
        path = output / f"observation_{day}_{slot}.json"
        try:
            with path.open("x", encoding="utf-8") as stream:
                json.dump(report | {"state": "reserved"}, stream)
            break
        except FileExistsError:
            continue
    else:
        raise ValueError("daily_observation_budget_exhausted")
    try:
        with httpx.Client() as client:
            bundle, official = inspect_bls(client=client, run_id=str(uuid4()))
        official["storage_result"] = NewsStore().save_evidence(bundle)
        report["bls"] = official
    except (BLSError, ValueError, OSError, sqlite3.Error) as exc:
        report["bls"] = {
            "state": "failed",
            "error": str(exc)
            if isinstance(exc, BLSError)
            else "parse_or_storage_error",
        }
    collection = collect_news(
        start=now - timedelta(days=1),
        end=now,
        queries=QUERIES,
        token=token,
        max_requests=6,
        max_pages=3,
    )
    report["marketaux"] = metadata_report(collection)
    completed_local = collection.collected_at.astimezone(KST)
    report["before_morning_cutoff"] = completed_local.date() == local.date() and (
        completed_local.hour,
        completed_local.minute,
    ) < (7, 30)
    report["state"] = "observed"
    # 본문은 파일에 보관하지 않는다. 명시적 수동 판독 시 콘솔에서만 확인한다.
    if review:
        for article in collection.articles:
            print(
                json.dumps(
                    {
                        "id": article.article_id,
                        "title": article.title,
                        "description": article.description,
                        "snippet": article.snippet,
                    },
                    ensure_ascii=False,
                )
            )
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--review", action="store_true")
    args = parser.parse_args()
    report = observe(
        run=args.run,
        review=args.review,
        token=Credentials().token.get_secret_value() if args.run else None,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
