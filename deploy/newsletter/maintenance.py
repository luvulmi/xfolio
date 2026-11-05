"""비밀 없는 보존 계획, 명시 DB의 만료 삭제 및 복원 후 검사. 자동 migration 없음."""

import argparse
import importlib
import json
import os
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.engine import make_url

RETENTION = {
    "newsletter_editions": 90,
    "domestic_price_snapshots": 90,
    "newsletter_news_items": 90,
    "newsletter_news_runs": 90,
    "notification_setting_audit": 365,
    "telegram_outbox": 365,
}
EVENT_RETENTION = {"newsletter_prepare": 90}
LEGACY_PAYLOAD_TABLES = (
    "evidence_bundles",
    "content_drafts",
    "publication_jobs",
    "publication_posts",
)
STORES = (
    ("xfolio.newsletter_store", "NewsletterStore", "purge_expired"),
    ("xfolio.domestic.store", "DomesticStore", "purge_expired_prices"),
    ("xfolio.newsletter_news_store", "NewsletterNewsStore", "purge_expired"),
    ("xfolio.notification_settings", "NotificationSettingsStore", "purge_expired"),
    ("xfolio.jobs.outbox", "TelegramOutboxStore", "purge_expired"),
    ("xfolio.jobs.collection", "PreparationStore", "purge_expired"),
)


class MaintenanceError(ValueError):
    pass


def plan():
    return {
        "mode": "plan",
        "database_accessed": False,
        "retention_days": RETENTION,
        "operations_event_retention_days": EVENT_RETENTION,
        "operating_logs_days": 30,
        "backup_max_days": 7,
        "raw_official_text_persisted": False,
        "legacy_payload_review_required": True,
        "restore_sequence": ["stop_worker", "restore_isolated", "purge", "verify"],
    }


def create_engine():
    raw = os.environ.get("XFOLIO_MAINTENANCE_DATABASE_URL", "")
    if not raw:
        raise MaintenanceError("explicit_maintenance_database_required")
    try:
        url = make_url(raw)
        if url.get_backend_name() != "postgresql":
            raise ValueError
        url = url.set(drivername="postgresql+psycopg")
        if url.host not in {"localhost", "127.0.0.1", "::1"} and (
            url.query.get("sslmode") != "verify-full"
        ):
            raise MaintenanceError("remote_database_tls_verification_required")
        return sa.create_engine(url, hide_parameters=True)
    except MaintenanceError:
        raise
    except (TypeError, ValueError, sa.exc.ArgumentError):
        raise MaintenanceError("maintenance_database_invalid") from None


def utc_now(value=None):
    now = value or datetime.now(UTC)
    if now.tzinfo is None or now.utcoffset() is None:
        raise MaintenanceError("aware_time_required")
    return now.astimezone(UTC)


def verify(engine, *, now):
    now = utc_now(now)
    with engine.connect() as conn:
        names = set(sa.inspect(conn).get_table_names())
        missing = sorted((set(RETENTION) | {"operations_events"}) - names)
        if missing:
            raise MaintenanceError("newsletter_schema_incomplete")
        expired = {}
        for name in RETENTION:
            table = sa.Table(name, sa.MetaData(), autoload_with=conn)
            if "expires_at" not in table.c:
                raise MaintenanceError("retention_contract_incomplete")
            expired[name] = conn.scalar(
                sa.select(sa.func.count())
                .select_from(table)
                .where(table.c.expires_at <= now)
            )
        events = sa.Table("operations_events", sa.MetaData(), autoload_with=conn)
        if not {"kind", "expires_at"} <= set(events.c.keys()):
            raise MaintenanceError("retention_contract_incomplete")
        for kind in EVENT_RETENTION:
            expired[f"operations_events.{kind}"] = conn.scalar(
                sa.select(sa.func.count())
                .select_from(events)
                .where(events.c.kind == kind, events.c.expires_at <= now)
            )
        legacy = {}
        for name in LEGACY_PAYLOAD_TABLES:
            if name in names:
                table = sa.Table(name, sa.MetaData(), autoload_with=conn)
                legacy[name] = conn.scalar(
                    sa.select(sa.func.count()).select_from(table)
                )
    return {
        "mode": "verify",
        "checked_at": now.isoformat(),
        "expired_rows": expired,
        "legacy_payload_rows": legacy,
        "can_resume": not any(expired.values()) and not any(legacy.values()),
    }


def purge(engine, *, now):
    now = utc_now(now)
    # 실패 전 일부만 삭제하지 않도록 전체 schema와 서비스 존재부터 확인한다.
    verify(engine, now=now)
    services = [
        (getattr(importlib.import_module(module), cls), method)
        for module, cls, method in STORES
    ]
    counts = {}
    for cls, method in services:
        counts[cls.__name__] = getattr(cls(engine), method)(now=now)
    result = verify(engine, now=now)
    result.update(mode="purge", deleted=counts)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("plan", "verify", "purge"))
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    engine = None
    try:
        if args.action == "plan":
            result = plan()
        else:
            if args.action == "purge" and not args.execute:
                raise MaintenanceError("purge_requires_execute")
            engine = create_engine()
            now = datetime.now(UTC)
            result = (
                purge(engine, now=now)
                if args.action == "purge"
                else verify(engine, now=now)
            )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0 if result.get("can_resume", True) else 2
    except MaintenanceError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 1
    except (sa.exc.SQLAlchemyError, ImportError, AttributeError, OSError, RuntimeError):
        # URL/driver 오류/원문 payload를 로그에 출력하지 않는다.
        print(json.dumps({"error": "maintenance_failed"}))
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
