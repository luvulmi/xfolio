"""기본 무통신 worker. 서버 어댑터를 주입한 준비/송신과 예약 진입점."""

import argparse
import json
import os
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy.exc import SQLAlchemyError

from xfolio.domestic.calendar import KST, local_calendar
from xfolio.jobs.collection import CollectionError
from xfolio.jobs.outbox import OutboxError, TelegramOutboxStore, dispatch
from xfolio.jobs.telegram import MockTelegramTransport, TelegramTransport, split_text
from xfolio.news.collection import aware
from xfolio.news.collection_store import NewsletterNewsStore
from xfolio.newsletter.demo import demo_inputs
from xfolio.newsletter.edition import NewsletterError, at, build_morning, fingerprint


class MorningWorker:
    """T02/T03 준비 어댑터는 서버에서만 주입한다. 휴장은 어댑터 호출 전에 검사."""

    def __init__(
        self,
        *,
        calendar,
        collect_inputs,
        newsletter_store,
        outbox_store,
        transport,
        clock=lambda: datetime.now(UTC),
        preparation=None,
    ):
        self.calendar, self.collect_inputs = calendar, collect_inputs
        self.newsletter_store, self.outbox_store = newsletter_store, outbox_store
        self.transport, self.clock = transport, clock
        self.preparation = preparation

    def _state(self, day, now, status, reason):
        if self.outbox_store is not None:
            self.outbox_store.record_worker_state(
                day=day, status=status, reason=reason, now=now
            )
        return {"status": status, "reason": reason}

    def prepare(self):
        if self.preparation is not None:
            return self.preparation.prepare()
        now = aware(self.clock())
        day = now.astimezone(KST).date()
        if day.weekday() >= 5:
            return self._state(day, now, "skipped", "weekend")
        if not at(day, 7, 50) <= now < at(day, 8, 10):
            return self._state(day, now, "failed", "outside_preparation_window")
        opened = self.calendar(day, now)
        if opened is not True:
            return self._state(
                day,
                now,
                "skipped" if opened is False else "failed",
                "market_closed" if opened is False else "calendar_unverified",
            )
        inputs = self.collect_inputs(day=day, frozen_at=at(day, 7, 50))
        edition = self.newsletter_store.save(inputs, now=aware(self.clock()))
        key = None
        if edition.status in {"ready", "partial"}:
            key = self.outbox_store.enqueue(
                edition.key, now=self.clock(), mode=self.transport.mode
            )
        return {"status": edition.status, "edition_id": edition.key, "outbox_id": key}

    def send(self):
        now = aware(self.clock())
        day = now.astimezone(KST).date()
        if day.weekday() >= 5:
            return self._state(day, now, "skipped", "market_closed_or_unverified")
        if not at(day, 8) <= now < at(day, 8, 10):
            return self._state(day, now, "skipped", "outside_send_window")
        if self.calendar(day, now) is not True:
            return self._state(day, now, "skipped", "market_closed_or_unverified")
        self.outbox_store.recover_stale(now=now)
        edition_key = fingerprint(
            [self.outbox_store.recipient_scope, day.isoformat(), "morning"]
        )
        edition = self.newsletter_store.get(edition_key, now=now)
        if edition is None:
            return self._state(day, now, "failed", "edition_missing_or_expired")
        if edition.status not in {"ready", "partial"}:
            return {"status": "skipped", "reason": "edition_not_prepared"}
        key = self.outbox_store.enqueue(edition.key, now=now, mode=self.transport.mode)
        row = dispatch(self.outbox_store, key, self.transport, clock=self.clock)
        return {
            "status": row["status"],
            "transport_mode": row["transport_mode"],
            "outbox_id": key,
        }


def create_scheduler(worker):
    from apscheduler.schedulers.blocking import BlockingScheduler

    scheduler = BlockingScheduler(timezone=KST)
    scheduler.add_job(
        worker.prepare,
        "cron",
        day_of_week="mon-fri",
        hour=7,
        minute=50,
        id="morning_prepare",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=60,
    )
    scheduler.add_job(
        worker.send,
        "cron",
        day_of_week="mon-fri",
        hour=8,
        minute="0-9",
        id="morning_send",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=30,
    )
    return scheduler


class MockWorker:
    """합성 데이터는 메모리에서만 사용하며 현재/실제 수신으로 표시하지 않는다."""

    def __init__(self, *, clock=lambda: datetime.now(UTC)):
        self.clock = clock

    def prepare(self):
        return self.send()

    def send(self):
        now = self.clock()
        day = now.astimezone(KST).date()
        schedule = local_calendar().schedule(start_date=day, end_date=day)
        if day.weekday() >= 5 or schedule.empty:
            return {
                "mode": "mock",
                "synthetic": True,
                "status": "skipped",
                "reason": "local_calendar_closed",
                "network_requests": 0,
                "database_writes": 0,
                "can_send": False,
            }
        value = demo_inputs(target_date=day)
        edition = build_morning(value, now=at(day, 7, 58))
        transport = MockTelegramTransport()
        for text in split_text(edition.body):
            transport.send(text)
        return {
            "mode": "mock",
            "synthetic": True,
            "status": "mock_complete",
            "edition_status": edition.status,
            "part_count": len(transport.sent),
            "network_requests": 0,
            "database_writes": 0,
            "can_send": False,
        }


def main(argv=None):
    parser = argparse.ArgumentParser(description="XFolio 독립 아침 worker")
    commands = parser.add_mutually_exclusive_group()
    commands.add_argument(
        "--once", action="store_true", help="무통신 합성 모의1회(기본)"
    )
    commands.add_argument(
        "--schedule", action="store_true", help="07:50/08:00 예약 실행"
    )
    parser.add_argument(
        "--live", action="store_true", help="서버 설정을 사용한 실제 송신 경로"
    )
    parser.add_argument("--phase", choices=("prepare", "send"), default="send")
    args = parser.parse_args(argv)
    db, transport, collection_resources = None, None, None
    try:
        worker = MockWorker()
        if args.live:
            if os.environ.get("XFOLIO_WORKER_LIVE_ACCEPTED") != "true":
                raise OutboxError("live_acceptance_required")
            url = os.environ.get("XFOLIO_WORKER_DATABASE_URL", "")
            if not url:
                raise OutboxError("explicit_worker_database_required")
            db = NewsletterNewsStore.from_url(url)
            transport = TelegramTransport(
                token=os.environ.get("XFOLIO_TELEGRAM_BOT_TOKEN", ""),
                chat_id=os.environ.get("XFOLIO_TELEGRAM_CHAT_ID", ""),
            )
            outbox_store = TelegramOutboxStore(
                db.engine,
                recipient_scope=os.environ.get("XFOLIO_RECIPIENT_SCOPE", "self"),
                monthly_limit=Decimal(
                    os.environ.get("XFOLIO_MONTHLY_BUDGET_KRW", "50000")
                ),
            )
            import sqlalchemy as sa

            from xfolio.db.domestic import calendar_days
            from xfolio.newsletter.store import NewsletterStore

            def calendar(day, now):
                with db.engine.connect() as conn:
                    return conn.scalar(
                        sa.select(calendar_days.c.is_open).where(
                            calendar_days.c.observed_on == day,
                            calendar_days.c.trade_date == day,
                            calendar_days.c.retrieved_at <= now,
                        )
                    )

            preparation = None
            if args.phase == "prepare" or args.schedule:
                from xfolio.jobs.collection import (
                    LiveCollectionResources,
                    LiveCollectionSettings,
                )

                collection_resources = LiveCollectionResources(
                    db.engine,
                    settings=LiveCollectionSettings.from_env(),
                    outbox_store=outbox_store,
                )
                preparation = collection_resources.preparation
                calendar = preparation.calendar

            worker = MorningWorker(
                calendar=calendar,
                collect_inputs=None,
                newsletter_store=NewsletterStore(db.engine),
                outbox_store=outbox_store,
                transport=transport,
                preparation=preparation,
            )
        if args.schedule:
            create_scheduler(worker).start()
            return 0
        result = worker.prepare() if args.phase == "prepare" else worker.send()
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (
        OutboxError,
        NewsletterError,
        ValueError,
        InvalidOperation,
        SQLAlchemyError,
    ) as exc:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "reason": str(exc)
                    if isinstance(exc, (OutboxError, NewsletterError, CollectionError))
                    else "worker_configuration_or_storage_error",
                    "can_send": False,
                }
            )
        )
        return 1
    finally:
        if collection_resources:
            collection_resources.close()
        if transport:
            transport.close()
        if db:
            db.engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
