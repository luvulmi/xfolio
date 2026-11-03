"""국내 시세/마스터/90일 삭제의 명시적 실행 경로. 기본은 무통신 계획."""

import json
import os
from datetime import UTC, datetime

from sqlalchemy.exc import SQLAlchemyError

from xfolio.domestic.catalogue import fetch_master, search
from xfolio.domestic.kis import KisClient, KisSettings
from xfolio.domestic.models import DEFAULT_CODES, PRICE_RETENTION_DAYS, DomesticError
from xfolio.domestic.store import DomesticStore


def execute(args):
    if not args.run:
        print(
            json.dumps(
                {
                    "mode": "dry_run",
                    "command": args.command,
                    "network_requests": 0,
                    "database_writes": 0,
                    "price_retention_days": PRICE_RETENTION_DAYS,
                    "default_codes": DEFAULT_CODES,
                    "can_send": False,
                }
            )
        )
        return
    db = None
    try:
        if args.save or args.command == "domestic-prune":
            url = os.environ.get("XFOLIO_API_DATABASE_URL", "")
            if not url:
                raise DomesticError("explicit_api_database_url_required")
            db = DomesticStore.from_url(url)
        now = datetime.now(UTC)
        if args.command == "domestic-prune":
            print(
                json.dumps(
                    {
                        "deleted_price_snapshots": db.purge_expired_prices(now=now),
                        "price_retention_days": PRICE_RETENTION_DAYS,
                    }
                )
            )
        elif args.command == "domestic-catalogue":
            items = fetch_master(retrieved_at=now)
            if db:
                db.bootstrap(now)
                db.import_catalogue(items)
            hits = search(items, args.query) if args.query else ()
            print(
                json.dumps(
                    {
                        "instrument_count": len(items),
                        "saved": bool(db),
                        "hits": [i.model_dump(mode="json") for i in hits],
                    },
                    ensure_ascii=False,
                )
            )
        else:
            settings = KisSettings.from_env_file(args.env_file)
            with KisClient(settings, calendar_cache=db) as adapter:
                if db:
                    db.bootstrap(now)
                    result, saved = db.collect(adapter)
                else:
                    result, saved = adapter.collect(DEFAULT_CODES), None
                payload = result.model_dump(mode="json")
                payload["quotes"] = [
                    q.model_dump(mode="json")
                    | {
                        "raw_change_pct": str(q.raw_change_pct),
                        "change_pct": str(q.change_pct)
                        if q.change_pct is not None
                        else None,
                        "change_reason": q.change_reason,
                    }
                    for q in result.quotes
                ]
                print(
                    json.dumps(
                        {
                            "collection": payload,
                            "status": result.status,
                            "saved": saved,
                        },
                        ensure_ascii=False,
                    )
                )
                if result.status != "complete":
                    raise SystemExit(1)
    except (DomesticError, SQLAlchemyError) as exc:
        # SQLAlchemy hides parameters; still do not output URL/driver exception text.
        reason = str(exc) if isinstance(exc, DomesticError) else "database_error"
        print(json.dumps({"status": "failed", "reason": reason}))
        raise SystemExit(1) from None
    finally:
        if db:
            db.engine.dispose()
