"""확인된 단일 BLS CPI 초안을 PM 편성으로 묶는 저장 경계. 외부 전송은 없다."""

import json
import secrets
from datetime import datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

import sqlalchemy as sa
from pydantic import ValidationError

from xfolio.bls import RELEASE_URL
from xfolio.db.schema import (
    collection_runs,
    content_drafts,
    evidence_bundles,
    publication_jobs,
)
from xfolio.news_contracts import EvidenceClaim, NewsEvent, digest
from xfolio.news_validation import (
    PROFILE,
    DraftValidationError,
    validate_stored_cpi_post,
)
from xfolio.news_workflow import TEXT_SCOPE, PermissionReview, WorkflowError

KST = ZoneInfo("Asia/Seoul")
ASSEMBLY_PROFILE = "bls_cpi_pm_v1"
COLLECTION_SCOPE = "bls_cpi_single_source_v1"


def payload_hash(payload):
    return digest(
        json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    )


def record_bls_collection(engine, bundle, *, started_at, finished_at):
    """호출자가 완료한 고정 URL 1조회만 기록한다. 전체 뉴스 완주가 아니다."""
    source = bundle.source
    if (
        started_at.utcoffset() is None
        or finished_at.utcoffset() is None
        or not started_at < source.retrieved_at <= finished_at
        or source.source_url != RELEASE_URL
        or source.provider != "BLS"
    ):
        raise WorkflowError("COLLECTION_TIME_OR_SCOPE_INVALID")
    with engine.begin() as conn:
        conn.execute(
            collection_runs.insert().values(
                id=source.collection_run_id,
                provider="BLS",
                window_start=started_at,
                window_end=source.retrieved_at,
                finished_at=finished_at,
                status="complete",
                payload={
                    "scope": COLLECTION_SCOPE,
                    "window_kind": "retrieval",
                    "expected_urls": [RELEASE_URL],
                    "completed_urls": [RELEASE_URL],
                    "source_versions": [
                        {
                            "source_id": source.source_id,
                            "content_version": source.content_version,
                        }
                    ],
                },
            )
        )
    return source.collection_run_id


def bls_pm_validation(conn, payload, target_date, now, synthetic):
    """편성 생성과 승인 때 같은 원본·권한·시각·의미·길이를 재검사한다."""
    reasons = []
    lengths = []
    try:
        frozen = datetime.fromisoformat(payload["frozen_at"])
        if frozen.utcoffset() is None:
            raise ValueError
    except (ValueError, KeyError, TypeError):
        return ["FREEZE_TIME_INVALID"], lengths
    cutoff = datetime.combine(target_date, time(17, 45), KST)
    if frozen > cutoff or frozen > now or frozen.astimezone(KST).date() != target_date:
        reasons.append("PM_FREEZE_DEADLINE_PASSED")
    run = (
        conn.execute(
            sa.select(collection_runs).where(
                collection_runs.c.id == payload.get("collection_run_id")
            )
        )
        .mappings()
        .first()
    )
    posts = payload.get("posts", [])
    if (
        len(posts) != 1
        or posts[0].get("kind") != "news"
        or posts[0].get("position") != 1
    ):
        return [*reasons, "BLS_SINGLE_NEWS_REQUIRED"], lengths
    evidence_ids = posts[0].get("evidence_ids", [])
    if len(evidence_ids) != 1:
        return [*reasons, "EVIDENCE_REQUIRED"], lengths
    evidence = (
        conn.execute(
            sa.select(evidence_bundles).where(evidence_bundles.c.id == evidence_ids[0])
        )
        .mappings()
        .first()
    )
    if not evidence or not evidence["rights_verified"]:
        return [*reasons, "PERMISSION_SCOPE_UNVERIFIED"], lengths
    data = evidence["payload"]
    expected_versions = [
        {
            "source_id": evidence["source_id"],
            "content_version": evidence["content_version"],
        }
    ]
    if (
        not run
        or run["provider"] != "BLS"
        or run["status"] != "complete"
        or run["finished_at"] > frozen
        or not run["window_start"] < evidence["collected_at"] <= run["window_end"]
        or run["payload"].get("scope") != COLLECTION_SCOPE
        or run["payload"].get("window_kind") != "retrieval"
        or run["payload"].get("expected_urls") != [RELEASE_URL]
        or run["payload"].get("completed_urls") != [RELEASE_URL]
        or run["payload"].get("source_versions") != expected_versions
        or data.get("collection_run_id") != run["id"]
    ):
        reasons.append("EDITION_COLLECTION_REQUIRED")
    if (
        not evidence["published_at"]
        or evidence["published_at"] > cutoff - timedelta(minutes=15)
        or evidence["collected_at"] > frozen
        or evidence["published_at"] > evidence["collected_at"]
    ):
        reasons.append("SOURCE_TIME_INVALID")
    try:
        review = PermissionReview.model_validate(data.get("permission_review"))
        if (
            review.provider != "BLS"
            or review.source_id != evidence["source_id"]
            or review.content_version != evidence["content_version"]
            or review.source_url != RELEASE_URL
            or review.text_scope != TEXT_SCOPE
            or data.get("source") != "BLS"
            or data.get("url") != RELEASE_URL
            or data.get("text_scope") != TEXT_SCOPE
            or not review.reviewed_at <= frozen <= now < review.expires_at
            or (review.fixture_only and not synthetic)
            or any(
                getattr(review, purpose) != "permitted"
                for purpose in ("storage", "ai_transfer", "summary_publication")
            )
        ):
            reasons.append("PERMISSION_SCOPE_UNVERIFIED")
        claims = [EvidenceClaim.model_validate(c) for c in data["claims"]]
        if any(
            c.source_id != evidence["source_id"]
            or c.content_version != evidence["content_version"]
            or c.evidence_span not in data["permitted_excerpt"]
            for c in claims
        ):
            raise DraftValidationError("OUTPUT_EVIDENCE_MISMATCH")
        event = NewsEvent(
            subject_id="US:CPI-U",
            event_type="cpi_release",
            period_or_transaction=data["period"],
            claims=tuple(claims),
        )
        if (
            posts[0].get("event_key") != evidence["event_key"]
            or posts[0].get("fact_version") != data.get("fact_version")
            or event.event_key != evidence["event_key"]
            or event.fact_version != data.get("fact_version")
        ):
            raise DraftValidationError("OUTPUT_SOURCE_MISMATCH")
        if not evidence["published_at"]:
            raise DraftValidationError("SOURCE_TIME_INVALID")
        lengths.append(
            validate_stored_cpi_post(
                posts[0]["text"], claims, data["period"], evidence["published_at"]
            )
        )
        if posts[0].get("weighted_length") != lengths[0]:
            raise DraftValidationError("X_WEIGHTED_LENGTH_MISMATCH")
    except (ValidationError, ValueError, KeyError, TypeError) as exc:
        reasons.append(
            str(exc)
            if isinstance(exc, DraftValidationError)
            else "EVIDENCE_CONTRACT_INVALID"
        )
    return list(dict.fromkeys(reasons)), lengths


def assemble_bls_pm(
    engine,
    draft_id,
    *,
    collection_run_id,
    account_id,
    target_date,
    now,
    max_publish_cost_krw,
):
    """원초안을 보존하고 새 편성 버전·job을 원자적으로 만든다. 승인은 별도다."""
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
