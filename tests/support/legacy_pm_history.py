"""기존 PM 자료의 격리 DB fixture 생성. 제품 진입점이 아니다."""

import secrets
from datetime import datetime, time, timedelta
from decimal import Decimal, InvalidOperation

import sqlalchemy as sa

from xfolio.ai.validation import PROFILE
from xfolio.ai.workflow import WorkflowError
from xfolio.db.schema import content_drafts, publication_jobs
from xfolio.legacy.news_edition import (
    ASSEMBLY_PROFILE,
    KST,
    bls_pm_validation,
    payload_hash,
)


def seed_historical_bls_pm(
    engine,
    draft_id,
    *,
    collection_run_id,
    account_id,
    target_date,
    now,
    max_publish_cost_krw,
):
    """이전 DDL/fixture 대조용 구현. 제품 경로에서 호출하지 않는다."""
    if now.utcoffset() is None or not account_id or not account_id.strip():
        raise WorkflowError("EDITION_INPUT_INVALID")
    try:
        cost = Decimal(str(max_publish_cost_krw))
    except (InvalidOperation, ValueError, TypeError):
        raise WorkflowError("PUBLISH_COST_REQUIRED") from None
    if not cost.is_finite() or cost < 0:
        raise WorkflowError("PUBLISH_COST_REQUIRED")
    with engine.begin() as conn:
        conn.execute(sa.text("SELECT pg_advisory_xact_lock(718435902)"))
        existing = conn.scalar(
            sa.select(publication_jobs.c.id).where(
                publication_jobs.c.account_id == account_id,
                publication_jobs.c.target_date == target_date,
                publication_jobs.c.edition == "PM",
            )
        )
        if existing:
            raise WorkflowError("EDITION_ALREADY_EXISTS")
        original = (
            conn.execute(
                sa.select(content_drafts)
                .where(content_drafts.c.id == draft_id)
                .with_for_update()
            )
            .mappings()
            .one_or_none()
        )
        if (
            not original
            or original["edition_id"] != "unassembled:" + draft_id
            or original["content_hash"] != payload_hash(original["payload"])
            or original["payload"].get("generation_validation", {}).get("profile")
            != PROFILE
            or original["payload"].get("target_date") != target_date.isoformat()
        ):
            raise WorkflowError("GENERATED_DRAFT_INVALID")
        job_id, assembled_id = secrets.token_hex(16), secrets.token_hex(16)
        payload = {
            **original["payload"],
            "assembly_profile": ASSEMBLY_PROFILE,
            "source_draft_id": draft_id,
            "collection_run_id": collection_run_id,
            "frozen_at": now.isoformat(),
            "max_cost_krw": str(cost),
        }
        reasons, lengths = bls_pm_validation(
            conn, payload, target_date, now, original["synthetic"]
        )
        payload["collection_complete"] = "EDITION_COLLECTION_REQUIRED" not in reasons
        payload["validation"] = {
            "status": "passed" if not reasons else "failed",
            "blocking_reasons": reasons,
        }
        payload["weighted_lengths"] = lengths
        conn.execute(
            content_drafts.insert().values(
                id=assembled_id,
                edition_id=job_id,
                version=1,
                content_hash=payload_hash(payload),
                synthetic=original["synthetic"],
                validation_passed=not reasons,
                payload=payload,
            )
        )
        scheduled = datetime.combine(target_date, time(18), KST)
        conn.execute(
            publication_jobs.insert().values(
                id=job_id,
                account_id=account_id,
                target_date=target_date,
                edition="PM",
                draft_id=assembled_id,
                status="validated" if not reasons else "prepared",
                scheduled_at=scheduled,
                expires_at=scheduled + timedelta(minutes=10),
                payload={"assembly_profile": ASSEMBLY_PROFILE},
            )
        )
    return job_id
