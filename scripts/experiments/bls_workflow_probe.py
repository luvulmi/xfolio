"""BLS 실자료→모의 생성→격리 PostgreSQL/관리자 조회 시험. 유료 AI 호출 없음."""

import argparse
import json
import os
import secrets
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import httpx
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from xfolio.api.app import COOKIE, create_app
from xfolio.api.auth import Settings
from xfolio.api.store import PostgresStore
from xfolio.bls import RELEASE_URL, fetch_html, parse_release
from xfolio.db.schema import content_drafts, publication_jobs, usage_ledger
from xfolio.news_edition import assemble_bls_pm, record_bls_collection
from xfolio.news_workflow import (
    GenerationLimits,
    PermissionReview,
    SQLWorkflowStore,
    generate_and_store,
)


class SimulatedGenerator:
    """원자료 경로 시험용. 모델 품질·실제 usage 결과로 사용하지 않는다."""

    def generate(self, **request):
        data = json.loads(request["input_json"])
        return {
            "model": "gpt-6-luna",
            "status": "completed",
            "output": {
                "source_id": data["source_id"],
                "content_version": data["content_version"],
                "claims": [
                    {
                        "claim_id": item["claim_id"],
                        "text_ko": " ".join(item["required_literals"]),
                        "evidence_span": item["evidence_span"],
                    }
                    for item in data["claims"]
                ],
            },
            "input_tokens": 500,
            "output_tokens": 100,
        }


def inspect_assembled_api(engine, job_id, now):
    """격리 시험 세션만 주입한다. 실제 Google 로그인 시험을 대신하지 않는다."""
    store = object.__new__(PostgresStore)
    store.engine = engine
    settings = Settings(
        origin="https://testserver",
        google_client_id="fixture",
        google_client_secret="fixture",
        allowed_emails=("probe@example.invalid",),
        cursor_secret=secrets.token_urlsafe(32),
        mode="dry_run",
    )
    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    store.put_event(
        "session",
        token,
        {
            "email": "probe@example.invalid",
            "display_name": "Isolated source probe",
            "csrf_token": csrf,
            "last_seen": now.isoformat(),
        },
        now,
        now + timedelta(hours=1),
    )
    with TestClient(
        create_app(settings=settings, store=store, clock=lambda: now),
        base_url=settings.origin,
    ) as api:
        api.cookies.set(COOKIE, token, path="/api")
        listing = api.get("/api/drafts")
        detail = api.get(f"/api/drafts/{job_id}")
        assert listing.status_code == detail.status_code == 200
        draft = detail.json()
        blocked = api.post(
            f"/api/drafts/{job_id}/decision",
            headers={
                "Origin": settings.origin,
                "X-CSRF-Token": csrf,
                "Idempotency-Key": "probe-block-check",
            },
            json={
                "action": "approve",
                "expected_version": 1,
                "expected_decision_revision": 0,
            },
        )
        assert blocked.status_code == 409
        return {
            "api_listed": listing.json()["items"][0]["id"] == job_id,
            "api_detail_http": detail.status_code,
            "api_session_is_fixture": True,
            "status": draft["status"],
            "validation": draft["validation"],
            "weighted_length": draft["posts"][0]["weighted_length"],
            "post_text": draft["posts"][0]["text"],
            "approval_http": blocked.status_code,
            "approval_block_code": blocked.json()["error"]["code"],
            "mode": "dry_run",
            "x_requests": 0,
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument(
        "--assemble",
        action="store_true",
        help="실제 현재 시각으로 PM 편성 검사·관리자 API 조회·승인 차단까지 확인",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not args.fetch:
        print(
            json.dumps(
                {
                    "mode": "plan",
                    "http_requests": 0,
                    "database_requests": 0,
                    "ai_requests": 0,
                }
            )
        )
        return
    url = os.environ.get("XFOLIO_TEST_DATABASE_URL", "")
    address = urlsplit(url)
    if address.hostname not in {
        "localhost",
        "127.0.0.1",
        "::1",
    } or not address.path.strip("/"):
        parser.exit(2, "명시적인 loopback 시험 DB가 필요합니다.\n")
    started_at = datetime.now(UTC)
    with httpx.Client(timeout=20, follow_redirects=False) as client:
        bundle = parse_release(
            fetch_html(client, RELEASE_URL),
            retrieved_at=datetime.now(UTC),
            run_id="explicit-real-input-probe",
        )
    now = datetime.now(UTC)
    target_date = now.astimezone(ZoneInfo("Asia/Seoul")).date()
    review = PermissionReview(
        **{
            key: getattr(bundle.source, key)
            for key in (
                "provider",
                "source_id",
                "source_url",
                "content_version",
                "text_scope",
            )
        },
        reviewed_by="XFolio official-text scope review",
        policy_reference="https://www.bls.gov/bls/linksite.htm#copyright",
        reviewed_at=now,
        expires_at=now + timedelta(days=1),
        storage="permitted",
        ai_transfer="permitted",
        summary_publication="permitted",
        fixture_only=False,
    )
    base = PostgresStore(url)
    schema = "xf_real_input_" + secrets.token_hex(8)
    with base.engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    engine = sa.create_engine(
        base.engine.url,
        connect_args={"options": f"-csearch_path={schema}"},
        hide_parameters=True,
    )
    try:
        config = Config("alembic.ini")
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
        if args.assemble:
            record_bls_collection(
                engine, bundle, started_at=started_at, finished_at=now
            )
        limits = GenerationLimits(
            max_input_tokens=16000,
            input_krw_per_million=Decimal(200),
            output_krw_per_million=Decimal(1000),
            price_basis="SIMULATED test ledger only, not a billing quote",
            prices_valid_until=now + timedelta(hours=1),
        )
        draft_id = generate_and_store(
            bundle,
            review,
            client=SimulatedGenerator(),
            store=SQLWorkflowStore(engine),
            limits=limits,
            now=now,
            target_date=target_date,
            synthetic=True,
        )
        with engine.connect() as connection:
            draft = (
                connection.execute(
                    sa.select(content_drafts).where(content_drafts.c.id == draft_id)
                )
                .mappings()
                .one()
            )
            assert draft["synthetic"] and not draft["validation_passed"]
            assert (
                connection.scalar(
                    sa.select(sa.func.count()).select_from(publication_jobs)
                )
                == 0
            )
            simulated_cost = connection.scalar(sa.select(usage_ledger.c.amount_krw))
        assembled = None
        if args.assemble:
            job_id = assemble_bls_pm(
                engine,
                draft_id,
                collection_run_id=bundle.source.collection_run_id,
                account_id="isolated-real-source-probe",
                target_date=target_date,
                now=now,
                max_publish_cost_krw="0",
            )
            assembled = inspect_assembled_api(engine, job_id, now)
        result = {
            "observed_at_utc": now.isoformat(),
            "source_url": bundle.source.source_url,
            "source_id": bundle.source.source_id,
            "content_version": bundle.source.content_version,
            "published_at_utc": bundle.source.published_at.isoformat(),
            "period": bundle.event.period_or_transaction,
            "claims": [
                {
                    "value": c.value,
                    "unit": c.unit,
                    "comparison_basis": c.comparison_basis,
                }
                for c in bundle.event.claims
            ],
            "policy_reference": review.policy_reference,
            "permission_review_scope": bundle.source.text_scope,
            "input_is_real": True,
            "generation_is_simulated": True,
            "synthetic": True,
            "http_requests": 1,
            "ai_requests": 0,
            "actual_ai_cost_krw": 0,
            "simulated_ledger_amount_krw": str(simulated_cost),
            "postgresql_roundtrip": True,
            "schema_cleanup": True,
            "validation_passed": False,
            "can_publish": False,
            "publication_jobs": 0,
            "target_date_kst": target_date.isoformat(),
            "assembled": assembled,
        }
        if assembled:
            result["publication_jobs"] = 1
    finally:
        engine.dispose()
        with base.engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        base.engine.dispose()
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
