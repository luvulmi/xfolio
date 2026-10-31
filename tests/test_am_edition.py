from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
import sqlalchemy as sa
from am_fixtures import CHECKS, CUTOFF, NOW, inputs, rights
from am_fixtures import am_store as am_store  # noqa: PLC0414 - 격리 fixture 재사용
from pydantic import ValidationError

from xfolio.am_edition import (
    AMError,
    AMInputs,
    save_am_edition,
    validate_am,
    weighted_length,
)
from xfolio.api.models import DecisionRequest
from xfolio.api.store import ApiError
from xfolio.db.schema import (
    collection_runs,
    content_drafts,
    evidence_bundles,
    operations_events,
    publication_jobs,
    publication_posts,
    usage_ledger,
)
from xfolio.news_input import NewsInputCollection, ScopeReport


def approve(store, job, key="approve", action="approve", revision=0, **updates):
    request = DecisionRequest.model_validate(
        {
            "action": action,
            "expected_version": 1,
            "expected_decision_revision": revision,
            "reason": "unit hold" if action == "hold" else None,
            "review_checks": CHECKS if action == "approve" else None,
        }
        | updates
    )
    return store.decide(job, "operator@example.invalid", key, request, "reviewed", NOW)


@pytest.mark.parametrize("count", [0, 1, 2, 3])
def test_etf_and_zero_to_three_news_make_one_to_four_posts(count):
    data = inputs(count)
    reasons, posts = validate_am(data, now=NOW)
    assert reasons == [] and len(posts) == count + 1
    assert posts[0]["kind"] == "etf" and "USD" in posts[0]["text"]
    assert all(0 < p["weighted_length"] <= 280 for p in posts)
    assert AMInputs.model_validate_json(data.model_dump_json()) == data


def test_four_news_five_posts_are_rejected():
    with pytest.raises(ValidationError):
        inputs(4)


@pytest.mark.parametrize("status", ["partial", "failed"])
def test_incomplete_required_source_is_not_normal_zero(status):
    data = inputs()
    raw = data.collections[0].model_dump() | {
        "status": status,
        "reports": (
            ScopeReport(
                scope_id="required",
                kind="search",
                status=status,
                requests=1,
                error_codes=("transport_error",),
            ),
        ),
    }
    broken = NewsInputCollection.model_validate(raw)
    data = AMInputs.model_validate(
        data.model_dump() | {"collections": (broken, data.collections[1])}
    )
    assert "INCOMPLETE_COLLECTION" in validate_am(data, now=NOW)[0]


@pytest.mark.parametrize(
    "change,reason",
    [
        ("missing", "REQUIRED_COLLECTION_MISSING"),
        ("late", "AM_FREEZE_INVALID"),
        ("duplicate", "DUPLICATE_EVENT"),
        ("rights", "RIGHTS_UNVERIFIED"),
        ("review", "INPUT_REVIEW_REQUIRED"),
        ("source", "INPUT_COLLECTION_VERSION_MISMATCH"),
        ("body", "DRAFT_CLAIM_CONTEXT_MISSING"),
    ],
)
def test_wrong_inputs_block_whole_edition(change, reason):
    data = inputs(2)
    raw = data.model_dump()
    if change == "missing":
        raw["collections"] = raw["collections"][:1]
    if change == "late":
        raw["frozen_at"] = CUTOFF + timedelta(seconds=1)
    if change == "duplicate":
        raw["news"] = (raw["news"][0], raw["news"][0])
    if change == "rights":
        raw["news"][0]["record"]["rights"] = rights(
            summary_publication="pending_review"
        ).model_dump()
    if change == "review":
        raw["news"][0]["related"] = False
    if change == "source":
        raw["news"][0]["record"]["collection_run_id"] = "wrong"
    if change == "body":
        raw["news"][0]["body"] = "수치와 기간을 뺀 문안"
    assert reason in validate_am(AMInputs.model_validate(raw), now=NOW)[0]


def test_unsupported_emoji_extra_url_and_long_body_fail_closed():
    for text in ("한글" * 200, "🙂", "https://untrusted.invalid"):
        with pytest.raises(AMError):
            weighted_length(text)


@pytest.mark.parametrize("count", [0, 3])
def test_real_isolated_db_save_list_approve_idempotency_and_audit(am_store, count):
    job = save_am_edition(
        am_store.engine, inputs(count), account_id="unit-account", now=NOW
    )
    detail = am_store.detail(job, "reviewed")
    assert (
        detail["posts"][0]["kind"] == "etf" and "approve" in detail["allowed_actions"]
    )
    assert len(detail["posts"]) == count + 1 and detail["posts"][0]["evidence"]
    assert approve(am_store, job)["status"] == "scheduled"
    assert approve(am_store, job)["replayed"]
    with am_store.engine.connect() as conn:
        assert conn.scalar(sa.select(publication_jobs.c.reserved_count)) == count + 1
        assert (
            conn.scalar(sa.select(sa.func.count()).select_from(publication_posts))
            == count + 1
        )
        audit = conn.scalar(
            sa.select(operations_events.c.payload).where(
                operations_events.c.kind == "decision"
            )
        )
        assert (
            audit["operator"] == "operator@example.invalid"
            and audit["review_checks"] == CHECKS
        )
        run = conn.scalar(
            sa.select(collection_runs.c.payload).where(
                collection_runs.c.id == "exa-run"
            )
        )
        assert all(r["content"]["text"] is None for r in run["records"])


@pytest.mark.parametrize(
    "change", ["run", "rights", "source", "market", "checks", "synthetic"]
)
def test_approval_rechecks_current_inputs_before_reservation(am_store, change):
    data = inputs(1, synthetic=change == "synthetic")
    job = save_am_edition(am_store.engine, data, account_id="unit-account", now=NOW)
    with am_store.engine.begin() as conn:
        if change == "run":
            conn.execute(
                collection_runs.update()
                .where(collection_runs.c.id == "exa-run")
                .values(status="partial")
            )
        if change in {"rights", "source"}:
            row = (
                conn.execute(
                    sa.select(evidence_bundles).where(
                        evidence_bundles.c.id == "input-0"
                    )
                )
                .mappings()
                .one()
            )
            payload = row["payload"]
            if change == "rights":
                payload["record"]["rights"]["expires_at"] = CUTOFF.isoformat()
            else:
                payload["record"]["content"]["text"] += " Changed."
            conn.execute(
                evidence_bundles.update()
                .where(evidence_bundles.c.id == "input-0")
                .values(payload=payload)
            )
        if change == "market":
            conn.execute(
                evidence_bundles.update()
                .where(evidence_bundles.c.id == "etf-run")
                .values(rights_verified=False)
            )
    with pytest.raises(ApiError):
        approve(am_store, job, review_checks=None if change == "checks" else CHECKS)
    with am_store.engine.connect() as conn:
        assert (
            conn.scalar(sa.select(sa.func.count()).select_from(publication_posts)) == 0
        )
        assert conn.scalar(sa.select(sa.func.count()).select_from(usage_ledger)) == 0


def test_hold_releases_reservation_and_old_approval_replay_is_not_reapproval(am_store):
    job = save_am_edition(
        am_store.engine, inputs(1), account_id="unit-account", now=NOW
    )
    approve(am_store, job)
    assert (
        approve(am_store, job, key="hold", action="hold", revision=1)["status"]
        == "held"
    )
    assert approve(am_store, job)["status"] == "held"
    with pytest.raises(ApiError):
        approve(am_store, job, key="new", revision=2)


def test_two_approvals_reserve_once_and_new_edition_cannot_replace_existing(am_store):
    job = save_am_edition(
        am_store.engine, inputs(3), account_id="unit-account", now=NOW
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: approve(am_store, job), range(2)))
    assert sum(r["replayed"] for r in results) == 1
    with pytest.raises(AMError, match="EDITION_ALREADY_EXISTS"):
        save_am_edition(am_store.engine, inputs(), account_id="unit-account", now=NOW)


def test_same_completed_trade_date_makes_no_new_job_on_next_kst_day(
    am_store, monkeypatch
):
    import am_fixtures

    monkeypatch.setattr(am_fixtures, "CUTOFF", CUTOFF + timedelta(days=2))
    data = inputs()
    save_am_edition(
        am_store.engine,
        data,
        account_id="unit-account",
        now=data.cutoff + timedelta(minutes=5),
    )
    later = AMInputs.model_validate(
        data.model_dump()
        | {
            "target_date": data.target_date + timedelta(days=1),
            "frozen_at": data.cutoff + timedelta(days=1),
        }
    )
    assert (
        save_am_edition(
            am_store.engine,
            later,
            account_id="unit-account",
            now=data.cutoff + timedelta(days=1, minutes=5),
        )
        is None
    )


def test_draft_rows_are_immutable_after_migration(am_store):
    save_am_edition(am_store.engine, inputs(), account_id="unit-account", now=NOW)
    with pytest.raises(sa.exc.DBAPIError), am_store.engine.begin() as conn:
        conn.execute(content_drafts.update().values(version=2))
