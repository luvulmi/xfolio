import json
import os
import secrets
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
import sqlalchemy as sa

from xfolio.bls import parse_release
from xfolio.news_workflow import (
    GenerationLimits,
    PermissionReview,
    SQLWorkflowStore,
    WorkflowError,
    generate_and_store,
)

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 10, 28, 8, tzinfo=UTC)


def bundle():
    return parse_release(
        (FIXTURES / "bls/cpi.html").read_text(encoding="utf-8"),
        retrieved_at=NOW,
        run_id="workflow-unit",
    )


def review(source=None, **updates):
    source = source or bundle().source
    fields = {
        key: getattr(source, key)
        for key in (
            "provider",
            "source_id",
            "source_url",
            "content_version",
            "text_scope",
        )
    }
    return PermissionReview(
        **(
            fields
            | {
                "reviewed_by": "fixture-reviewer",
                "policy_reference": "fixture-only:not-real-permission",
                "reviewed_at": NOW - timedelta(days=1),
                "expires_at": NOW + timedelta(days=1),
                "storage": "permitted",
                "ai_transfer": "permitted",
                "summary_publication": "permitted",
                "fixture_only": True,
            }
            | updates
        )
    )


def limits(**updates):
    return GenerationLimits(
        **(
            {
                "max_input_tokens": 8000,
                "input_krw_per_million": Decimal(200),
                "output_krw_per_million": Decimal(1000),
                "price_basis": "fixture-price-not-current-quote",
                "prices_valid_until": NOW + timedelta(days=1),
            }
            | updates
        )
    )


class MemoryStore:
    def __init__(self):
        self.reservations, self.failures, self.saved = {}, [], []

    def reserve(self, key, caps, now):
        self.reservations[key] = caps.maximum_cost

    def fail(self, key, code, now):
        self.failures.append(code)

    def finish(self, key, cost, source, permission, payload, now):
        self.reservations[key] = cost
        if payload:
            self.saved.append(payload)
            return key


class Client:
    def __init__(self, mutation=None):
        self.calls = []
        self.mutation = mutation or (lambda output: output)

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        request = json.loads(kwargs["input_json"])
        fixture = json.loads(
            (FIXTURES / "news_workflow/output.json").read_text(encoding="utf-8")
        )
        response = {
            "model": "gpt-6-luna",
            "status": "completed",
            "output": {
                "source_id": request["source_id"],
                "content_version": request["content_version"],
                "claims": [
                    {
                        "claim_id": claim["claim_id"],
                        "text_ko": claim["text_ko"],
                        "evidence_span": required["evidence_span"],
                    }
                    for claim, required in zip(
                        fixture["claims"], request["claims"], strict=True
                    )
                ],
            },
            "input_tokens": 400,
            "output_tokens": 100,
        }
        return self.mutation(response)


def run(
    *, source=None, permission="default", client=None, store=None, caps=None, **kwargs
):
    source = source or bundle()
    if permission == "default":
        permission = review(source.source)
    return generate_and_store(
        source,
        permission,
        client=client or Client(),
        store=store or MemoryStore(),
        limits=caps or limits(),
        now=NOW,
        target_date=date(2026, 10, 28),
        **kwargs,
    )


def test_permission_checked_before_client_or_budget_reservation():
    for permission in [
        None,
        review(ai_transfer="unverified"),
        review(storage="denied"),
        review(summary_publication="unverified"),
        review(content_version="different"),
        review(expires_at=NOW),
        review(reviewed_at=NOW + timedelta(seconds=1)),
    ]:
        client, store = Client(), MemoryStore()
        with pytest.raises(WorkflowError, match="PERMISSION"):
            run(permission=permission, client=client, store=store)
        assert client.calls == [] and store.reservations == {}


def test_bls_provider_label_does_not_grant_ai_rights_or_cover_other_scope():
    raw = bundle().model_dump()
    raw["source"]["provider"] = "Marketaux"
    source = type(bundle()).model_validate(raw)
    with pytest.raises(WorkflowError, match="SOURCE_SCOPE_UNVERIFIED"):
        run(source=source, permission=review())
    with pytest.raises(WorkflowError, match="PERMISSION_SCOPE_UNVERIFIED"):
        run(synthetic=False)
    raw = bundle().model_dump()
    raw["source"]["text_scope"] = "photos and tables"
    with pytest.raises(WorkflowError, match="SOURCE_SCOPE_UNVERIFIED"):
        run(source=type(bundle()).model_validate(raw), permission=review())


def test_generation_preserves_facts_but_remains_unassembled_unapproved():
    client, store = Client(), MemoryStore()
    key = run(client=client, store=store)
    assert key
    payload = store.saved[0]
    assert payload["validation"]["status"] == "pending"
    assert payload["can_publish"] is False
    assert payload["collection_complete"] is False
    assert payload["human_review_required"] is True
    assert payload["mechanical_checks"] == "passed"
    assert len(payload["posts"]) == 1
    assert (
        "출처: BLS https://www.bls.gov/news.release/cpi.htm"
        in payload["posts"][0]["text"]
    )
    assert client.calls[0]["max_output_tokens"] == 600
    assert store.reservations[key] == limits().cost(400, 100)


def test_future_source_and_unsupported_event_do_not_reach_generation():
    client, store = Client(), MemoryStore()
    raw = bundle().model_dump()
    raw["source"]["retrieved_at"] = NOW + timedelta(seconds=1)
    with pytest.raises(WorkflowError, match="SOURCE_TIME_INVALID"):
        run(source=type(bundle()).model_validate(raw), client=client, store=store)
    raw = bundle().model_dump()
    raw["event"]["period_or_transaction"] = "other-period"
    with pytest.raises(WorkflowError, match="UNSUPPORTED_CLAIM"):
        run(source=type(bundle()).model_validate(raw), client=client, store=store)
    assert client.calls == [] and store.reservations == {}


@pytest.mark.parametrize(
    "change,code",
    [
        ("source", "OUTPUT_SOURCE_MISMATCH"),
        ("evidence", "OUTPUT_EVIDENCE_MISMATCH"),
        ("number", "OUTPUT_UNSUPPORTED_NUMBERS"),
        ("fact", "OUTPUT_FACTS_MISSING"),
        ("missing_claim", "OUTPUT_CLAIMS_MISMATCH"),
    ],
)
def test_bad_generation_is_charged_but_never_saved_as_draft(change, code):
    def mutation(response):
        output = response["output"]
        if change == "source":
            output["source_id"] = "other-source"
        elif change == "missing_claim":
            output["claims"].pop()
        elif change == "evidence":
            output["claims"][0]["evidence_span"] = "wrong evidence"
        elif change == "number":
            output["claims"][0]["text_ko"] += " 99"
        elif change == "fact":
            output["claims"][0]["text_ko"] = output["claims"][0]["text_ko"].replace(
                "계절조정", ""
            )
        return response

    store = MemoryStore()
    with pytest.raises(WorkflowError, match=code):
        run(client=Client(mutation), store=store)
    assert store.saved == []
    assert list(store.reservations.values()) == [limits().cost(400, 100)]


def test_maximum_input_price_expiry_and_usage_caps_are_checked():
    client, store = Client(), MemoryStore()
    with pytest.raises(WorkflowError, match="INPUT_BUDGET_EXCEEDED"):
        run(client=client, store=store, caps=limits(max_input_tokens=256))
    with pytest.raises(WorkflowError, match="PRICES_EXPIRED"):
        run(client=client, store=store, caps=limits(prices_valid_until=NOW))
    assert client.calls == [] and store.reservations == {}

    def exceed(response):
        response["output_tokens"] = 601
        return response

    with pytest.raises(WorkflowError, match="USAGE_EXCEEDS_RESERVED_MAXIMUM"):
        run(client=Client(exceed), store=store)
    assert store.saved == []
    assert list(store.reservations.values()) == [limits().maximum_cost]


def test_transport_failure_keeps_reservation_without_leaking_error():
    class FailedClient:
        def generate(self, **kwargs):
            raise RuntimeError("secret token and response body")

    store = MemoryStore()
    with pytest.raises(WorkflowError, match="GENERATION_RESULT_UNKNOWN") as exc:
        run(client=FailedClient(), store=store)
    assert "secret" not in str(exc.value)
    assert store.saved == []
    assert list(store.reservations.values()) == [limits().maximum_cost]


@pytest.mark.parametrize(
    "change", ["wrong_model", "incomplete", "boolean_usage", "extra_field"]
)
def test_response_schema_and_completion_required_and_unknown_cost_reserved(change):
    def mutation(response):
        if change == "wrong_model":
            response["model"] = "unpriced-model"
        elif change == "incomplete":
            response["status"] = "incomplete"
        elif change == "boolean_usage":
            response["input_tokens"] = True
        else:
            response["output"]["unexpected"] = "data"
        return response

    store = MemoryStore()
    with pytest.raises(WorkflowError, match="GENERATION_RESULT_UNKNOWN"):
        run(client=Client(mutation), store=store)
    assert store.saved == []
    assert list(store.reservations.values()) == [limits().maximum_cost]


@pytest.fixture
def pg_engine():
    url = os.environ.get("XFOLIO_TEST_DATABASE_URL")
    if not url:
        pytest.skip("explicit isolated PostgreSQL not configured")
    from xfolio.api.store import PostgresStore
    from xfolio.db.schema import metadata

    base = PostgresStore(url).engine
    schema = "xf_workflow_" + secrets.token_hex(8)
    with base.begin() as conn:
        conn.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    engine = sa.create_engine(
        base.url, connect_args={"options": f"-csearch_path={schema}"}
    )
    with engine.begin() as conn:
        metadata.create_all(conn)
    try:
        yield engine
    finally:
        engine.dispose()
        with base.begin() as conn:
            conn.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        base.dispose()


def test_postgresql_roundtrip_is_pending_not_a_publication_job(pg_engine):
    from xfolio.db.schema import (
        content_drafts,
        evidence_bundles,
        publication_jobs,
        usage_ledger,
    )

    store = SQLWorkflowStore(pg_engine)
    key = run(store=store)
    with pg_engine.connect() as conn:
        draft = conn.execute(sa.select(content_drafts)).mappings().one()
        assert draft["id"] == key
        assert draft["synthetic"] is True and draft["validation_passed"] is False
        assert draft["payload"]["validation"]["status"] == "pending"
        assert (
            conn.scalar(sa.select(sa.func.count()).select_from(publication_jobs)) == 0
        )
        assert conn.scalar(sa.select(evidence_bundles.c.rights_verified)) is True
        evidence_payload = conn.scalar(sa.select(evidence_bundles.c.payload))
        assert evidence_payload["source"] == "BLS"
        assert evidence_payload["url"] == bundle().source.source_url
        assert (
            evidence_payload["permitted_excerpt"]
            == bundle().event.claims[0].evidence_span
        )
        assert evidence_payload["fact_version"] == bundle().event.fact_version
        assert "text" not in evidence_payload and "source_url" not in evidence_payload
        assert conn.scalar(sa.select(usage_ledger.c.state)) == "confirmed"


@pytest.mark.parametrize("state", ["estimated", "reserved", "confirmed"])
def test_postgresql_maximum_budget_is_reserved_before_client(pg_engine, state):
    from xfolio.db.schema import usage_ledger

    with pg_engine.begin() as conn:
        conn.execute(
            usage_ledger.insert().values(
                id="fixed",
                provider="AWS",
                month="2026-10",
                state=state,
                amount_krw=Decimal(50000),
                payload={"fixture": True},
            )
        )
    client = Client()
    with pytest.raises(WorkflowError, match="MONTHLY_BUDGET_EXCEEDED"):
        run(store=SQLWorkflowStore(pg_engine), client=client)
    assert client.calls == []
