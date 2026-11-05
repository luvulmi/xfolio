"""아침 편성 미리보기/파일 검사. 이 명령은 외부 송신을 수행하지 않는다."""

import json
import os
from datetime import UTC, datetime

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from xfolio.newsletter.demo import demo_inputs
from xfolio.newsletter.edition import (
    MorningInputs,
    NewsletterError,
    SendContext,
    at,
    build_morning,
    check_send,
)
from xfolio.newsletter.store import NewsletterStore


def execute(args):
    db = None
    try:
        if args.save and args.inputs_file is None:
            raise NewsletterError("save_requires_collected_inputs_file")
        inputs = (
            MorningInputs.model_validate_json(
                args.inputs_file.read_text(encoding="utf-8-sig")
            )
            if args.inputs_file
            else demo_inputs(args.scenario)
        )
        now = args.prepared_at or (
            datetime.now(UTC) if args.inputs_file else at(inputs.target_date, 7, 58)
        )
        if args.save:
            url = os.environ.get("XFOLIO_API_DATABASE_URL", "")
            if not url:
                raise NewsletterError("explicit_api_database_url_required")
            db = NewsletterStore.from_url(url)
            edition = db.save(inputs, now=now)
        else:
            edition = build_morning(inputs, now=now)
        context = (
            SendContext.model_validate_json(
                args.context_file.read_text(encoding="utf-8-sig")
            )
            if args.context_file
            else None
        )
        decision = (
            (db.check(edition.key, context) if db else check_send(edition, context))
            if context
            else None
        )
        report = {
            "mode": "preview",
            "network_requests": 0,
            "database_writes": bool(db),
            "can_send": False,
            "edition": edition.model_dump(mode="json"),
            "send_check": decision.model_dump(mode="json") if decision else None,
            "check_scope": "database_and_context" if db else "local_inputs_only",
        }
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            print(edition.body)
            print(f"\n준비 상태: {edition.status}")
            print(
                "실제 송신 없음 · " + (" / ".join(edition.reasons) or "편성 검사 통과")
            )
            if decision:
                print(
                    "발송 직전 검사: "
                    + ("통과" if decision.can_send else " / ".join(decision.reasons))
                )
        if edition.status == "failed" or decision is not None and not decision.can_send:
            raise SystemExit(1)
    except (OSError, ValueError, SQLAlchemyError) as exc:
        reason = (
            str(exc)
            if isinstance(exc, NewsletterError)
            else "invalid_input_or_database"
            if isinstance(exc, (ValidationError, SQLAlchemyError))
            else "input_error"
        )
        print(json.dumps({"status": "failed", "reason": reason, "can_send": False}))
        raise SystemExit(1) from None
    finally:
        if db:
            db.engine.dispose()
