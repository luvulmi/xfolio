"""외부 API 없는 CPI 생성→실제 격리 PG→인증된 관리자 API 승인/철회 시험.

정상 승인 경로의 non-synthetic은 시험 전제다. 실제 모델/Google 성공 증거가 아니다.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from test_news_workflow import NOW, Client, bundle, limits, review
from test_news_workflow import (
    pg_engine as pg_engine,  # noqa: PLC0414 - 격리 PG fixture 재사용
)

from xfolio.api.app import COOKIE, create_app
from xfolio.api.auth import Settings
from xfolio.api.store import PostgresStore
from xfolio.db.schema import (
    collection_runs,
    content_drafts,
    evidence_bundles,
    publication_jobs,
    publication_posts,
)
from xfolio.news_edition import assemble_bls_pm, payload_hash, record_bls_collection
from xfolio.news_workflow import SQLWorkflowStore, WorkflowError, generate_and_store

TARGET = NOW.date()
FREEZE = NOW + timedelta(minutes=40)
APPROVE = NOW + timedelta(minutes=50)


def generated(engine, *, synthetic=False):
    source = bundle()
    record_bls_collection(
        engine,
        source,
        started_at=NOW - timedelta(seconds=1),
        finished_at=NOW + timedelta(seconds=1),
    )
    draft_id = generate_and_store(
        source,
        review(source.source, fixture_only=synthetic),
        client=Client(),
        store=SQLWorkflowStore(engine),
        limits=limits(),
        now=NOW + timedelta(minutes=10),
        target_date=TARGET,
        synthetic=synthetic,
    )
    return draft_id


def assemble(engine, draft_id, **updates):
    args = {
        "collection_run_id": bundle().source.collection_run_id,
        "account_id": "isolated-cpi-test",
        "target_date": TARGET,
        "now": FREEZE,
        "max_publish_cost_krw": "10",
    }
    return assemble_bls_pm(engine, draft_id, **(args | updates))


def api_client(engine, *, mode="reviewed", now=APPROVE):
    store = object.__new__(PostgresStore)
    store.engine = engine
    settings = Settings(
        origin="https://testserver",
        google_client_id="fixture",
        google_client_secret="fixture",
        allowed_emails=("operator@example.invalid",),
        cursor_secret="c" * 32,
        mode=mode,
    )
    store.put_event(
        "session",
        "fixture-session",
        {
            "email": "operator@example.invalid",
            "display_name": "Fixture operator",
            "csrf_token": "fixture-csrf",
            "last_seen": now.isoformat(),
        },
        now,
        now + timedelta(hours=1),
    )
    client = TestClient(
        create_app(settings=settings, store=store, clock=lambda: now),
        base_url=settings.origin,
    )
    client.cookies.set(COOKIE, "fixture-session", path="/api")
    return client


def decision(
    client, job_id, *, action="approve", revision=0, key="fixture-key", version=1
):
    return client.post(
        f"/api/drafts/{job_id}/decision",
        headers={
            "Origin": "https://testserver",
            "X-CSRF-Token": "fixture-csrf",
            "Idempotency-Key": key,
        },
        json={
            "action": action,
            "expected_version": version,
            "expected_decision_revision": revision,
            "reason": "검토 후 보류" if action == "hold" else None,
        },
    )


def test_generated_immutable_draft_reaches_list_detail_approval_and_hold(pg_engine):
    original_id = generated(pg_engine)
    job_id = assemble(pg_engine, original_id)
    with pg_engine.connect() as conn:
        original = (
            conn.execute(
                sa.select(content_drafts).where(content_drafts.c.id == original_id)
            )
            .mappings()
            .one()
        )
        assert original["edition_id"].startswith("unassembled:")
        assert original["validation_passed"] is False
        assert original["content_hash"] == payload_hash(original["payload"])
        assert conn.scalar(sa.select(sa.func.count()).select_from(content_drafts)) == 2
    with api_client(pg_engine) as client:
        rows = client.get("/api/drafts").json()["items"]
        assert rows[0]["id"] == job_id
        detail = client.get(f"/api/drafts/{job_id}").json()
        assert detail["validation"] == {"status": "passed", "blocking_reasons": []}
        assert detail["allowed_actions"] == ["approve", "hold"]
        post = detail["posts"][0]
        assert 0 < post["weighted_length"] <= 280
        assert len(post["evidence"][0]["claims"]) == 2
        assert "발표일(미국 동부)" in post["text"]
        assert decision(client, job_id, version=2).status_code == 409
        approved = decision(client, job_id)
        assert approved.status_code == 200
        assert approved.json()["status"] == "scheduled"
        assert decision(client, job_id).json()["replayed"] is True
        held = decision(client, job_id, action="hold", revision=1, key="hold-key")
        assert held.status_code == 200 and held.json()["status"] == "held"
        assert decision(client, job_id).json()["status"] == "held"
        assert decision(client, job_id, revision=2, key="new-key").status_code == 409
    with pg_engine.connect() as conn:
        rows = conn.execute(sa.select(publication_posts)).mappings().all()
        assert len(rows) == 1 and rows[0]["state"] == "cancelled"
        assert rows[0]["x_id"] is None


@pytest.mark.parametrize("synthetic,mode", [(True, "reviewed"), (False, "dry_run")])
def test_trial_data_and_dry_run_still_cannot_approve(pg_engine, synthetic, mode):
    job_id = assemble(pg_engine, generated(pg_engine, synthetic=synthetic))
    with api_client(pg_engine, mode=mode) as client:
        assert (
            "approve"
            not in client.get(f"/api/drafts/{job_id}").json()["allowed_actions"]
        )
        response = decision(client, job_id)
        assert (
            response.status_code == 409
            and response.json()["error"]["code"] == "MODE_BLOCKED"
        )


@pytest.mark.parametrize(
    "change,reason",
    [
        ("partial", "EDITION_COLLECTION_REQUIRED"),
        ("different_version", "EDITION_COLLECTION_REQUIRED"),
        ("late_freeze", "PM_FREEZE_DEADLINE_PASSED"),
        ("late_release", "SOURCE_TIME_INVALID"),
    ],
)
def test_bad_collection_and_late_sources_remain_visible_but_unapprovable(
    pg_engine, change, reason
):
    draft = generated(pg_engine)
    updates = {}
    with pg_engine.begin() as conn:
        if change == "partial":
            conn.execute(collection_runs.update().values(status="partial"))
        elif change == "different_version":
            payload = dict(conn.scalar(sa.select(collection_runs.c.payload)))
            payload["source_versions"] = []
            conn.execute(collection_runs.update().values(payload=payload))
        elif change == "late_freeze":
            updates["now"] = NOW + timedelta(minutes=46)
        elif change == "late_release":
            conn.execute(
                evidence_bundles.update().values(
                    published_at=NOW + timedelta(minutes=31)
                )
            )
    job_id = assemble(pg_engine, draft, **updates)
    with api_client(pg_engine) as client:
        detail = client.get(f"/api/drafts/{job_id}").json()
        assert detail["status"] == "prepared"
        assert reason in detail["validation"]["blocking_reasons"]
        assert detail["allowed_actions"] == ["hold"]
        assert decision(client, job_id).status_code == 409
        assert (
            decision(client, job_id, action="hold", key="hold-invalid").status_code
            == 200
        )


@pytest.mark.parametrize(
    "change", ["semantic", "length", "permission_expiry", "collection"]
)
def test_approval_rechecks_facts_permission_and_collection_before_reserving(
    pg_engine, change
):
    job_id = assemble(pg_engine, generated(pg_engine))
    with pg_engine.begin() as conn:
        if change in {"semantic", "length"}:
            draft_id = conn.scalar(sa.select(publication_jobs.c.draft_id))
            payload = dict(
                conn.scalar(
                    sa.select(content_drafts.c.payload).where(
                        content_drafts.c.id == draft_id
                    )
                )
            )
            if change == "semantic":
                payload["posts"][0]["text"] += " 원인이 아니다"
            else:
                payload["posts"][0]["weighted_length"] = 0
            # Rehashing a failed body must not turn its stored pass flag into authority.
            conn.execute(
                content_drafts.update()
                .where(content_drafts.c.id == draft_id)
                .values(payload=payload, content_hash=payload_hash(payload))
            )
        elif change == "permission_expiry":
            payload = dict(conn.scalar(sa.select(evidence_bundles.c.payload)))
            payload["permission_review"]["expires_at"] = (
                NOW + timedelta(minutes=45)
            ).isoformat()
            conn.execute(evidence_bundles.update().values(payload=payload))
        else:
            conn.execute(collection_runs.update().values(status="partial"))
    with api_client(pg_engine) as client:
        assert decision(client, job_id).json()["error"]["code"] == "VALIDATION_BLOCKED"
    with pg_engine.connect() as conn:
        assert (
            conn.scalar(sa.select(sa.func.count()).select_from(publication_posts)) == 0
        )


def test_concurrent_assembly_cannot_replace_existing_edition_or_approval(pg_engine):
    draft = generated(pg_engine)

    def attempt(_):
        try:
            return assemble(pg_engine, draft)
        except WorkflowError as exc:
            return str(exc)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, range(2)))
    assert results.count("EDITION_ALREADY_EXISTS") == 1
    with pg_engine.connect() as conn:
        assert (
            conn.scalar(sa.select(sa.func.count()).select_from(publication_jobs)) == 1
        )


def test_missing_publish_cost_never_creates_edition(pg_engine):
    draft = generated(pg_engine)
    with pytest.raises(WorkflowError, match="PUBLISH_COST_REQUIRED"):
        assemble(pg_engine, draft, max_publish_cost_krw=None)
