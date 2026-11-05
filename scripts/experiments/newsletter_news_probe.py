"""T03 무료 수집 진단. 기사 본문/유료 AI/DB/Telegram 없이 최소 집계만 보존."""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx

from xfolio.news.cli import Settings
from xfolio.news.collection import collect


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not args.run:
        print(
            json.dumps(
                {
                    "mode": "dry_run",
                    "requests": 0,
                    "paid_ai_calls": 0,
                    "can_send": False,
                }
            )
        )
        return
    if not args.output:
        parser.error("--output required")
    output = args.output.resolve()
    root = Path("tasks/verification/assets/news_samples").resolve()
    if not output.is_relative_to(root) or output.exists():
        parser.error("output must be new under news_samples")
    try:
        key = Settings().finnhub_api_key.get_secret_value()
    except ValueError:
        raise SystemExit("configuration_missing") from None
    started = datetime.now(UTC)
    with httpx.Client(timeout=20, follow_redirects=False) as client:
        result = collect(client, api_key=key, as_of=started)
    report = result.report()
    report.update(
        mode="free_collection_diagnostic",
        scheduled_observation=False,
        requested_at=started.isoformat(),
        paid_ai_calls=0,
        database_writes=0,
        telegram_sent=False,
        raw_content_saved=False,
    )
    report["selected"] = [
        {
            k: item.metadata()[k]
            for k in (
                "provider",
                "source_id",
                "url",
                "published_at",
                "retrieved_at",
                "content_version",
                "event_key",
            )
        }
        for item in result.selected
    ]
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8", newline="\n") as file:
        file.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            {
                "status": result.status,
                "selected_count": len(result.selected),
                "sources": report["sources"],
                "output": str(args.output),
                "paid_ai_calls": 0,
            }
        )
    )


if __name__ == "__main__":
    main()
