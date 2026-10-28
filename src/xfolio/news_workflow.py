"""명시적 이용 검토를 통과한 BLS 근거의 생성·기계검사·초안 저장 경계.

실제 조회·모델 client 생성·게시·예약을 수행하지 않는다. 의미/길이 검토 전 초안은
항상 prepared이고 API에서 발행 승인할 수 없다.
"""

import json
import re
import secrets
from datetime import date, datetime
from decimal import ROUND_CEILING, Decimal
from typing import Literal, Protocol
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import sqlalchemy as sa
from pydantic import AwareDatetime, Field

from xfolio.news_contracts import Contract, EvidenceBundle, digest

KST = ZoneInfo("Asia/Seoul")
TEXT_SCOPE = "CPI first PRE narrative; tables excluded"


class WorkflowError(ValueError):
    """본문·응답·비밀을 포함하지 않는 안정 오류 코드."""


class PermissionReview(Contract):
    provider: Literal["BLS"]
    source_id: str = Field(min_length=1)
    source_url: str
    content_version: str
    text_scope: Literal["CPI first PRE narrative; tables excluded"]
    reviewed_by: str = Field(min_length=1)
    policy_reference: str = Field(min_length=1)
    reviewed_at: AwareDatetime
    expires_at: AwareDatetime
    storage: Literal["permitted", "unverified", "denied"] = "unverified"
    ai_transfer: Literal["permitted", "unverified", "denied"] = "unverified"
    summary_publication: Literal["permitted", "unverified", "denied"] = "unverified"
    fixture_only: bool = True


class GenerationLimits(Contract):
    model: Literal["gpt-6-luna"] = "gpt-6-luna"
    max_input_tokens: int = Field(default=4096, ge=256, le=16000)
    max_output_tokens: int = Field(default=600, ge=100, le=1000)
    input_krw_per_million: Decimal = Field(gt=0, allow_inf_nan=False)
    output_krw_per_million: Decimal = Field(gt=0, allow_inf_nan=False)
    price_basis: str = Field(min_length=1)
    prices_valid_until: AwareDatetime

    @property
    def maximum_cost(self):
        return self.cost(self.max_input_tokens, self.max_output_tokens)

    def cost(self, input_tokens, output_tokens):
        return (
            (
                input_tokens * self.input_krw_per_million
                + output_tokens * self.output_krw_per_million
            )
            / Decimal(1000000)
        ).quantize(Decimal("0.0001"), rounding=ROUND_CEILING)


class GeneratedClaim(Contract):
    claim_id: str
    text_ko: str = Field(min_length=1)
    evidence_span: str = Field(min_length=1)


class GeneratedNews(Contract):
    source_id: str
    content_version: str
    claims: tuple[GeneratedClaim, ...]


class GenerationResponse(Contract):
    model: Literal["gpt-6-luna"]
    status: Literal["completed"]
    output: GeneratedNews
    input_tokens: int = Field(ge=0, strict=True)
    output_tokens: int = Field(ge=0, strict=True)


class GenerationClient(Protocol):
    def generate(
        self, *, model, input_json, max_output_tokens, max_input_tokens
    ) -> GenerationResponse: ...


class WorkflowStore(Protocol):
    def reserve(self, request_id, limits, now): ...

    def fail(self, request_id, code, now): ...

    def finish(self, request_id, cost, bundle, review, payload, now): ...


def _permission_gate(bundle, review, now, synthetic):
    source = bundle.source
    address = urlsplit(source.source_url)
    if (
        source.provider != "BLS"
        or source.permission_scope != "bls_public_text"
        or address.scheme != "https"
        or address.hostname != "www.bls.gov"
        or address.path != "/news.release/cpi.htm"
        or address.query
        or address.fragment
        or source.text_scope != TEXT_SCOPE
    ):
        raise WorkflowError("SOURCE_SCOPE_UNVERIFIED")
    if not source.published_at <= source.retrieved_at <= now or (
        source.updated_at is not None and source.updated_at > source.retrieved_at
    ):
        raise WorkflowError("SOURCE_TIME_INVALID")
    if review is None or any(
        getattr(review, field) != getattr(source, field)
        for field in (
            "provider",
            "source_id",
            "source_url",
            "content_version",
            "text_scope",
        )
    ):
        raise WorkflowError("PERMISSION_REVIEW_REQUIRED")
    if (
        not review.reviewed_at <= now < review.expires_at
        or (review.fixture_only and not synthetic)
        or any(
            getattr(review, purpose) != "permitted"
            for purpose in ("storage", "ai_transfer", "summary_publication")
        )
    ):
        raise WorkflowError("PERMISSION_SCOPE_UNVERIFIED")


def _claim_contract(bundle):
    if (
        bundle.event.subject_id != "US:CPI-U"
        or bundle.event.event_type != "cpi_release"
        or len(bundle.event.claims) != 2
        or {claim.comparison_basis for claim in bundle.event.claims}
        != {"previous_month_seasonally_adjusted", "12_months_unadjusted"}
    ):
        raise WorkflowError("UNSUPPORTED_CLAIM")
    required = []
    for index, claim in enumerate(bundle.event.claims):
        if (
            claim.certainty != "confirmed"
            or claim.subject != "US:CPI-U:all_items"
            or claim.unit != "percent"
            or claim.value is None
            or not claim.period
            or claim.period != bundle.event.period_or_transaction
            or not re.fullmatch(r"\d{4}-(?:0[1-9]|1[0-2])", claim.period)
            or claim.conditions
            or claim.action not in {"increased", "decreased"}
            or claim.comparison_basis
            not in {"previous_month_seasonally_adjusted", "12_months_unadjusted"}
        ):
            raise WorkflowError("UNSUPPORTED_CLAIM")
        required.append(
            {
                "claim_id": f"claim-{index}",
                "required_literals": [
                    "미국 CPI-U",
                    claim.period,
                    claim.value + "%",
                    "상승" if claim.action == "increased" else "하락",
                    "전월 대비(계절조정)"
                    if claim.comparison_basis == "previous_month_seasonally_adjusted"
                    else "전년 동월 대비(비계절조정)",
                ],
                "evidence_span": claim.evidence_span,
            }
        )
    if not required:
        raise WorkflowError("CLAIMS_REQUIRED")
    return required


def _check_output(output, bundle, required):
    if (output.source_id, output.content_version) != (
        bundle.source.source_id,
        bundle.source.content_version,
    ):
        raise WorkflowError("OUTPUT_SOURCE_MISMATCH")
    if [claim.claim_id for claim in output.claims] != [x["claim_id"] for x in required]:
        raise WorkflowError("OUTPUT_CLAIMS_MISMATCH")
    for generated, contract in zip(output.claims, required, strict=True):
        if generated.evidence_span != contract["evidence_span"]:
            raise WorkflowError("OUTPUT_EVIDENCE_MISMATCH")
        if not all(
            value in generated.text_ko for value in contract["required_literals"]
        ):
            raise WorkflowError("OUTPUT_FACTS_MISSING")
        expected_numbers = re.findall(
            r"\d+(?:\.\d+)?", " ".join(contract["required_literals"])
        )
        if sorted(re.findall(r"\d+(?:\.\d+)?", generated.text_ko)) != sorted(
            expected_numbers
        ):
            raise WorkflowError("OUTPUT_UNSUPPORTED_NUMBERS")


def generate_and_store(
    bundle: EvidenceBundle,
    review: PermissionReview | None,
    *,
    client: GenerationClient,
    store: WorkflowStore,
    limits: GenerationLimits,
    now: datetime,
    target_date: date,
    synthetic: bool = True,
) -> str:
    """완성된 한 뉴스 초안만 저장. 편성 완주·발행 job은 생성하지 않는다."""
    if now.utcoffset() is None:
        raise WorkflowError("TIMEZONE_REQUIRED")
    bundle = EvidenceBundle.model_validate_json(bundle.model_dump_json())
    if review is not None:
        review = PermissionReview.model_validate_json(review.model_dump_json())
    limits = GenerationLimits.model_validate_json(limits.model_dump_json())
    _permission_gate(bundle, review, now, synthetic)
    required = _claim_contract(bundle)
    if limits.prices_valid_until <= now:
        raise WorkflowError("PRICES_EXPIRED")
    payload = json.dumps(
        {
            "source_id": bundle.source.source_id,
            "content_version": bundle.source.content_version,
            "instruction": "한국어로 확인된 사실만 요약. 필수 표현과 정확한 근거를 보존. 외부 지식/예측/인과/도구 사용 금지.",
            "claims": required,
        },
        ensure_ascii=False,
    )
    # adapter와 같은 지시·출력 schema·요청 overhead를 예약 전에 포함한다.
    from xfolio.news_generation import estimate_input_tokens

    if estimate_input_tokens(payload) > limits.max_input_tokens:
        raise WorkflowError("INPUT_BUDGET_EXCEEDED")
    request_id = secrets.token_hex(16)
    store.reserve(request_id, limits, now)
    try:
        raw = client.generate(
            model=limits.model,
            input_json=payload,
            max_output_tokens=limits.max_output_tokens,
            max_input_tokens=limits.max_input_tokens,
        )
        response = GenerationResponse.model_validate(
            raw.model_dump() if isinstance(raw, GenerationResponse) else raw
        )
    except Exception:  # noqa: BLE001 - 주입한 제공처 예외는 비용 불명 상태로 보존한다.
        store.fail(request_id, "GENERATION_RESULT_UNKNOWN", now)
        raise WorkflowError("GENERATION_RESULT_UNKNOWN") from None
    if (
        response.input_tokens > limits.max_input_tokens
        or response.output_tokens > limits.max_output_tokens
    ):
        store.fail(request_id, "USAGE_EXCEEDS_RESERVED_MAXIMUM", now)
        raise WorkflowError("USAGE_EXCEEDS_RESERVED_MAXIMUM")
    cost = limits.cost(response.input_tokens, response.output_tokens)
    try:
        _check_output(response.output, bundle, required)
    except WorkflowError as exc:
        store.finish(request_id, cost, bundle, review, None, now)
        store.fail(request_id, str(exc), now)
        raise
    text = " ".join(claim.text_ko for claim in response.output.claims)
    source = bundle.source
    draft_payload = {
        "posts": [
            {
                "position": 1,
                "kind": "news",
                "text": text + " 출처: BLS " + source.source_url,
                "evidence_ids": [
                    digest(source.source_id + ":" + source.content_version)
                ],
                "event_key": bundle.event.event_key,
                "fact_version": bundle.event.fact_version,
            }
        ],
        "target_date": target_date.isoformat(),
        "edition": "PM",
        "rights_verified": True,
        "collection_complete": False,
        "validation": {
            "status": "pending",
            "blocking_reasons": [
                "SEMANTIC_REVIEW_REQUIRED",
                "X_WEIGHTED_LENGTH_REQUIRED",
                "EDITION_COLLECTION_REQUIRED",
            ],
        },
        "mechanical_checks": "passed",
        "human_review_required": True,
        "synthetic": synthetic,
        "can_publish": False,
        "source_collected_at": source.retrieved_at.isoformat(),
        "generation": {
            "request_id": request_id,
            "model": limits.model,
            "input_tokens": response.input_tokens,
            "output_tokens": response.output_tokens,
        },
    }
    return store.finish(request_id, cost, bundle, review, draft_payload, now)


class SQLWorkflowStore:
    """기존 8개 테이블만 사용한다. schema 생성·발행 예약/전송은 하지 않는다."""

    def __init__(self, engine):
        if engine.dialect.name != "postgresql":
            raise WorkflowError("POSTGRESQL_REQUIRED")
        self.engine = engine

    def reserve(self, request_id, limits, now):
        from xfolio.db.schema import usage_ledger

        with self.engine.begin() as conn:
            conn.execute(sa.text("SELECT pg_advisory_xact_lock(718435902)"))
            month = now.astimezone(KST).strftime("%Y-%m")
            used = conn.scalar(
                sa.select(
                    sa.func.coalesce(sa.func.sum(usage_ledger.c.amount_krw), 0)
                ).where(
                    usage_ledger.c.month == month,
                    usage_ledger.c.state.in_(["estimated", "reserved", "confirmed"]),
                )
            )
            if used + limits.maximum_cost > Decimal(50000):
                raise WorkflowError("MONTHLY_BUDGET_EXCEEDED")
            conn.execute(
                usage_ledger.insert().values(
                    id=request_id,
                    provider="OpenAI",
                    month=month,
                    state="reserved",
                    amount_krw=limits.maximum_cost,
                    payload={
                        "purpose": "news_generation",
                        "model": limits.model,
                        "price_basis": limits.price_basis,
                        "max_output_tokens": limits.max_output_tokens,
                    },
                )
            )

    def fail(self, request_id, code, now):
        from xfolio.db.schema import operations_events

        with self.engine.begin() as conn:
            conn.execute(
                operations_events.insert().values(
                    id=secrets.token_hex(16),
                    kind="generation_failure",
                    scope=request_id,
                    unique_key=secrets.token_hex(16),
                    created_at=now,
                    payload={"code": code},
                )
            )

    def finish(self, request_id, cost, bundle, review, payload, now):
        from xfolio.db.schema import content_drafts, evidence_bundles, usage_ledger

        with self.engine.begin() as conn:
            reserved = (
                conn.execute(
                    sa.select(usage_ledger)
                    .where(usage_ledger.c.id == request_id)
                    .with_for_update()
                )
                .mappings()
                .one()
            )
            if reserved["state"] != "reserved" or cost > reserved["amount_krw"]:
                raise WorkflowError("RESERVATION_CONFLICT")
            conn.execute(
                usage_ledger.update()
                .where(usage_ledger.c.id == request_id)
                .values(state="confirmed", amount_krw=cost)
            )
            if payload is None:
                return None
            source = bundle.source
            evidence_id = digest(source.source_id + ":" + source.content_version)
            existing = (
                conn.execute(
                    sa.select(evidence_bundles).where(
                        evidence_bundles.c.source_id == source.source_id,
                        evidence_bundles.c.content_version == source.content_version,
                    )
                )
                .mappings()
                .first()
            )
            if existing and (
                existing["id"] != evidence_id
                or not existing["rights_verified"]
                or existing["event_key"] != bundle.event.event_key
            ):
                raise WorkflowError("EVIDENCE_IDENTITY_CONFLICT")
            from sqlalchemy.dialects.postgresql import insert

            conn.execute(
                insert(evidence_bundles)
                .values(
                    id=evidence_id,
                    source_id=source.source_id,
                    content_version=source.content_version,
                    event_key=bundle.event.event_key,
                    published_at=source.published_at,
                    collected_at=source.retrieved_at,
                    rights_verified=True,
                    payload={
                        "source": source.provider,
                        "url": source.source_url,
                        "text_scope": source.text_scope,
                        "permitted_excerpt": "\n\n".join(
                            dict.fromkeys(
                                claim.evidence_span for claim in bundle.event.claims
                            )
                        ),
                        "fact_version": bundle.event.fact_version,
                        "claims": [
                            claim.model_dump(mode="json")
                            for claim in bundle.event.claims
                        ],
                        "permission_review": review.model_dump(mode="json"),
                    },
                )
                .on_conflict_do_nothing(index_elements=["source_id", "content_version"])
            )
            draft_id = request_id
            conn.execute(
                content_drafts.insert().values(
                    id=draft_id,
                    edition_id="unassembled:" + request_id,
                    version=1,
                    content_hash=digest(
                        json.dumps(
                            payload,
                            sort_keys=True,
                            ensure_ascii=False,
                            separators=(",", ":"),
                        )
                    ),
                    synthetic=payload["synthetic"],
                    validation_passed=False,
                    payload=payload,
                )
            )
            return draft_id
