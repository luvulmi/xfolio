"""공통 입력의 무통신 시험. 실기사 전문을 fixture로 복사하지 않는다."""

import json
import socket
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from xfolio.news_contracts import digest
from xfolio.news_input import (
    ContentEvidence,
    InputRights,
    NewsInput,
    NewsInputCollection,
    PublicationTime,
    ScopeReport,
)

NOW = datetime(2026, 10, 31, tzinfo=UTC)
TEXT = "  Example reports Q3 revenue of USD 10. Outlook remains conditional.\n"
ASSETS = Path(__file__).parents[1] / "tasks/verification/assets/news"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("external_network_forbidden")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)


def evidence(**updates):
    return ContentEvidence.model_validate(
        {
            "text": TEXT,
            "text_chars": len(TEXT),
            "requested_max_chars": 20000,
            "truncation": "not_detected",
            "sufficiency": "sufficient",
            "reason": "Synthetic body contains the stated context.",
            "assessed_by": "fixture-reviewer",
            "assessed_at": NOW,
            "evidence_spans": ("Q3 revenue of USD 10",),
        }
        | updates
    )


def record(**updates):
    return NewsInput.model_validate(
        {
            "input_id": "input-1",
            "source_id": "exa",
            "source_record_id": "provider-record-1",
            "source_url": "https://example.invalid/story/1",
            "publisher": "Example News",
            "publisher_url": "https://example.invalid",
            "document_type": "article",
            "publication": {
                "raw": "2026-10-30T15:00:00-04:00",
                "value": "2026-10-30T15:00:00-04:00",
                "timezone": "America/New_York",
                "precision": "second",
                "verified": True,
            },
            "retrieved_at": NOW - timedelta(minutes=2),
            "available_at": NOW - timedelta(minutes=1),
            "last_checked_at": NOW,
            "collection_run_id": "run-1",
            "content": evidence(),
            "content_hash": digest(TEXT),
            "source_revision": digest(TEXT),
            "revision_kind": "content_hash",
            "data_origin": "synthetic_fixture",
            "synthetic": True,
        }
        | updates
    )


def report(scope_id="search", **updates):
    return ScopeReport.model_validate(
        {"scope_id": scope_id, "kind": "search", "status": "complete", "requests": 1}
        | updates
    )


def collection(**updates):
    return NewsInputCollection.model_validate(
        {
            "collection_run_id": "run-1",
            "source_id": "exa",
            "adapter_version": "fixture-v1",
            "query_version": "sample-v1",
            "scope": "morning-configured-top-results",
            "window_start": NOW - timedelta(days=1),
            "window_end": NOW,
            "finished_at": NOW,
            "required_scope_ids": ("search", "contents"),
            "reports": (report(), report("contents", kind="contents")),
            "status": "complete",
        }
        | updates
    )


@pytest.mark.parametrize("source_id", ["exa", "bls"])
def test_provider_publisher_and_roundtrip_are_separate(source_id):
    item = record(source_id=source_id)
    assert item.source_id != item.publisher
    assert item.publication.value == datetime(2026, 10, 30, 19, tzinfo=UTC)
    assert item.publication.raw.endswith("-04:00")
    assert item.content.text == TEXT  # 앞뒤 공백도 해시 근거의 일부다.
    assert NewsInput.model_validate_json(item.model_dump_json()) == item
    assert item.rights.summary_publication == "pending_review"


@pytest.mark.parametrize("field", ["source_url", "publisher_url"])
@pytest.mark.parametrize(
    "url",
    ["https://user:pass@example.invalid", "https://example.invalid?api_key=secret"],
)
def test_authenticated_urls_are_rejected(field, url):
    with pytest.raises(ValidationError, match="authenticated_source_url"):
        record(**{field: url})


def test_date_and_unverified_midnight_are_not_precise_publication():
    day = PublicationTime(raw="2026-10-29", precision="date")
    assert not day.reliable and day.value is None
    midnight = PublicationTime(
        raw="2026-10-29T00:00:00.000Z",
        value="2026-10-29T00:00:00Z",
        timezone="UTC",
        precision="unknown",
    )
    assert not midnight.reliable
    assert not record(publication=midnight).publication.reliable
    with pytest.raises(ValidationError, match="date_must_not_become_midnight"):
        PublicationTime(raw="2026-10-29", precision="date", value=midnight.value)
    with pytest.raises(ValidationError, match="verified_publication"):
        PublicationTime(raw="2026-10-29", precision="date", verified=True)


@pytest.mark.parametrize(
    "updates,code",
    [
        ({"retrieved_at": "2026-10-30T23:58:00"}, "timezone_aware"),
        ({"available_at": NOW - timedelta(minutes=3)}, "invalid_capture_times"),
        ({"last_checked_at": NOW - timedelta(minutes=3)}, "invalid_capture_times"),
        ({"available_at": NOW + timedelta(seconds=1)}, "invalid_capture_times"),
        ({"retrieved_at": NOW - timedelta(days=1)}, "capture_before_publication"),
        ({"available_at": None}, "content_hash_or_availability"),
        ({"content_hash": "0" * 64}, "content_hash_or_availability"),
        ({"source_revision": "bad"}, "hash_revision_mismatch"),
        ({"revision_kind": "native", "source_revision": None}, "native_revision"),
        ({"event_key": "event-1"}, "event_version_pair"),
        (
            {"supersedes": "input-1", "change_reason": "correction"},
            "invalid_superseded",
        ),
        ({"supersedes": "old"}, "invalid_superseded"),
        ({"synthetic": False}, "data_origin_mismatch"),
        ({"data_origin": "live_capture"}, "data_origin_mismatch"),
        ({"schema_version": "official_news_input_v1"}, "literal_error"),
        ({"source_id": "Marketaux"}, "literal_error"),
        ({"assembly_profile": "am_official_reviewed_v1"}, "extra_forbidden"),
    ],
)
def test_invalid_common_inputs_cannot_be_promoted(updates, code):
    with pytest.raises(ValidationError, match=code):
        record(**updates)


def test_recheck_preserves_first_capture_and_versions_but_new_body_needs_new_hash():
    item = record(event_key="company:q3", fact_version="fact-v1")
    again = item.rechecked(checked_at=NOW + timedelta(hours=1))
    assert again.retrieved_at == item.retrieved_at
    assert again.available_at == item.available_at
    assert again.content_hash == item.content_hash
    assert again.last_checked_at > item.last_checked_at
    with pytest.raises(ValueError, match="recheck_cannot_rewind"):
        again.rechecked(checked_at=NOW)
    with pytest.raises(ValidationError, match="content_hash_or_availability"):
        record(
            content=evidence(
                text=TEXT.replace("10", "11"), evidence_spans=("Q3 revenue of USD 11",)
            )
        )
    changed = record(
        input_id="input-2",
        content=evidence(
            text=TEXT.replace("10", "11"), evidence_spans=("Q3 revenue of USD 11",)
        ),
        content_hash=digest(TEXT.replace("10", "11")),
        source_revision="revision-2",
        revision_kind="native",
        event_key="company:q3",
        fact_version="fact-v2",
        supersedes="input-1",
        change_reason="Source corrected revenue.",
    )
    assert changed.event_key == item.event_key
    assert changed.content_hash != item.content_hash


@pytest.mark.parametrize(
    "updates,code",
    [
        ({"title_only": True}, "content_not_sufficient"),
        ({"truncation": "detected"}, "content_not_sufficient"),
        ({"truncation": "unknown"}, "content_not_sufficient"),
        ({"requested_max_chars": len(TEXT)}, "content_not_sufficient"),
        ({"text": None}, "evidence_span_missing"),
        ({"evidence_spans": ()}, "content_not_sufficient"),
        (
            {"evidence_spans": ("Revenue not actually in the body",)},
            "evidence_span_missing",
        ),
        ({"assessed_by": None}, "content_assessment_required"),
        ({"reason": None}, "content_assessment_required"),
        ({"text_chars": 999}, "text_length_mismatch"),
    ],
)
def test_sufficiency_needs_body_context_and_assessment(updates, code):
    with pytest.raises(ValidationError, match=code):
        evidence(**updates)


def test_length_never_grants_sufficiency_and_metadata_can_record_insufficiency():
    long_body = ContentEvidence(text="x" * 25000, text_chars=25000)
    assert long_body.sufficiency == "not_assessed"
    short = evidence(
        text=None,
        text_chars=2273,
        evidence_spans=(),
        truncation="detected",
        sufficiency="insufficient",
    )
    item = record(
        content=short,
        content_hash=None,
        available_at=None,
        source_revision=None,
        revision_kind="unknown",
    )
    assert item.content.sufficiency == "insufficient"
    assert item.available_at is None


def test_rights_are_per_purpose_and_need_review_without_granting_approval():
    with pytest.raises(ValidationError, match="permission_review_required"):
        InputRights(storage="permitted")
    rights = InputRights(
        collection="permitted",
        storage="permitted",
        ai_transfer="restricted",
        review_id="review-1",
        reviewed_by="operator",
        reviewed_at=NOW,
        policy_reference="fixture-only test decision",
        expires_at=NOW + timedelta(days=1),
    )
    assert record(rights=rights).rights.summary_publication == "pending_review"
    with pytest.raises(ValidationError, match="invalid_permission_expiry"):
        InputRights.model_validate(rights.model_dump() | {"expires_at": NOW})


def test_complete_zero_requires_all_scopes_and_has_unknown_cost_by_default():
    run = collection()
    assert run.normal_zero and run.no_updates
    assert run.response_cost_usd is None
    assert NewsInputCollection.model_validate_json(run.model_dump_json()) == run


def test_partial_keeps_discovered_evidence_and_never_becomes_zero():
    item = record()
    run = collection(
        records=(item,),
        reports=(
            report(input_ids=(item.input_id,)),
            report(
                "contents",
                kind="contents",
                status="failed",
                error_codes=("content_fetch_failed",),
            ),
        ),
        status="partial",
    )
    assert run.records == (item,)
    assert not run.normal_zero and not run.no_updates


def test_insufficient_body_is_retained_in_complete_discovery():
    item = record(content=evidence(sufficiency="insufficient", title_only=True))
    run = collection(
        required_scope_ids=("search",),
        reports=(report(input_ids=(item.input_id,)),),
        records=(item,),
    )
    assert run.status == "complete"
    assert not run.normal_zero
    assert run.records[0].content.sufficiency == "insufficient"


def test_different_input_ids_cannot_duplicate_a_source_version():
    original, duplicate = record(), record(input_id="alias")
    with pytest.raises(ValidationError, match="duplicate_source_version"):
        collection(
            records=(original, duplicate),
            reports=(
                report(input_ids=(original.input_id, duplicate.input_id)),
                report("contents"),
            ),
        )


@pytest.mark.parametrize(
    "reports,status",
    [
        ((report(),), "partial"),
        (
            (
                report(),
                report(
                    "contents",
                    kind="contents",
                    status="failed",
                    error_codes=("content_fetch_failed",),
                ),
            ),
            "partial",
        ),
        ((report(status="partial", error_codes=("result_limit",)),), "partial"),
        ((report(status="failed", error_codes=("transport_error",)),), "failed"),
        ((), "failed"),
    ],
)
def test_empty_partial_failed_or_missing_scope_is_never_normal_zero(reports, status):
    run = collection(reports=reports, status=status)
    assert not run.normal_zero and not run.no_updates
    with pytest.raises(ValidationError, match="collection_status_mismatch"):
        collection(reports=reports, status="complete")


def test_rights_or_content_exclusion_and_old_version_are_not_discovery_zero():
    item = record(is_new_version=False)
    run = collection(
        records=(item,),
        reports=(
            report(input_ids=(item.input_id,)),
            report("contents", kind="contents", input_ids=(item.input_id,)),
        ),
    )
    assert not run.normal_zero and run.no_updates
    assert len(run.records) == 1  # 두 요청의 동일 자료를 한 번만 센다.
    assert item.rights.summary_publication == "pending_review"
    new_run = NewsInputCollection.model_validate(
        run.model_dump()
        | {
            "records": (record(),),
        }
    )
    assert not new_run.no_updates and not new_run.normal_zero


@pytest.mark.parametrize(
    "updates,code",
    [
        ({"required_scope_ids": ()}, "too_short"),
        ({"required_scope_ids": ("search", "search")}, "invalid_required_scopes"),
        ({"reports": (report(), report())}, "invalid_required_scopes"),
        ({"reports": (report("unknown"),)}, "invalid_required_scopes"),
        ({"records": (record(),)}, "collection_input_reference_mismatch"),
        (
            {"reports": (report(input_ids=("missing",)), report("contents"))},
            "collection_input_reference_mismatch",
        ),
        ({"window_end": NOW + timedelta(seconds=1)}, "invalid_collection_window"),
        ({"schema_version": "unregistered"}, "literal_error"),
    ],
)
def test_collection_reference_and_scope_invariants(updates, code):
    with pytest.raises(ValidationError, match=code):
        collection(**updates)


@pytest.mark.parametrize(
    "updates,code",
    [
        ({"requests": 0}, "invalid_complete_scope"),
        ({"error_codes": ("http_error",)}, "invalid_complete_scope"),
        ({"status": "failed"}, "scope_failure_reason_required"),
        ({"input_ids": ("a", "a")}, "duplicate_scope_input"),
        ({"response_cost_usd": "NaN"}, "finite_number"),
        ({"response_cost_usd": "-1"}, "greater_than_equal"),
    ],
)
def test_invalid_request_reports(updates, code):
    with pytest.raises(ValidationError, match=code):
        report(**updates)


def test_record_must_belong_to_run_and_not_be_captured_after_finish():
    for item, code in [
        (record(source_id="bls"), "collection_source_mismatch"),
        (record(collection_run_id="other"), "collection_source_mismatch"),
        (
            record(last_checked_at=NOW + timedelta(seconds=1)),
            "capture_after_collection",
        ),
    ]:
        with pytest.raises(ValidationError, match=code):
            collection(
                records=(item,),
                reports=(report(input_ids=(item.input_id,)), report("contents")),
            )


def test_saved_exa_metadata_intake_retains_cost_precision_and_quality_limits():
    search = json.loads(
        (ASSETS / "2026-10-30_Exa_API_메타데이터.json").read_text(encoding="utf-8")
    )
    contents = json.loads(
        (ASSETS / "2026-10-30_Exa_동일_URL_메타데이터.json").read_text(encoding="utf-8")
    )
    assert search["requests"] == 3 and contents["requests"] == 1
    assert not search["article_text_saved"] and not contents["article_text_saved"]
    reports = []
    limits = []
    for query in search["queries"]:
        params = query["parameters"]
        assert (params["type"], params["category"], params["numResults"]) == (
            "auto",
            "news",
            5,
        )
        assert params["startPublishedDate"] == "2026-10-28T00:00:00Z"
        assert params["endPublishedDate"] == "2026-10-30T08:00:00Z"
        reports.append(
            report(query["case"], response_cost_usd=str(query["cost_dollars"]["total"]))
        )
        for article in query["articles"]:
            body = ContentEvidence(
                text_chars=article["text_chars"],
                requested_max_chars=params["contents"]["text"]["maxCharacters"],
            )
            assert body.sufficiency == "not_assessed" and body.text is None
            limits.append(body.limit_reached)
            # 00:00Z도 원문 대조 없이 확인 시각으로 승격하지 않는다.
            stamp = PublicationTime(
                raw=article["published_at"],
                value=article["published_at"],
                timezone="UTC",
            )
            assert not stamp.reliable
    assert sum(limits) == 4
    assert contents["parameters"]["maxAgeHours"] == -1
    assert [a["text_chars"] for a in contents["articles"]] == [2273, 5706]
    reports.append(
        report(
            "same-url",
            kind="contents",
            response_cost_usd=str(contents["cost_dollars"]["total"]),
        )
    )
    # 비용 인수만 검사하며 17개 실자료의 정확한 최초 확보 시각을 만들어내지 않는다.
    assert sum(r.response_cost_usd for r in reports) == Decimal("0.023")
    cost_run = collection(
        required_scope_ids=("search", "contents"),
        reports=(
            report(response_cost_usd="0.007"),
            report("contents", response_cost_usd="0.002"),
        ),
    )
    assert cost_run.response_cost_usd == Decimal("0.009")
