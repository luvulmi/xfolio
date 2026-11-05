"""T07 explicit free-provider/private-Telegram diagnostics, never scheduled delivery."""

import argparse
import json
import logging
import os
import secrets
from datetime import UTC, datetime
from pathlib import Path

import httpx
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from dotenv import dotenv_values

from xfolio.domestic.calendar import KST
from xfolio.domestic.kis import KisClient, KisSettings
from xfolio.domestic.store import DomesticStore
from xfolio.jobs.telegram import TelegramTransport
from xfolio.news.collection import collect
from xfolio.news.collection_store import NewsletterNewsStore

ROOT = Path(__file__).resolve().parents[2]


def run(args):
    logging.disable(logging.CRITICAL)
    if not args.run:
        return {"mode": "plan", "network_requests": 0, "database_writes": 0}
    output = args.output.resolve()
    if ROOT / ".cache" not in output.parents:
        raise ValueError("output_must_be_git_ignored_cache")
    output.parent.mkdir(parents=True, exist_ok=True)
    attempt = output.with_suffix(".attempt.json")
    with attempt.open("x", encoding="utf-8") as handle:
        json.dump({"started_at": datetime.now(UTC).isoformat()}, handle)
    values = dotenv_values(args.env_file, interpolate=False)
    url = os.environ.get("XFOLIO_TEST_DATABASE_URL", "")
    from sqlalchemy.engine import make_url

    parsed = make_url(url)
    if (
        parsed.host != "127.0.0.1"
        or parsed.port != 55438
        or parsed.database != "xfolio_t07_test"
    ):
        raise ValueError("isolated_test_database_required")
    base = sa.create_engine(url, hide_parameters=True)
    schema = "xf_t07_probe_" + secrets.token_hex(8)
    engine = None
    report = {"mode": "diagnostic", "synthetic": False, "scheduled_acceptance": False}
    try:
        with base.begin() as conn:
            conn.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
        engine = sa.create_engine(
            url,
            hide_parameters=True,
            connect_args={"options": f"-csearch_path={schema}"},
        )
        config = Config(str(ROOT / "alembic.ini"))
        with engine.begin() as conn:
            config.attributes["connection"] = conn
            command.upgrade(config, "head")
        now = datetime.now(UTC)
        domestic = DomesticStore(engine)
        domestic.bootstrap(now)
        settings = KisSettings(
            values.get("KIS_APP_KEY") or "",
            values.get("KIS_APP_SECRET") or "",
        )
        with KisClient(settings, calendar_cache=domestic) as kis:
            market, saved = domestic.collect(kis)
        day = now.astimezone(KST).date()
        calendar = domestic.load_calendar(day) or {}
        report["market"] = {
            "status": market.status,
            "quote_count": len(market.quotes),
            "stored_snapshots": len(saved["snapshot_ids"]),
            "errors": market.errors,
            "started_at": market.started_at.isoformat(),
            "finished_at": market.finished_at.isoformat(),
            "trade_dates": sorted(
                {q.latest.trade_date.isoformat() for q in market.quotes}
            ),
            "market_open_today": calendar.get(day),
        }
        with httpx.Client(
            timeout=20, follow_redirects=False, trust_env=False
        ) as client:
            news = collect(
                client,
                api_key=values.get("FINNHUB_API_KEY") or "",
                as_of=datetime.now(UTC),
            )
        ids = NewsletterNewsStore(engine).save_result(news, now=datetime.now(UTC))
        report["news"] = {
            "status": news.status,
            "normal_zero": news.normal_zero,
            "selected_count": len(news.selected),
            "stored_items": len(ids),
            "as_of": news.as_of.isoformat(),
            "finished_at": news.finished_at.isoformat(),
            "sources": [
                {
                    "provider": source.provider,
                    "status": source.status,
                    "requests": source.requests,
                    "errors": source.errors,
                }
                for source in news.sources
            ],
            "paid_ai_calls": 0,
        }
        report["telegram"] = {"status": "not_requested", "send_calls": 0}
        if args.telegram:
            if calendar.get(day) is not True or day.weekday() >= 5:
                report["telegram"]["status"] = "skipped_closed_or_unverified"
            else:
                report["telegram"] = telegram_probe(values, output)
        report["finished_at"] = datetime.now(UTC).isoformat()
    finally:
        if engine:
            engine.dispose()
        with base.begin() as conn:
            conn.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        base.dispose()
    report["test_schema_removed"] = True
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return report


def telegram_probe(values, output):
    token = (
        values.get("XFOLIO_TELEGRAM_BOT_TOKEN")
        or values.get("TELEGRAM_BOT_TOKEN")
        or ""
    )
    chat = values.get("XFOLIO_TELEGRAM_CHAT_ID") or values.get("TELEGRAM_CHAT_ID") or ""
    transport = TelegramTransport(token=token, chat_id=chat)
    try:
        with httpx.Client(
            timeout=15, follow_redirects=False, trust_env=False
        ) as client:
            response = client.post(
                f"https://api.telegram.org/bot{token}/getChat", json={"chat_id": chat}
            )
            data = response.json()
            target = data.get("result", {})
            if (
                response.status_code != 200
                or data.get("ok") is not True
                or target.get("type") != "private"
                or str(target.get("id")) != str(chat)
            ):
                return {"status": "preflight_failed", "send_calls": 0}
        marker = output.with_suffix(".telegram_attempt.json")
        with marker.open("x", encoding="utf-8") as handle:
            json.dump(
                {"status": "attempted", "at": datetime.now(UTC).isoformat()}, handle
            )
        body = (
            "XFolio T07 \ud1b5\ud569 \uc2dc\ud5d8\n"
            "\ubcf8\uc778 1:1 Telegram \uc5f0\uacb0\uc744 \ud655\uc778\ud558\ub294 \uc2dc\ud5d8 \uba54\uc2dc\uc9c0\uc785\ub2c8\ub2e4.\n"
            "\uc815\uc2dc \uc544\uce68 \ub274\uc2a4\ub808\ud130\uc640 \uad6c\ubd84\ub418\uba70 \uac00\uaca9\u00b7\ub274\uc2a4\ub294 \ud3ec\ud568\ud558\uc9c0 \uc54a\uc2b5\ub2c8\ub2e4."
        )
        result = transport.send(body)
        receipt = {
            "status": result.status,
            "send_calls": 1,
            "message_id": result.message_id,
            "error_code": result.error_code,
            "private_verified": True,
        }
        marker.write_text(json.dumps(receipt), encoding="utf-8")
        return receipt
    finally:
        transport.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--telegram", action="store_true")
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument(
        "--output", type=Path, default=ROOT / ".cache/t07-20261105/live_probe.json"
    )
    args = parser.parse_args()
    try:
        print(json.dumps(run(args), ensure_ascii=False, indent=2))
        return 0
    except Exception:  # noqa: BLE001 - external errors may contain credentials; emit only a fixed code.
        print(
            json.dumps(
                {
                    "status": "probe_failed_or_already_attempted",
                    "automatic_retry": False,
                }
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
