"""본인 로컬 DB·관리자·날짜 한정 정시 시험. 비밀과 외부 예외는 출력하지 않는다."""

import argparse
import json
import logging
import os
import secrets
import subprocess
import sys
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import httpx
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from dotenv import dotenv_values

from xfolio.domestic.calendar import KST
from xfolio.domestic.kis import KisClient, KisSettings
from xfolio.domestic.store import DomesticStore
from xfolio.jobs.collection import CappedWorkflowStore
from xfolio.news_generation import OpenAIGenerationClient
from xfolio.news_workflow import GenerationLimits
from xfolio.newsletter_news import collect, summarize
from xfolio.newsletter_news_store import NewsletterNewsStore

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
CACHE = ROOT / ".cache" / "local_runtime"
PG = Path("C:/Program Files/PostgreSQL/17/bin")
PORT = 55439
DATABASE = "xfolio_local"
ROLE = "xfolio_local"
TARGET_DAY = date(2026, 11, 6)


def save(path, value):
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def pg_run(*args):
    result = subprocess.run(
        [str(PG / args[0]), *args[1:]],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if result.returncode:
        raise ValueError("local_postgres_command_failed")


def load_environment():
    values = dotenv_values(ROOT / ".env", interpolate=False)
    os.environ.update({k: v for k, v in values.items() if v is not None})
    config = json.loads((CACHE / "runtime.json").read_text(encoding="utf-8"))
    for name in ("XFOLIO_API_DATABASE_URL", "XFOLIO_WORKER_DATABASE_URL"):
        os.environ[name] = config["database_url"]
    os.environ["XFOLIO_API_CURSOR_SECRET"] = config["cursor_secret"]
    os.environ["XFOLIO_PUBLIC_ORIGIN"] = "https://localhost:8443"
    os.environ["XFOLIO_GENERATION_LIMITS_FILE"] = str(CACHE / "generation_limits.json")
    os.environ["XFOLIO_MONTHLY_BUDGET_KRW"] = "100"
    os.environ["XFOLIO_RECIPIENT_SCOPE"] = "self"
    for name in ("BOT_TOKEN", "CHAT_ID"):
        os.environ["XFOLIO_TELEGRAM_" + name] = (
            values.get("XFOLIO_TELEGRAM_" + name)
            or values.get("TELEGRAM_" + name)
            or ""
        )
    return config


def engine():
    return sa.create_engine(
        os.environ["XFOLIO_API_DATABASE_URL"], hide_parameters=True, pool_pre_ping=True
    )


def setup():
    CACHE.mkdir(parents=True, exist_ok=True)
    config_file = CACHE / "runtime.json"
    if not config_file.exists():
        password = secrets.token_urlsafe(32)
        save(
            config_file,
            {
                "database_url": f"postgresql+psycopg://{ROLE}:{password}@127.0.0.1:{PORT}/{DATABASE}",
                "cursor_secret": secrets.token_urlsafe(48),
            },
        )
    config = load_environment()
    data = CACHE / "postgres" / "data"
    if not (data / "PG_VERSION").exists():
        password_file = CACHE / "init_password"
        password_file.write_text(
            sa.engine.make_url(config["database_url"]).password + "\n", encoding="utf-8"
        )
        try:
            pg_run(
                "initdb.exe",
                "-D",
                str(data),
                "-U",
                ROLE,
                "--auth=scram-sha-256",
                "--pwfile=" + str(password_file),
                "--encoding=UTF8",
                "--locale=C",
            )
        finally:
            password_file.unlink(missing_ok=True)
    if subprocess.run(
        [str(PG / "pg_ctl.exe"), "-D", str(data), "status"],
        capture_output=True,
        check=False,
    ).returncode:
        pg_run(
            "pg_ctl.exe",
            "-D",
            str(data),
            "-l",
            str(CACHE / "postgres.log"),
            "-o",
            f"-h 127.0.0.1 -p {PORT}",
            "-w",
            "start",
        )
    admin = sa.create_engine(
        sa.engine.make_url(config["database_url"]).set(database="postgres"),
        isolation_level="AUTOCOMMIT",
        hide_parameters=True,
    )
    with admin.connect() as conn:
        if not conn.scalar(
            sa.text("SELECT 1 FROM pg_database WHERE datname=:name"), {"name": DATABASE}
        ):
            conn.exec_driver_sql(f'CREATE DATABASE "{DATABASE}"')
    admin.dispose()
    db = engine()
    try:
        alembic = Config(str(ROOT / "alembic.ini"))
        with db.begin() as conn:
            alembic.attributes["connection"] = conn
            command.upgrade(alembic, "head")
        DomesticStore(db).bootstrap(datetime.now(UTC))
        with db.connect() as conn:
            revision = conn.scalar(sa.text("SELECT version_num FROM alembic_version"))
        return {
            "status": "ready",
            "database": DATABASE,
            "port": PORT,
            "migration": revision,
            "synthetic": False,
        }
    finally:
        db.dispose()


def start_service(name):
    load_environment()
    if name == "api":
        from scripts.dev.run_api import main
    else:
        from scripts.dev.local_https import main
    sys.argv = [name]
    main()


def collect_real():
    load_environment()
    db = engine()
    try:
        store = DomesticStore(db)
        with KisClient(
            KisSettings(os.environ["KIS_APP_KEY"], os.environ["KIS_APP_SECRET"]),
            calendar_cache=store,
        ) as kis:
            result, saved = store.collect(kis)
        with httpx.Client(
            timeout=20, follow_redirects=False, trust_env=False
        ) as client:
            news = collect(
                client, api_key=os.environ["FINNHUB_API_KEY"], as_of=datetime.now(UTC)
            )
        NewsletterNewsStore(db).save_result(news, now=datetime.now(UTC))
        report = {
            "status": "collected",
            "market_status": result.status,
            "prices": len(saved["snapshot_ids"]),
            "trade_dates": sorted(
                {q.latest.trade_date.isoformat() for q in result.quotes}
            ),
            "news_status": news.status,
            "selected": len(news.selected),
            "sources": [
                {"provider": s.provider, "status": s.status, "errors": s.errors}
                for s in news.sources
            ],
            "synthetic": False,
            "paid_calls": 0,
            "send_calls": 0,
        }
        save(CACHE / "collection.json", report)
        return report
    finally:
        db.dispose()


def paid_probe():
    from openai import OpenAI

    from xfolio.bls import RELEASE_URL
    from xfolio.db.schema import usage_ledger
    from xfolio.official_releases import _bls_item, fetch

    load_environment()
    limits = GenerationLimits.model_validate_json(
        (CACHE / "generation_limits.json").read_text(encoding="utf-8")
    )
    with httpx.Client(timeout=20, trust_env=False, follow_redirects=False) as client:
        item = _bls_item(fetch(client, RELEASE_URL), datetime.now(UTC))
    # 과거 발표도 요약 진단에만 사용한다. 당일 뉴스레터로 저장/송신하지 않는다.
    with (CACHE / "paid_probe.attempt.json").open("x", encoding="utf-8") as handle:
        json.dump({"at": datetime.now(UTC).isoformat(), "maximum_calls": 1}, handle)
    db = engine()
    try:

        class MeasuredClient:
            usage = None

            def generate(self, **kwargs):
                response = adapter.generate(**kwargs)
                self.usage = {
                    "input_tokens": response.input_tokens,
                    "output_tokens": response.output_tokens,
                }
                return response

        measured = MeasuredClient()
        with OpenAI(
            api_key=os.environ["OPENAI_API_KEY"],
            base_url="https://api.openai.com/v1",
            max_retries=0,
            timeout=30,
        ) as sdk:
            adapter = OpenAIGenerationClient(sdk)
            value = summarize(
                item,
                client=measured,
                store=CappedWorkflowStore(db, Decimal(100)),
                limits=limits,
                now=datetime.now(UTC),
            )
        with db.connect() as conn:
            cost = conn.scalar(
                sa.select(sa.func.sum(usage_ledger.c.amount_krw)).where(
                    usage_ledger.c.provider == "OpenAI"
                )
            )
        report = {
            "status": "verified",
            "model": limits.model,
            "usage": measured.usage,
            "estimated_krw": str(cost),
            "source": "BLS",
            "published_at": item.published_at.isoformat(),
            "source_url": item.url,
            "summary": value.summary_ko,
            "claims_checked": len(item.facts),
            "diagnostic_only": True,
            "send_calls": 0,
        }
        save(CACHE / "paid_probe.json", report)
        return report
    finally:
        db.dispose()


def phase(day, part, *, now=None):
    now = now or datetime.now(UTC)
    local = now.astimezone(KST)
    if day != TARGET_DAY or local.date() != day:
        return {
            "status": "skipped",
            "reason": "outside_authorized_date",
            "send_calls": 0,
        }
    if not (
        local.hour == 7 and local.minute == 50
        if part == "prepare"
        else local.hour == 8 and local.minute < 10
    ):
        return {
            "status": "skipped",
            "reason": "outside_authorized_window",
            "send_calls": 0,
        }
    load_environment()
    os.environ["XFOLIO_WORKER_LIVE_ACCEPTED"] = "true"
    from xfolio.jobs.worker import main

    with (CACHE / f"{day}_{part}.log").open("a", encoding="utf-8") as handle:
        from contextlib import redirect_stdout

        with redirect_stdout(handle):
            code = main(["--live", "--phase", part])
    return {
        "exit_code": code,
        "phase": part,
        "finished_at": datetime.now(UTC).isoformat(),
    }


def preflight():
    from scripts.dev.run_api import development_settings
    from xfolio.notification_settings import NotificationSettingsStore

    setup()
    development_settings("https://localhost:8443")
    limits = GenerationLimits.model_validate_json(
        (CACHE / "generation_limits.json").read_text(encoding="utf-8")
    )
    if limits.prices_valid_until <= datetime.now(UTC):
        raise ValueError("prices_expired")
    token, chat = (
        os.environ["XFOLIO_TELEGRAM_BOT_TOKEN"],
        os.environ["XFOLIO_TELEGRAM_CHAT_ID"],
    )
    with httpx.Client(timeout=15, trust_env=False) as client:
        response = client.post(
            f"https://api.telegram.org/bot{token}/getChat", json={"chat_id": chat}
        )
        payload = response.json()
        target = payload.get("result", {})
        if (
            response.status_code != 200
            or payload.get("ok") is not True
            or target.get("type") != "private"
            or str(target.get("id")) != chat
        ):
            raise ValueError("private_recipient_unverified")
    db = engine()
    try:
        settings = NotificationSettingsStore(db).get()
        result = {
            "status": "ready"
            if settings.morning_enabled and not settings.paused
            else "disabled",
            "private_recipient_verified": True,
            "google_configuration": True,
            "max_summary_cost_krw": str(limits.maximum_cost),
            "monthly_cap_krw": "100",
            "send_calls": 0,
            "paid_calls": 0,
            "checked_at": datetime.now(UTC).isoformat(),
        }
        save(CACHE / "preflight.json", result)
        return result
    finally:
        db.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=("setup", "api", "https", "collect", "paid", "phase", "preflight"),
    )
    parser.add_argument("--day", type=date.fromisoformat, default=TARGET_DAY)
    parser.add_argument("--phase", choices=("prepare", "send"), default="prepare")
    args = parser.parse_args()
    logging.disable(logging.CRITICAL)
    try:
        if args.action in {"api", "https"}:
            start_service(args.action)
            return 0
        result = {
            "setup": setup,
            "collect": collect_real,
            "paid": paid_probe,
            "phase": lambda: phase(args.day, args.phase),
            "preflight": preflight,
        }[args.action]()
        print(json.dumps(result, ensure_ascii=False))
        return int(result.get("exit_code", 0))
    except Exception:  # noqa: BLE001 -- credentials and provider payloads must remain private.
        print(
            json.dumps(
                {"status": "failed", "action": args.action, "automatic_retry": False}
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
