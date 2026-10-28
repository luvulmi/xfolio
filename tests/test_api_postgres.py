"""명시적 임시 PostgreSQL에서만 수행하는 상태/저장 계층 시험.

XFOLIO_TEST_DATABASE_URL이 없으면 skip. 합격 전제를 주입한 계층 시험이며 실뉴스 E2E가 아니다.
각 시험은 무작위 별도 schema를 만들고 마지막에 그 schema만 제거한다.
"""

import hashlib
import json
import os
import secrets
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from xfolio.api.models import DecisionRequest
from xfolio.api.store import ApiError, PostgresStore
from xfolio.db.schema import (
    content_drafts,
    evidence_bundles,
    operations_events,
    publication_jobs,
    publication_posts,
    usage_ledger,
)

NOW = datetime(2026, 10, 28, 8, 50, tzinfo=UTC)


@pytest.fixture
def store():
    url = os.environ.get("XFOLIO_TEST_DATABASE_URL")
    if not url:
        pytest.skip(
            "XFOLIO_TEST_DATABASE_URL explicit isolated PostgreSQL not configured"
        )
    base = PostgresStore(url)
    schema = "xf_test_" + secrets.token_hex(8)
    with base.engine.begin() as conn:
        conn.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    result = PostgresStore(url)
    result.engine.dispose()
    result.engine = sa.create_engine(
        base.engine.url, connect_args={"options": f"-csearch_path={schema}"}
    )
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option(
        "script_location", str(Path(__file__).parents[1] / "migrations")
    )
    with result.engine.begin() as conn:
        config.attributes["connection"] = conn
        command.upgrade(config, "head")
    try:
        yield result
    finally:
        result.engine.dispose()
        with base.engine.begin() as conn:
            conn.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        base.engine.dispose()


def seed(store, *, synthetic=False, cost=100, posts=None, status="validated"):
    posts = posts or [
        {
            "position": 1,
            "kind": "news",
            "text": "layer-only test",
            "evidence_ids": ["e1"],
            "event_key": "event-1",
            "fact_version": "v1",
        }
    ]
    payload = {
        "posts": posts,
        "rights_verified": True,
        "collection_complete": True,
        "max_cost_krw": cost,
        "frozen_at": "2026-10-28T08:45:00+00:00",
        "validation": {"status": "passed", "blocking_reasons": []},
    }
    digest = hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode()
    ).hexdigest()
    with store.engine.begin() as conn:
        conn.execute(
            evidence_bundles.insert().values(
                id="e1",
                source_id="layer-source",
                content_version="v1",
                event_key="event-1",
                published_at=datetime(2026, 10, 28, 6, tzinfo=UTC),
                collected_at=datetime(2026, 10, 28, 6, 5, tzinfo=UTC),
                rights_verified=True,
                payload={"layer_only": True},
            )
        )
        conn.execute(
            content_drafts.insert().values(
                id="d1",
                edition_id="j1",
                version=1,
                content_hash=digest,
                synthetic=synthetic,
                validation_passed=True,
                payload=payload,
            )
        )
        conn.execute(
            publication_jobs.insert().values(
                id="j1",
                account_id="layer-only",
                target_date=date(2026, 10, 28),
                edition="PM",
                draft_id="d1",
                status=status,
                scheduled_at=datetime(2026, 10, 28, 9, tzinfo=UTC),
                expires_at=datetime(2026, 10, 28, 9, 10, tzinfo=UTC),
                payload={},
            )
        )


def decide(store, key="k1", action="approve", revision=0, now=NOW, mode="reviewed"):
    return store.decide(
        "j1",
        "test@example.invalid",
        key,
        DecisionRequest(
            action=action,
            expected_version=1,
            expected_decision_revision=revision,
            reason="layer-only" if action == "hold" else None,
        ),
        mode,
        now,
    )


def test_approve_hold_old_approve_replay_is_not_reapproval(store):
    seed(store)
    assert decide(store)["status"] == "scheduled"
    assert decide(store, key="k2", action="hold", revision=1)["status"] == "held"
    replay = decide(store)
    assert replay["replayed"] is True and replay["status"] == "held"
    with pytest.raises(ApiError, match="") as conflict:
        decide(store, key="k3", revision=2)
    assert conflict.value.code == "VALIDATION_BLOCKED"
    with store.engine.connect() as conn:
        assert (
            conn.scalar(
                sa.select(sa.func.count())
                .select_from(operations_events)
                .where(operations_events.c.kind == "decision")
            )
            == 2
        )
        assert (
            conn.scalar(
                sa.select(sa.func.count())
                .select_from(publication_posts)
                .where(publication_posts.c.active_claim.is_(True))
            )
            == 0
        )
        assert conn.scalar(sa.select(usage_ledger.c.state)) == "released"


@pytest.mark.parametrize(
    "change,code",
    [
        ("synthetic", "MODE_BLOCKED"),
        ("nan", "BUDGET_BLOCKED"),
        ("huge", "BUDGET_BLOCKED"),
        ("index_in_pm", "VALIDATION_BLOCKED"),
        ("same_event", "DUPLICATE_EVENT"),
        ("evidence_missing", "VALIDATION_BLOCKED"),
    ],
)
def test_bad_input_cannot_reserve(store, change, code):
    posts = [
        {
            "position": 1,
            "kind": "news",
            "text": "layer-only",
            "event_key": "event-1",
            "fact_version": "v1",
            "evidence_ids": ["missing" if change == "evidence_missing" else "e1"],
        }
    ]
    if change == "index_in_pm":
        posts[0]["kind"] = "index"
    if change == "same_event":
        posts.append({**posts[0], "position": 2, "fact_version": "v2"})
    seed(
        store,
        synthetic=change == "synthetic",
        cost="NaN" if change == "nan" else (50001 if change == "huge" else 100),
        posts=posts,
    )
    with pytest.raises(ApiError) as err:
        decide(store)
    assert err.value.code == code
    with store.engine.connect() as conn:
        assert conn.scalar(sa.select(sa.func.count()).select_from(usage_ledger)) == 0
        assert conn.scalar(sa.select(publication_jobs.c.decision_revision)) == 0


def test_deadline_and_day_are_enforced(store):
    seed(store)
    for now in [
        datetime(2026, 10, 28, 9, 10, tzinfo=UTC),
        datetime(2026, 10, 27, 8, 50, tzinfo=UTC),
    ]:
        with pytest.raises(ApiError) as err:
            decide(store, now=now)
        assert err.value.code == "DEADLINE_PASSED"


def test_concurrent_approvals_have_one_winner(store):
    seed(store)

    def request(key):
        try:
            return decide(store, key=key)["status"]
        except ApiError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = sorted(pool.map(request, ["k1", "k2"]))
    assert results == ["DECISION_CONFLICT", "scheduled"]
    with store.engine.connect() as conn:
        assert (
            conn.scalar(sa.select(sa.func.count()).select_from(publication_posts)) == 1
        )
        assert conn.scalar(sa.select(sa.func.count()).select_from(usage_ledger)) == 1


def test_claim_is_not_released_after_transmission_started(store):
    seed(store)
    decide(store)
    with store.engine.begin() as conn:
        conn.execute(
            publication_jobs.update().values(status="sending", first_attempt_at=NOW)
        )
        conn.execute(publication_posts.update().values(state="unknown"))
    result = decide(store, key="k2", action="hold", revision=1)
    assert result["status"] == "sending"
    with store.engine.connect() as conn:
        assert conn.scalar(sa.select(publication_posts.c.active_claim)) is True
        assert conn.scalar(sa.select(publication_jobs.c.stop_requested)) is True


def test_api_detail_serializes_product_contract(store):
    seed(store, synthetic=True)
    from xfolio.api.models import DraftDetail

    parsed = DraftDetail.model_validate(store.detail("j1", "dry_run"))
    assert parsed.synthetic and "approve" not in parsed.allowed_actions


def test_migration_enforces_content_immutability(store):
    seed(store)
    with pytest.raises(sa.exc.DBAPIError), store.engine.begin() as conn:
        conn.execute(
            content_drafts.update()
            .where(content_drafts.c.id == "d1")
            .values(content_hash="changed")
        )
