"""사용자가 승인한 2026-11-06 09:00 본인 전송 시험. 현재 시각을 사용한다."""

import argparse
import json
import logging
import os
import sys
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.dev import local_runtime as runtime
from xfolio.domestic.calendar import KST
from xfolio.jobs.collection import (
    LiveCollectionResources,
    LiveCollectionSettings,
)
from xfolio.jobs.diagnostics import (
    emit_event,
    failure_details,
    safe_process_diagnostics,
)
from xfolio.jobs.outbox import TelegramOutboxStore, dispatch
from xfolio.jobs.telegram import TelegramTransport
from xfolio.newsletter.edition import AcceptanceSchedule, at, fingerprint
from xfolio.newsletter.store import NewsletterStore

DAY = date(2026, 11, 6)
SCOPE = "self_acceptance_20261106_0900"
CONFIG = runtime.CACHE / "2026-11-06_0900_schedule.json"


def run(part):
    now = datetime.now(UTC)
    local = now.astimezone(KST)
    if local.date() != DAY or not (
        local < at(DAY, 9) if part == "prepare" else at(DAY, 9) <= local < at(DAY, 9, 1)
    ):
        return {"status": "skipped", "reason": "outside_authorized_0900_window"}
    runtime.load_environment()
    if part == "prepare":
        schedule = AcceptanceSchedule(
            target_date=DAY,
            recipient_scope=SCOPE,
            frozen_at=now,
            send_at=at(DAY, 9),
            deadline=at(DAY, 9, 1),
        )
        with CONFIG.open("x", encoding="utf-8") as handle:
            handle.write(schedule.model_dump_json(indent=2))
    else:
        schedule = AcceptanceSchedule.model_validate_json(
            CONFIG.read_text(encoding="utf-8")
        )
        if (
            schedule.recipient_scope != SCOPE
            or schedule.send_at != at(DAY, 9)
            or schedule.deadline != at(DAY, 9, 1)
        ):
            raise ValueError("acceptance_config_mismatch")
    db = runtime.engine()
    resources = transport = None
    try:
        outbox = TelegramOutboxStore(
            db, recipient_scope=SCOPE, monthly_limit=100, schedule=schedule
        )
        if part == "prepare":
            settings = replace(LiveCollectionSettings.from_env(), recipient_scope=SCOPE)
            resources = LiveCollectionResources(
                db, settings=settings, outbox_store=outbox, schedule=schedule
            )
            result = resources.preparation.prepare()
            report = {
                k: result[k]
                for k in (
                    "status",
                    "reason",
                    "edition_id",
                    "outbox_id",
                    "market_status",
                    "news_status",
                    "failed_stage",
                    "exception_type",
                    "frames",
                )
                if k in result
            }
            edition = NewsletterStore(db, schedule=schedule).get(
                fingerprint([SCOPE, DAY.isoformat(), "morning"]), now=datetime.now(UTC)
            )
            if edition is not None:
                report.update(
                    price_count=edition.price_count,
                    news_count=edition.news_count,
                    reasons=edition.reasons,
                )
            return report
        edition_key = fingerprint([SCOPE, DAY.isoformat(), "morning"])
        edition = NewsletterStore(db, schedule=schedule).get(edition_key, now=now)
        if edition is None or edition.status not in {"ready", "partial"}:
            return {"status": "failed", "reason": "acceptance_edition_not_ready"}
        key = outbox.enqueue(edition.key, now=now, mode="live")
        with (runtime.CACHE / "2026-11-06_0900_send.attempt.json").open(
            "x", encoding="utf-8"
        ) as handle:
            json.dump(
                {"started_at": now.isoformat(), "edition_id": edition.key}, handle
            )
        transport = TelegramTransport(
            token=os.environ["XFOLIO_TELEGRAM_BOT_TOKEN"],
            chat_id=os.environ["XFOLIO_TELEGRAM_CHAT_ID"],
        )
        row = dispatch(outbox, key, transport, clock=lambda: datetime.now(UTC))
        return {
            k: row[k]
            for k in (
                "status",
                "transport_mode",
                "part_count",
                "created_at",
                "updated_at",
                "error_code",
            )
            if k in row
        }
    finally:
        if resources:
            resources.close()
        if transport:
            transport.close()
        db.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("prepare", "send"))
    args = parser.parse_args()
    logging.disable(logging.CRITICAL)
    from contextlib import redirect_stdout

    with (
        (runtime.CACHE / f"2026-11-06_0900_{args.phase}.log").open(
            "a", encoding="utf-8"
        ) as handle,
        redirect_stdout(handle),
    ):
        emit_event(
            {
                "event": "acceptance_0900",
                "phase": args.phase,
                "status": "started",
                "at": datetime.now(UTC).isoformat(),
            }
        )
        try:
            result = run(args.phase)
        except Exception as exc:  # noqa: BLE001 -- never log provider or credential data.
            result = {"status": "failed", **failure_details(exc, args.phase)}
        emit_event(
            {
                "event": "acceptance_0900",
                "phase": args.phase,
                "at": datetime.now(UTC).isoformat(),
                **{
                    k: (v.isoformat() if hasattr(v, "isoformat") else v)
                    for k, v in result.items()
                },
            }
        )
    emit_event({"phase": args.phase, "status": result["status"]})
    return 0 if result["status"] in {"ready", "partial", "confirmed", "skipped"} else 1


if __name__ == "__main__":
    with safe_process_diagnostics():
        raise SystemExit(main())
