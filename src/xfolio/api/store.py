"""PostgreSQL 저장 경계. DDL 실행과 외부 전송은 API가 수행하지 않는다."""

import hashlib
import json
import secrets
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

import sqlalchemy as sa

from xfolio.api.models import DecisionRequest
from xfolio.db.schema import (
    collection_runs,
    content_drafts,
    evidence_bundles,
    operations_events,
    publication_jobs,
    publication_posts,
    usage_ledger,
)


class ApiError(Exception):
    def __init__(self, code: str, status: int = 409):
        self.code, self.status = code, status


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class PostgresStore:
    def __init__(self, url: str):
        if not url.startswith(("postgresql://", "postgresql+psycopg://")):
            raise ValueError("PostgreSQL URL required")
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
        self.engine = sa.create_engine(url, pool_pre_ping=True, hide_parameters=True)

    def put_event(self, kind, key, payload, now, expires):
        with self.engine.begin() as conn:
            conn.execute(
                operations_events.insert().values(
                    id=secrets.token_hex(16),
                    kind=kind,
                    scope="auth",
                    unique_key=token_hash(key),
                    created_at=now,
                    expires_at=expires,
                    payload=payload,
                )
            )

    def take_event(self, kind, key, now):
        with self.engine.begin() as conn:
            row = (
                conn.execute(
                    operations_events.delete()
                    .where(
                        operations_events.c.kind == kind,
                        operations_events.c.unique_key == token_hash(key),
                    )
                    .returning(operations_events)
                )
                .mappings()
                .first()
            )
            return row["payload"] if row and row["expires_at"] > now else None

    def get_session(self, key, now):
        with self.engine.begin() as conn:
            row = (
                conn.execute(
                    sa.select(operations_events)
                    .where(
                        operations_events.c.kind == "session",
                        operations_events.c.unique_key == token_hash(key),
                    )
                    .with_for_update()
                )
                .mappings()
                .first()
            )
            if not row or row["expires_at"] <= now:
                return None
            payload = row["payload"]
            if (
                datetime.fromisoformat(payload["last_seen"]) + timedelta(minutes=30)
                <= now
            ):
                return None
            payload = dict(payload, last_seen=now.isoformat())
            conn.execute(
                operations_events.update()
                .where(operations_events.c.id == row["id"])
                .values(payload=payload)
            )
            return payload

    def _draft(self, conn, draft_id, lock=False):
        query = (
            sa.select(
                publication_jobs,
                content_drafts.c.version,
                content_drafts.c.synthetic,
                content_drafts.c.validation_passed,
                content_drafts.c.payload.label("draft_payload"),
            )
            .join(content_drafts, publication_jobs.c.draft_id == content_drafts.c.id)
            .where(publication_jobs.c.id == draft_id)
        )
        if lock:
            query = query.with_for_update(of=publication_jobs)
        row = conn.execute(query).mappings().first()
        if not row:
            raise ApiError("NOT_FOUND", 404)
        return row

    @staticmethod
    def serialize(row, mode):
        payload = row["draft_payload"]
        posts = payload.get("posts", [])
        return {
            "id": row["id"],
            "target_date": row["target_date"],
            "edition": row["edition"],
            "market_trade_date": payload.get("market_trade_date"),
            "version": row["version"],
            "decision_revision": row["decision_revision"],
            "status": row["status"],
            "news_count": sum(p["kind"] == "news" for p in posts),
            "scheduled_at": row["scheduled_at"],
            "expires_at": row["expires_at"],
            "mode": mode,
            "synthetic": row["synthetic"],
            "validation": payload.get(
                "validation", {"status": "pending", "blocking_reasons": []}
            ),
            "frozen_at": payload.get("frozen_at"),
            "posts": posts,
            "allowed_actions": ["approve", "hold"]
            if row["status"] == "validated"
            and mode == "reviewed"
            and not row["synthetic"]
            else (
                ["hold"]
                if row["status"] in {"validated", "scheduled", "sending"}
                else []
            ),
            "publication": {"job_id": row["id"], "posts": []},
            "history": [],
            "hold_reason": row["payload"].get("hold_reason"),
        }

    def detail(self, draft_id, mode):
        with self.engine.connect() as conn:
            result = self.serialize(self._draft(conn, draft_id), mode)
            for post in result["posts"]:
                post["evidence"] = []
                for evidence_id in post.get("evidence_ids", []):
                    record = (
                        conn.execute(
                            sa.select(evidence_bundles).where(
                                evidence_bundles.c.id == evidence_id
                            )
                        )
                        .mappings()
                        .first()
                    )
                    if record and record["rights_verified"]:
                        allowed = record["payload"]
                        post["evidence"].append(
                            {
                                "id": record["id"],
                                "source": allowed.get("source", record["source_id"]),
                                "url": allowed.get("url"),
                                "published_at": record["published_at"].isoformat()
                                if record["published_at"]
                                else None,
                                "collected_at": record["collected_at"].isoformat(),
                                "text": allowed.get("permitted_excerpt", ""),
                                "claims": allowed.get("claims", []),
                                "event_key": record["event_key"],
                                "fact_version": allowed.get("fact_version"),
                            }
                        )
            result["publication"]["posts"] = [
                dict(row)
                for row in conn.execute(
                    sa.select(
                        publication_posts.c.position,
                        publication_posts.c.state,
                        publication_posts.c.x_id,
                    ).where(publication_posts.c.job_id == draft_id)
                ).mappings()
            ]
            return result

    def list_drafts(
        self, mode, target_date=None, edition=None, status=None, after=None, limit=21
    ):
        with self.engine.connect() as conn:
            query = sa.select(publication_jobs.c.id)
            for column, value in [
                (publication_jobs.c.target_date, target_date),
                (publication_jobs.c.edition, edition),
                (publication_jobs.c.status, status),
            ]:
                if value is not None:
                    query = query.where(column == value)
            if after:
                from datetime import date

                last_date, last_edition, last_id = (
                    date.fromisoformat(after[0]),
                    after[1],
                    after[2],
                )
                query = query.where(
                    sa.or_(
                        publication_jobs.c.target_date < last_date,
                        sa.and_(
                            publication_jobs.c.target_date == last_date,
                            publication_jobs.c.edition > last_edition,
                        ),
                        sa.and_(
                            publication_jobs.c.target_date == last_date,
                            publication_jobs.c.edition == last_edition,
                            publication_jobs.c.id > last_id,
                        ),
                    )
                )
            ids = (
                conn.execute(
                    query.order_by(
                        publication_jobs.c.target_date.desc(),
                        publication_jobs.c.edition,
                        publication_jobs.c.id,
                    ).limit(limit)
                )
                .scalars()
                .all()
            )
            return [self.serialize(self._draft(conn, key), mode) for key in ids]

    def summary(self):
        month = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m")
        with self.engine.connect() as conn:
            run = (
                conn.execute(
                    sa.select(collection_runs)
                    .order_by(collection_runs.c.finished_at.desc())
                    .limit(1)
                )
                .mappings()
                .first()
            )
            totals = dict(
                conn.execute(
                    sa.select(
                        usage_ledger.c.state, sa.func.sum(usage_ledger.c.amount_krw)
                    )
                    .where(usage_ledger.c.month == month)
                    .group_by(usage_ledger.c.state)
                ).all()
            )
            counts = dict(
                conn.execute(
                    sa.select(publication_jobs.c.status, sa.func.count()).group_by(
                        publication_jobs.c.status
                    )
                ).all()
            )
            return {
                "collection": {
                    "status": run["status"] if run else "not_observed",
                    "last_finished_at": run["finished_at"].isoformat() if run else None,
                },
                "usage": {
                    **{
                        f"{k}_krw": float(totals.get(k, 0))
                        for k in ("estimated", "reserved", "confirmed")
                    },
                    "monthly_limit_krw": 50000,
                },
                "publications": {
                    k: counts.get(k, 0) for k in ("published", "held", "unknown")
                },
                "alerts": {"open": 0, "failed": 0, "status": "not_implemented"},
            }

    def decide(self, draft_id, operator, key, request: DecisionRequest, mode, now):
        body = request.model_dump(mode="json")
        request_hash = token_hash(json.dumps(body, sort_keys=True))
        scope = f"{operator}:{draft_id}"
        with self.engine.begin() as conn:
            # account-wide serialization also covers shared monthly budget and PM quota.
            conn.execute(sa.text("SELECT pg_advisory_xact_lock(718435902)"))
            row = self._draft(conn, draft_id, lock=True)
            prior = (
                conn.execute(
                    sa.select(operations_events).where(
                        operations_events.c.kind == "decision",
                        operations_events.c.scope == scope,
                        operations_events.c.unique_key == key,
                    )
                )
                .mappings()
                .first()
            )
            if prior:
                if prior["payload"]["request_hash"] != request_hash:
                    raise ApiError("IDEMPOTENCY_CONFLICT")
                return {
                    **prior["payload"]["result"],
                    "applied": False,
                    "replayed": True,
                    "version": row["version"],
                    "decision_revision": row["decision_revision"],
                    "status": row["status"],
                    "original_result": prior["payload"]["result"],
                }
            if row["version"] != request.expected_version:
                raise ApiError("VERSION_CONFLICT")
            if row["decision_revision"] != request.expected_decision_revision:
                raise ApiError("DECISION_CONFLICT")
            if request.action == "approve":
                if mode != "reviewed" or row["synthetic"]:
                    raise ApiError("MODE_BLOCKED")
                if row["status"] != "validated" or not row["validation_passed"]:
                    raise ApiError("VALIDATION_BLOCKED")
                if row["first_attempt_at"]:
                    raise ApiError("TRANSMISSION_STARTED")
                if (
                    now >= row["expires_at"]
                    or now.astimezone(ZoneInfo("Asia/Seoul")).date()
                    != row["target_date"]
                ):
                    raise ApiError("DEADLINE_PASSED")
                payload = row["draft_payload"]
                posts = payload.get("posts", [])
                expected_hash = hashlib.sha256(
                    json.dumps(
                        payload,
                        sort_keys=True,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ).encode()
                ).hexdigest()
                content_hash = conn.scalar(
                    sa.select(content_drafts.c.content_hash).where(
                        content_drafts.c.id == row["draft_id"]
                    )
                )
                if not secrets.compare_digest(expected_hash, content_hash):
                    raise ApiError("VALIDATION_BLOCKED")
                if not payload.get("rights_verified") or not payload.get(
                    "collection_complete"
                ):
                    raise ApiError("VALIDATION_BLOCKED")
                if not 1 <= len(posts) <= (3 if row["edition"] == "AM" else 2):
                    raise ApiError("VALIDATION_BLOCKED")
                if [p.get("position") for p in posts] != list(range(1, len(posts) + 1)):
                    raise ApiError("VALIDATION_BLOCKED")
                if row["edition"] == "AM" and (
                    [p.get("kind") for p in posts]
                    != ["index"] + ["news"] * (len(posts) - 1)
                ):
                    raise ApiError("VALIDATION_BLOCKED")
                if row["edition"] == "PM" and any(
                    p.get("kind") != "news" for p in posts
                ):
                    raise ApiError("VALIDATION_BLOCKED")
                events = [p.get("event_key") for p in posts if p.get("kind") == "news"]
                if len(events) != len(set(events)):
                    raise ApiError("DUPLICATE_EVENT")
                cutoff = datetime.combine(
                    row["target_date"], datetime.min.time(), ZoneInfo("Asia/Seoul")
                ) + timedelta(hours=17, minutes=45)
                if row["edition"] == "PM":
                    try:
                        frozen_at = datetime.fromisoformat(payload["frozen_at"])
                    except (ValueError, KeyError, TypeError):
                        raise ApiError("VALIDATION_BLOCKED") from None
                    if frozen_at.tzinfo is None or frozen_at > cutoff:
                        raise ApiError("VALIDATION_BLOCKED")
                for post in posts:
                    evidence_ids = post.get("evidence_ids", [])
                    if not evidence_ids or not post.get("text", "").strip():
                        raise ApiError("VALIDATION_BLOCKED")
                    for evidence_id in evidence_ids:
                        evidence = (
                            conn.execute(
                                sa.select(evidence_bundles).where(
                                    evidence_bundles.c.id == evidence_id
                                )
                            )
                            .mappings()
                            .first()
                        )
                        if not evidence or not evidence["rights_verified"]:
                            raise ApiError("VALIDATION_BLOCKED")
                        if row["edition"] == "PM" and (
                            not evidence["published_at"]
                            or evidence["published_at"] > cutoff - timedelta(minutes=15)
                            or evidence["collected_at"] > frozen_at
                        ):
                            raise ApiError("VALIDATION_BLOCKED")
                if row["edition"] == "PM":
                    used = conn.scalar(
                        sa.select(
                            sa.func.coalesce(
                                sa.func.sum(publication_jobs.c.reserved_count), 0
                            )
                        ).where(
                            publication_jobs.c.account_id == row["account_id"],
                            publication_jobs.c.target_date == row["target_date"],
                            publication_jobs.c.edition == "PM",
                        )
                    )
                    if used + len(posts) > 2:
                        raise ApiError("QUOTA_BLOCKED")
                cost = payload.get("max_cost_krw")
                try:
                    cost = Decimal(str(cost))
                except (InvalidOperation, TypeError, ValueError):
                    raise ApiError("BUDGET_BLOCKED") from None
                if not cost.is_finite() or cost < 0:
                    raise ApiError("BUDGET_BLOCKED")
                month = now.astimezone(ZoneInfo("Asia/Seoul")).strftime("%Y-%m")
                spent = conn.scalar(
                    sa.select(
                        sa.func.coalesce(sa.func.sum(usage_ledger.c.amount_krw), 0)
                    ).where(
                        usage_ledger.c.month == month,
                        usage_ledger.c.state.in_(
                            ["estimated", "reserved", "confirmed"]
                        ),
                    )
                )
                if spent + cost > 50000:
                    raise ApiError("BUDGET_BLOCKED")
                for post in posts:
                    if post.get("kind") == "news" and not all(
                        post.get(field) for field in ("event_key", "fact_version")
                    ):
                        raise ApiError("VALIDATION_BLOCKED")
                    if post.get("kind") == "news" and conn.scalar(
                        sa.select(sa.func.count())
                        .select_from(publication_posts)
                        .where(
                            publication_posts.c.account_id == row["account_id"],
                            publication_posts.c.event_key == post["event_key"],
                            publication_posts.c.fact_version == post["fact_version"],
                            sa.or_(
                                publication_posts.c.active_claim.is_(True),
                                publication_posts.c.state.in_(
                                    ["published", "unknown", "sending"]
                                ),
                            ),
                        )
                    ):
                        raise ApiError("DUPLICATE_EVENT")
                    conn.execute(
                        publication_posts.insert().values(
                            id=secrets.token_hex(16),
                            job_id=draft_id,
                            account_id=row["account_id"],
                            position=post["position"],
                            content_version=row["version"],
                            event_key=post.get("event_key"),
                            fact_version=post.get("fact_version"),
                            state="reserved",
                            active_claim=post.get("kind") == "news",
                            payload={"version": row["version"]},
                        )
                    )
                status, reserved = "scheduled", len(posts)
                conn.execute(
                    usage_ledger.insert().values(
                        id=secrets.token_hex(16),
                        provider="X",
                        month=month,
                        job_id=draft_id,
                        state="reserved",
                        amount_krw=cost,
                        payload={"decision_key": key},
                    )
                )
            else:
                if row["status"] not in {
                    "prepared",
                    "validated",
                    "approved",
                    "scheduled",
                    "sending",
                }:
                    raise ApiError("DECISION_CONFLICT")
                status = "sending" if row["first_attempt_at"] else "held"
                reserved = row["reserved_count"] if row["first_attempt_at"] else 0
                if not row["first_attempt_at"]:
                    conn.execute(
                        usage_ledger.update()
                        .where(
                            usage_ledger.c.job_id == draft_id,
                            usage_ledger.c.state == "reserved",
                        )
                        .values(state="released")
                    )
                    conn.execute(
                        publication_posts.update()
                        .where(
                            publication_posts.c.job_id == draft_id,
                            publication_posts.c.state == "reserved",
                        )
                        .values(active_claim=False, state="cancelled")
                    )
            revision = row["decision_revision"] + 1
            conn.execute(
                publication_jobs.update()
                .where(publication_jobs.c.id == draft_id)
                .values(
                    status=status,
                    decision_revision=revision,
                    reserved_count=reserved,
                    stop_requested=request.action == "hold",
                    payload={
                        **row["payload"],
                        "hold_reason": request.reason
                        if request.action == "hold"
                        else None,
                    },
                )
            )
            decision_id = secrets.token_hex(16)
            result = {
                "decision_id": decision_id,
                "applied": True,
                "replayed": False,
                "version": row["version"],
                "decision_revision": revision,
                "status": status,
            }
            conn.execute(
                operations_events.insert().values(
                    id=decision_id,
                    kind="decision",
                    scope=scope,
                    unique_key=key,
                    created_at=now,
                    payload={"request_hash": request_hash, "result": result},
                )
            )
            return result
