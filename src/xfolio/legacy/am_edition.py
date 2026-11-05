"""세 ETF·공통 뉴스의 AM 편성 및 승인 재검사. 송신 기능은 포함하지 않는다."""

import json
import re
import secrets
import unicodedata
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Literal
from zoneinfo import ZoneInfo

import sqlalchemy as sa
from pydantic import AwareDatetime, Field, field_validator

from xfolio.ai.validation import BASES
from xfolio.db.schema import (
    collection_runs,
    content_drafts,
    evidence_bundles,
    operations_events,
    publication_jobs,
    publication_posts,
    usage_ledger,
)
from xfolio.legacy.etf import ETFSnapshot, completed_sessions, etf_post_text
from xfolio.news.contracts import digest
from xfolio.news.evaluation import NewsFacts, _number_in_span, evaluate_news_input
from xfolio.news.input import (
    ContentEvidence,
    Identifier,
    InputContract,
    NewsInput,
    NewsInputCollection,
)

KST = ZoneInfo("Asia/Seoul")
ASSEMBLY_PROFILE = "am_etf_news_v1"
VALIDATION_PROFILE = "etf_news_review_v1"


class AMError(ValueError):
    """원문/비밀을 포함하지 않는 안정 코드."""


def payload_hash(value):
    return digest(
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    )


def weighted_length(text, urls=()):
    if unicodedata.normalize("NFC", text) != text:
        raise AMError("TEXT_NORMALIZATION_REQUIRED")
    found = re.findall(r"https?://\S+", text)
    if found != list(urls):
        raise AMError("POST_SOURCE_URL_MISMATCH")
    body = text
    for url in urls:
        body = body.replace(url, "", 1)
    if (
        "http" in body
        or "www." in body
        or any(not (32 <= ord(c) <= 126 or 0xAC00 <= ord(c) <= 0xD7A3) for c in body)
    ):
        raise AMError("UNSUPPORTED_TEXT_CHARACTER")
    length = sum(1 if ord(c) <= 126 else 2 for c in body) + 23 * len(urls)
    if length > 280:
        raise AMError("X_WEIGHTED_LENGTH_EXCEEDED")
    return length


class NewsDraft(InputContract):
    record: NewsInput
    facts: NewsFacts
    body: Identifier
    claim_ids: tuple[Identifier, ...] = Field(min_length=1)
    generation_mode: Literal["mock", "live"]
    related: bool
    importance: Literal["critical", "material", "routine", "uncertain"]
    input_review_id: Identifier
    reviewed_by: Identifier
    reviewed_at: AwareDatetime
    review_reason: Identifier

    @field_validator("reviewed_at")
    @classmethod
    def utc_time(cls, value):
        return value.astimezone(UTC)


class AMInputs(InputContract):
    schema_version: Literal["am_etf_news_input_v1"] = "am_etf_news_input_v1"
    target_date: date
    market_run_id: Identifier
    snapshot: ETFSnapshot
    collections: tuple[NewsInputCollection, ...]
    news: tuple[NewsDraft, ...] = Field(default=(), max_length=3)
    window_start: AwareDatetime
    frozen_at: AwareDatetime
    max_publish_cost_krw: Decimal = Field(gt=0, allow_inf_nan=False)
    transport_mode: Literal["mock", "live"] = "mock"

    @field_validator("window_start", "frozen_at")
    @classmethod
    def utc_time(cls, value):
        return value.astimezone(UTC)

    @property
    def cutoff(self):
        return datetime.combine(self.target_date, time(7, 30), KST)

    @property
    def synthetic(self):
        return (
            self.snapshot.synthetic
            or any(r.synthetic for run in self.collections for r in run.records)
            or any(n.record.synthetic or n.generation_mode == "mock" for n in self.news)
        )


def news_post(news):
    if "http" in news.body or "www." in news.body:
        raise AMError("BODY_URL_NOT_ALLOWED")
    ids = tuple(c.claim_id for c in news.facts.claims)
    if len(set(news.claim_ids)) != len(news.claim_ids) or set(news.claim_ids) != set(
        ids
    ):
        raise AMError("CLAIM_LINKS_REQUIRED")
    # 자유문의 의미는 사람이 확인한다. 수치·기간·단위·조건 누락은 기계로도 막는다.
    for c in news.facts.claims:
        literals = [c.target_period, c.unit, *c.conditions]
        if c.comparison_basis in BASES:
            literals.append(BASES[c.comparison_basis])
        numbers = (
            (c.value,)
            if c.value is not None
            else ((c.value_range.lower, c.value_range.upper) if c.value_range else ())
        )
        if any(not _number_in_span(n, news.body) for n in numbers):
            raise AMError("DRAFT_CLAIM_CONTEXT_MISSING")
        if c.accounting_basis != "not_applicable":
            literals.append(c.accounting_basis)
        if c.statement_type == "company_outlook":
            literals.append("전망")
        if any(value and value not in news.body for value in literals):
            raise AMError("DRAFT_CLAIM_CONTEXT_MISSING")
    url = str(news.record.source_url)
    text = f"{news.body} 출처: {news.record.source_id.upper()} {url}"
    return text, weighted_length(text, (url,))


def validate_am(inputs: AMInputs, *, now):
    reasons, posts = [], []
    cutoff = inputs.cutoff
    snapshot = inputs.snapshot
    if inputs.transport_mode == "live" and (
        snapshot.data_origin != "live_capture"
        or any(
            r.data_origin != "live_capture"
            for run in inputs.collections
            for r in run.records
        )
    ):
        reasons.append("FIXTURE_LIVE_BLOCKED")
    if now.utcoffset() is None or not inputs.window_start < cutoff:
        raise AMError("AM_TIME_INVALID")
    if (
        not inputs.frozen_at <= cutoff <= now
        or inputs.frozen_at.astimezone(KST).date() != inputs.target_date
    ):
        reasons.append("AM_FREEZE_INVALID")
    if snapshot.retrieved_at > inputs.frozen_at or snapshot.as_of > cutoff:
        reasons.append("ETF_AFTER_CUTOFF")
    if snapshot.trade_date != completed_sessions(cutoff, "NYSE")[1]:
        reasons.append("ETF_SESSION_MISMATCH")
    if snapshot.supersedes:
        reasons.append("ETF_REVISION_REVIEW_REQUIRED")
    if not all(
        snapshot.rights.allows(p, now=now)
        for p in ("collection", "storage", "summary_publication")
    ):
        reasons.append("ETF_RIGHTS_UNVERIFIED")
    runs = {r.source_id: r for r in inputs.collections}
    if len(runs) != len(inputs.collections) or set(runs) != {"exa", "bls"}:
        reasons.append("REQUIRED_COLLECTION_MISSING")
    for run in inputs.collections:
        if (
            run.status != "complete"
            or run.finished_at > inputs.frozen_at
            or run.window_start != inputs.window_start
            or run.window_end != cutoff
        ):
            reasons.append("INCOMPLETE_COLLECTION")
    try:
        text = etf_post_text(snapshot)
        posts.append(
            {
                "position": 1,
                "kind": "etf",
                "text": text,
                "weighted_length": weighted_length(text),
                "evidence_ids": [inputs.market_run_id],
                "event_key": None,
                "fact_version": None,
            }
        )
    except AMError as exc:
        reasons.append(str(exc))
    events = []
    for news in inputs.news:
        record = news.record
        run = runs.get(record.source_id)
        matching = (
            [r for r in run.records if r.input_id == record.input_id] if run else []
        )
        if (
            not run
            or record.collection_run_id != run.collection_run_id
            or len(matching) != 1
            or matching[0].content_hash != record.content_hash
            or matching[0].publication != record.publication
            or matching[0].available_at != record.available_at
            or any(
                getattr(matching[0], field) != getattr(record, field)
                for field in (
                    "source_record_id",
                    "source_url",
                    "retrieved_at",
                    "synthetic",
                    "data_origin",
                )
            )
        ):
            reasons.append("INPUT_COLLECTION_VERSION_MISMATCH")
        decision = evaluate_news_input(
            record,
            news.facts,
            now=now,
            cutoff=cutoff,
            window_start=inputs.window_start,
            purpose="summary_publication",
        )
        if decision.disposition != "candidate":
            reasons.extend(decision.reason_codes)
        if not record.rights.allows("storage", now=now):
            reasons.append("STORAGE_NOT_PERMITTED")
        if news.generation_mode == "live" and not record.rights.allows(
            "ai_transfer", now=now
        ):
            reasons.append("AI_TRANSFER_NOT_PERMITTED")
        if (
            not news.related
            or news.importance not in {"critical", "material"}
            or not record.retrieved_at <= news.reviewed_at <= inputs.frozen_at
        ):
            reasons.append("INPUT_REVIEW_REQUIRED")
        events.append(news.facts.event_key)
        try:
            text, length = news_post(news)
            posts.append(
                {
                    "position": len(posts) + 1,
                    "kind": "news",
                    "text": text,
                    "weighted_length": length,
                    "evidence_ids": [record.input_id],
                    "event_key": news.facts.event_key,
                    "fact_version": news.facts.fact_version,
                }
            )
        except AMError as exc:
            reasons.append(str(exc))
    if len(events) != len(set(events)):
        reasons.append("DUPLICATE_EVENT")
    if not 1 <= len(posts) <= 4 or [p["kind"] for p in posts] != ["etf"] + [
        "news"
    ] * len(inputs.news):
        reasons.append("AM_POST_SET_INVALID")
    return list(dict.fromkeys(reasons)), posts


def metadata_record(record):
    content = ContentEvidence.model_validate(
        record.content.model_dump()
        | {
            "text": None,
            "sufficiency": "not_assessed",
            "evidence_spans": (),
            "assessed_by": None,
            "assessed_at": None,
            "reason": None,
        }
    )
    return NewsInput.model_validate(record.model_dump() | {"content": content})


def storable_collection(run):
    return NewsInputCollection.model_validate(
        run.model_dump() | {"records": tuple(metadata_record(r) for r in run.records)}
    )


def _insert_immutable(conn, table, row):
    existing = (
        conn.execute(sa.select(table).where(table.c.id == row["id"])).mappings().first()
    )
    if existing:
        if existing["payload"] != row["payload"] or any(
            existing[k] != v for k, v in row.items() if k != "payload"
        ):
            raise AMError("IMMUTABLE_INPUT_CONFLICT")
    else:
        conn.execute(table.insert().values(**row))


def _store_common_collection(conn, run, now):
    if run.finished_at > now:
        raise AMError("COLLECTION_IN_FUTURE")
    stored = storable_collection(run)
    _insert_immutable(
        conn,
        collection_runs,
        {
            "id": run.collection_run_id,
            "provider": run.source_id,
            "window_start": run.window_start,
            "window_end": run.window_end,
            "finished_at": run.finished_at,
            "status": run.status,
            "payload": stored.model_dump(mode="json"),
        },
    )
    changed = {}
    for record in run.records:
        if not record.supersedes:
            continue
        old = (
            conn.execute(
                sa.select(evidence_bundles).where(
                    evidence_bundles.c.id == record.supersedes
                )
            )
            .mappings()
            .first()
        )
        if not old or old["payload"].get("schema_version") != "common_news_evidence_v1":
            continue
        source = NewsInput.model_validate(old["payload"]["record"])
        if (
            source.source_id == record.source_id
            and source.source_url == record.source_url
            and source.synthetic == record.synthetic
            and (
                source.content_hash != record.content_hash
                or source.publication != record.publication
            )
        ):
            changed[record.supersedes] = record.input_id
    if not changed:
        return
    jobs = (
        conn.execute(
            sa.select(
                publication_jobs,
                content_drafts.c.payload.label("draft_payload"),
                content_drafts.c.version,
            )
            .join(content_drafts, publication_jobs.c.draft_id == content_drafts.c.id)
            .where(publication_jobs.c.status.in_(["validated", "scheduled", "sending"]))
            .with_for_update(of=publication_jobs)
        )
        .mappings()
        .all()
    )
    for job in jobs:
        referenced = {
            e
            for post in job["draft_payload"].get("posts", [])
            for e in post.get("evidence_ids", [])
        }
        if not referenced.intersection(changed):
            continue
        if conn.scalar(
            sa.select(operations_events.c.id).where(
                operations_events.c.kind == "input_invalidated",
                operations_events.c.scope == job["id"],
                operations_events.c.unique_key == run.collection_run_id,
            )
        ):
            continue
        started = job["first_attempt_at"] is not None
        conn.execute(
            publication_jobs.update()
            .where(publication_jobs.c.id == job["id"])
            .values(
                status="sending" if started else "held",
                stop_requested=True,
                reserved_count=job["reserved_count"] if started else 0,
                decision_revision=job["decision_revision"] + 1,
                payload={**job["payload"], "hold_reason": "APPROVED_SOURCE_CHANGED"},
            )
        )
        if not started:
            conn.execute(
                publication_posts.update()
                .where(
                    publication_posts.c.job_id == job["id"],
                    publication_posts.c.state == "reserved",
                )
                .values(state="cancelled", active_claim=False)
            )
            conn.execute(
                usage_ledger.update()
                .where(
                    usage_ledger.c.job_id == job["id"],
                    usage_ledger.c.state == "reserved",
                )
                .values(state="released")
            )
        _insert_immutable(
            conn,
            operations_events,
            {
                "id": f"invalidated:{run.collection_run_id}:{job['id']}",
                "kind": "input_invalidated",
                "scope": job["id"],
                "unique_key": run.collection_run_id,
                "created_at": now,
                "payload": {
                    "actor": "system:collection",
                    "collection_run_id": run.collection_run_id,
                    "job_id": job["id"],
                    "version": job["version"],
                    "changed_inputs": changed,
                    "reason": "APPROVED_SOURCE_CHANGED",
                    "transmission_started": started,
                },
            },
        )


def record_common_collection(engine, run: NewsInputCollection, *, now):
    """수집 메타데이터 저장과 기존 승인 근거 정정 보류. 실제 송신은 하지 않는다."""
    with engine.begin() as conn:
        conn.execute(sa.text("SELECT pg_advisory_xact_lock(718435902)"))
        _store_common_collection(conn, run, now)


def save_am_edition(engine, inputs: AMInputs, *, account_id, now):
    """입력·근거·불변 편성·job을 원자 저장한다. 승인/송신은 별도다."""
    if not account_id.strip():
        raise AMError("ACCOUNT_REQUIRED")
    reasons, posts = validate_am(inputs, now=now)
    if "ETF_SESSION_MISMATCH" in reasons:
        raise AMError("ETF_SESSION_MISMATCH")
    if not inputs.snapshot.rights.allows("storage", now=now):
        raise AMError("ETF_STORAGE_NOT_PERMITTED")
    with engine.begin() as conn:
        conn.execute(sa.text("SELECT pg_advisory_xact_lock(718435902)"))
        jobs = (
            conn.execute(
                sa.select(
                    publication_jobs, content_drafts.c.payload.label("draft_payload")
                )
                .join(
                    content_drafts, content_drafts.c.id == publication_jobs.c.draft_id
                )
                .where(publication_jobs.c.account_id == account_id)
            )
            .mappings()
            .all()
        )
        if any(
            j["target_date"] == inputs.target_date and j["edition"] == "AM"
            for j in jobs
        ):
            raise AMError("EDITION_ALREADY_EXISTS")
        if any(
            j["edition"] == "AM"
            and j["target_date"] < inputs.target_date
            and j["draft_payload"].get("market_trade_date")
            == inputs.snapshot.trade_date.isoformat()
            for j in jobs
        ):
            return None
        market_payload = {
            "schema_version": "etf_market_run_v1",
            "snapshot": inputs.snapshot.model_dump(mode="json"),
        }
        _insert_immutable(
            conn,
            collection_runs,
            {
                "id": inputs.market_run_id,
                "provider": "Yahoo Finance",
                "window_start": inputs.snapshot.prices[0].market_closed_at,
                "window_end": inputs.snapshot.retrieved_at,
                "finished_at": inputs.snapshot.retrieved_at,
                "status": "complete",
                "payload": market_payload,
            },
        )
        _insert_immutable(
            conn,
            evidence_bundles,
            {
                "id": inputs.market_run_id,
                "source_id": "yahoo:SPY_QQQ_DIA",
                "content_version": inputs.snapshot.content_hash,
                "event_key": "etf_snapshot:" + inputs.snapshot.trade_date.isoformat(),
                "published_at": inputs.snapshot.prices[0].market_closed_at,
                "collected_at": inputs.snapshot.retrieved_at,
                "rights_verified": inputs.snapshot.rights.allows(
                    "summary_publication", now=now
                ),
                "payload": market_payload,
            },
        )
        for run in inputs.collections:
            _store_common_collection(conn, run, now)
        refs = []
        for news in inputs.news:
            record = news.record
            permitted = record.rights.allows("storage", now=now)
            stored = record if permitted else metadata_record(record)
            _insert_immutable(
                conn,
                evidence_bundles,
                {
                    "id": record.input_id,
                    "source_id": record.source_id + ":" + record.source_record_id,
                    "content_version": record.content_hash or "unavailable",
                    "event_key": news.facts.event_key,
                    "published_at": record.publication.value,
                    "collected_at": record.available_at or record.retrieved_at,
                    "rights_verified": permitted,
                    "payload": {
                        "schema_version": "common_news_evidence_v1",
                        "record": stored.model_dump(mode="json"),
                        "facts": news.facts.model_dump(mode="json")
                        if permitted
                        else None,
                    },
                },
            )
            _insert_immutable(
                conn,
                operations_events,
                {
                    "id": news.input_review_id,
                    "kind": "input_review",
                    "scope": record.source_id
                    + ":"
                    + record.source_record_id
                    + ":"
                    + (record.content_hash or "unavailable"),
                    "unique_key": news.input_review_id,
                    "created_at": news.reviewed_at,
                    "payload": {
                        "input_id": record.input_id,
                        "content_hash": record.content_hash,
                        "event_key": news.facts.event_key,
                        "fact_version": news.facts.fact_version,
                        "reviewed_by": news.reviewed_by,
                        "reason": news.review_reason,
                        "related": news.related,
                        "importance": news.importance,
                    },
                },
            )
            refs.append(
                {
                    **news.model_dump(mode="json", exclude={"record", "facts"}),
                    "evidence_id": record.input_id,
                    "body": news.body if permitted else "이용 검토 전 근거",
                }
            )
            if not permitted:
                for post in posts:
                    if record.input_id in post["evidence_ids"]:
                        post["text"], post["weighted_length"] = (
                            "이용 검토 전 근거",
                            None,
                        )
        job_id, draft_id = secrets.token_hex(16), secrets.token_hex(16)
        payload = {
            "schema_version": "am_etf_news_payload_v1",
            "assembly_profile": ASSEMBLY_PROFILE,
            "input_meta": inputs.model_dump(
                mode="json", exclude={"snapshot", "collections", "news"}
            ),
            "collection_run_ids": [
                inputs.market_run_id,
                *(r.collection_run_id for r in inputs.collections),
            ],
            "news_refs": refs,
            "source_versions": [
                {
                    "id": inputs.market_run_id,
                    "content_hash": inputs.snapshot.content_hash,
                },
                *(
                    {"id": n.record.input_id, "content_hash": n.record.content_hash}
                    for n in inputs.news
                ),
            ],
            "posts": posts,
            "market_trade_date": inputs.snapshot.trade_date.isoformat(),
            "transport_mode": inputs.transport_mode,
            "frozen_at": inputs.frozen_at.isoformat(),
            "max_cost_krw": str(inputs.max_publish_cost_krw),
            "rights_verified": not any("RIGHTS" in r or "PERMIT" in r for r in reasons),
            "collection_complete": not any("COLLECTION" in r for r in reasons),
            "validation": {
                "profile": VALIDATION_PROFILE,
                "status": "passed" if not reasons else "failed",
                "blocking_reasons": reasons,
            },
        }
        conn.execute(
            content_drafts.insert().values(
                id=draft_id,
                edition_id=job_id,
                version=1,
                content_hash=payload_hash(payload),
                synthetic=inputs.synthetic,
                validation_passed=not reasons,
                payload=payload,
            )
        )
        scheduled = datetime.combine(inputs.target_date, time(8), KST)
        conn.execute(
            publication_jobs.insert().values(
                id=job_id,
                account_id=account_id,
                target_date=inputs.target_date,
                edition="AM",
                draft_id=draft_id,
                status="prepared" if reasons else "validated",
                scheduled_at=scheduled,
                expires_at=scheduled + timedelta(hours=1),
                payload={
                    "assembly_profile": ASSEMBLY_PROFILE,
                    "transport_mode": inputs.transport_mode,
                },
            )
        )
    return job_id


def am_db_validation(conn, payload, target_date, now, synthetic):
    """승인 시 저장된 pass 표시 대신 현재 입력을 재검증한다."""
    try:
        if (
            payload.get("assembly_profile") != ASSEMBLY_PROFILE
            or payload["validation"]["profile"] != VALIDATION_PROFILE
        ):
            raise AMError("UNREGISTERED_PROFILE")
        meta = payload["input_meta"]
        market = (
            conn.execute(
                sa.select(collection_runs).where(
                    collection_runs.c.id == meta["market_run_id"]
                )
            )
            .mappings()
            .one()
        )
        if market["status"] != "complete" or market["provider"] != "Yahoo Finance":
            raise AMError("INCOMPLETE_COLLECTION")
        market_evidence = (
            conn.execute(
                sa.select(evidence_bundles).where(
                    evidence_bundles.c.id == meta["market_run_id"]
                )
            )
            .mappings()
            .one()
        )
        if (
            market_evidence["payload"] != market["payload"]
            or not market_evidence["rights_verified"]
            or market_evidence["content_version"]
            != ETFSnapshot.model_validate(market["payload"]["snapshot"]).content_hash
        ):
            raise AMError("ETF_EVIDENCE_MISMATCH")
        runs = []
        for run_id in payload["collection_run_ids"]:
            if run_id == meta["market_run_id"]:
                continue
            row = (
                conn.execute(
                    sa.select(collection_runs).where(collection_runs.c.id == run_id)
                )
                .mappings()
                .one()
            )
            run = NewsInputCollection.model_validate(row["payload"])
            if (
                row["provider"] != run.source_id
                or row["status"] != run.status
                or row["finished_at"] != run.finished_at
                or row["id"] != run.collection_run_id
                or row["window_start"] != run.window_start
                or row["window_end"] != run.window_end
            ):
                raise AMError("COLLECTION_VERSION_MISMATCH")
            runs.append(run)
        news = []
        for ref in payload["news_refs"]:
            evidence = (
                conn.execute(
                    sa.select(evidence_bundles).where(
                        evidence_bundles.c.id == ref["evidence_id"]
                    )
                )
                .mappings()
                .one()
            )
            data = evidence["payload"]
            record = NewsInput.model_validate(data["record"])
            facts = NewsFacts.model_validate(data["facts"])
            if (
                not evidence["rights_verified"]
                or evidence["source_id"]
                != record.source_id + ":" + record.source_record_id
                or evidence["content_version"] != record.content_hash
                or evidence["event_key"] != facts.event_key
                or evidence["published_at"] != record.publication.value
                or evidence["collected_at"] != record.available_at
            ):
                raise AMError("EVIDENCE_VERSION_MISMATCH")
            news.append(
                NewsDraft.model_validate(
                    {k: v for k, v in ref.items() if k != "evidence_id"}
                    | {"record": record, "facts": facts}
                )
            )
            review = (
                conn.execute(
                    sa.select(operations_events).where(
                        operations_events.c.id == ref["input_review_id"],
                        operations_events.c.kind == "input_review",
                    )
                )
                .mappings()
                .one()
            )
            if (
                review["created_at"] != news[-1].reviewed_at
                or review["payload"].get("content_hash") != record.content_hash
                or review["payload"].get("fact_version") != facts.fact_version
                or review["payload"].get("reviewed_by") != news[-1].reviewed_by
                or review["payload"].get("related") != news[-1].related
                or review["payload"].get("importance") != news[-1].importance
            ):
                raise AMError("INPUT_REVIEW_VERSION_MISMATCH")
        inputs = AMInputs.model_validate(
            meta
            | {
                "snapshot": market["payload"]["snapshot"],
                "collections": runs,
                "news": news,
            }
        )
        reasons, posts = validate_am(inputs, now=now)
        expected_versions = [
            {"id": inputs.market_run_id, "content_hash": inputs.snapshot.content_hash},
            *(
                {"id": n.record.input_id, "content_hash": n.record.content_hash}
                for n in inputs.news
            ),
        ]
        if payload.get("source_versions") != expected_versions:
            reasons.append("EVIDENCE_VERSION_MISMATCH")
        if (
            inputs.target_date != target_date
            or inputs.synthetic != synthetic
            or posts != payload["posts"]
            or meta["max_publish_cost_krw"] != payload["max_cost_krw"]
        ):
            reasons.append("AM_PAYLOAD_MISMATCH")
        return list(dict.fromkeys(reasons))
    except (ValueError, KeyError, TypeError, sa.exc.NoResultFound):
        return ["AM_INPUT_CONTRACT_INVALID"]
