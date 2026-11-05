"""기존 CPI 파서의 공통 입력 연결과 최신 snapshot·일정 대조."""

import re
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

import httpx

from xfolio.news.contracts import digest
from xfolio.news.evaluation import NewsClaim, NewsFacts
from xfolio.news.input import (
    ContentEvidence,
    InputContract,
    InputRights,
    NewsInput,
    NewsInputCollection,
    PublicationTime,
    ScopeReport,
)
from xfolio.news.providers.bls import (
    RELEASE_URL,
    SCHEDULE_URL,
    BLSError,
    fetch_html,
    parse_release,
    parse_schedule,
)


class CPIInput(InputContract):
    record: NewsInput
    facts: NewsFacts | None
    target_period: str


def parse_cpi_input(
    html: str,
    *,
    retrieved_at: datetime,
    run_id: str,
    rights: InputRights | None = None,
    data_origin: Literal[
        "live_capture", "permitted_fixture", "synthetic_fixture"
    ] = "permitted_fixture",
    previous: NewsInput | None = None,
) -> CPIInput:
    bundle = parse_release(html, retrieved_at=retrieved_at, run_id=run_id)
    source = bundle.source
    input_id = digest(source.source_id + ":" + source.content_version)
    claims = tuple(
        NewsClaim(
            claim_id=f"cpi-{i}",
            subject=c.subject,
            action=c.action,
            metric="CPI-U all items",
            target_period=c.period,
            statement_type="actual",
            accounting_basis="not_applicable",
            value=Decimal(c.value),
            unit=c.unit,
            comparison_basis=c.comparison_basis,
            evidence_span=c.evidence_span,
            evidence_locator="first PRE: opening paragraph",
        )
        for i, c in enumerate(bundle.event.claims)
    )
    facts = (
        NewsFacts(
            input_id=input_id,
            content_hash=source.content_version,
            subject_id="US:CPI-U",
            event_type="economic_indicator",
            identity=bundle.event.period_or_transaction,
            extraction_mode="parser",
            claims=claims,
        )
        if claims
        else None
    )
    raw = re.search(r"embargoed until\s+(.+?\d{4})", source.text)
    item = NewsInput(
        input_id=input_id,
        source_id="bls",
        source_record_id=source.source_id,
        source_url=source.source_url,
        publisher="U.S. Bureau of Labor Statistics",
        publisher_url="https://www.bls.gov",
        document_type="press_release",
        publication=PublicationTime(
            raw=raw[1],
            value=source.published_at,
            timezone="America/New_York",
            precision="minute",
            verified=True,
        ),
        retrieved_at=retrieved_at,
        available_at=retrieved_at,
        last_checked_at=retrieved_at,
        collection_run_id=run_id,
        content=ContentEvidence(
            text=source.text,
            text_chars=len(source.text),
            truncation="not_detected",
            sufficiency="sufficient" if facts else "insufficient",
            reason="supported_cpi_opening" if facts else "unsupported_narrative",
            assessed_by="bls_cpi_parser_v1",
            assessed_at=retrieved_at,
            evidence_spans=tuple(dict.fromkeys(c.evidence_span for c in claims)),
        ),
        content_hash=source.content_version,
        source_revision=source.content_version,
        revision_kind="content_hash",
        event_key=facts.event_key if facts else None,
        fact_version=facts.fact_version if facts else None,
        data_origin=data_origin,
        synthetic=data_origin == "synthetic_fixture",
        rights=rights or InputRights(),
    )
    if previous:
        if previous.source_id != "bls":
            raise BLSError("previous_release_identity_mismatch")
        if previous.synthetic != item.synthetic:
            raise BLSError("previous_data_origin_mismatch")
        updates = (
            {
                "retrieved_at": previous.retrieved_at,
                "available_at": previous.available_at,
                "is_new_version": False,
            }
            if previous.content_hash == item.content_hash
            else {
                "supersedes": previous.input_id,
                "change_reason": "cpi_source_content_changed",
            }
        )
        if previous.source_record_id == item.source_record_id or (
            previous.event_key is not None and previous.event_key == item.event_key
        ):
            item = NewsInput.model_validate(item.model_dump() | updates)
    return CPIInput(
        record=item, facts=facts, target_period=bundle.event.period_or_transaction
    )


def collect_cpi_input(
    *,
    client: httpx.Client,
    run_id: str,
    rights: InputRights,
    window_start: datetime,
    window_end: datetime,
    clock=lambda: datetime.now(UTC),
    previous: NewsInput | None = None,
    synthetic: bool = False,
) -> tuple[NewsInputCollection, CPIInput | None]:
    """최신 snapshot만 대조한다. 과거 조회창 전체 수집이나 커서 전진이 아니다."""
    now = clock()
    if (
        any(t.utcoffset() is None for t in (now, window_start, window_end))
        or not window_start < window_end <= now
    ):
        raise BLSError("invalid_collection_window")
    if not rights.allows("collection", now=now):
        raise BLSError("collection_not_permitted")
    reports, schedule, parsed = [], None, None
    for scope_id, url in (("schedule", SCHEDULE_URL), ("latest_release", RELEASE_URL)):
        try:
            html = fetch_html(client, url)
            if scope_id == "schedule":
                schedule = parse_schedule(html)
                ids = ()
            else:
                parsed = parse_cpi_input(
                    html,
                    retrieved_at=clock(),
                    run_id=run_id,
                    rights=rights,
                    data_origin="synthetic_fixture" if synthetic else "live_capture",
                    previous=previous,
                )
                ids = (parsed.record.input_id,)
            reports.append(
                ScopeReport(
                    scope_id=scope_id,
                    kind="release",
                    status="complete",
                    requests=1,
                    input_ids=ids,
                )
            )
        except ValueError as exc:
            code = "invalid_payload"
            if isinstance(exc, BLSError):
                if str(exc) == "transport_error":
                    code = "transport_error"
                elif str(exc) == "http_429":
                    code = "rate_limit"
                elif str(exc).startswith("http_"):
                    code = "http_error"
            reports.append(
                ScopeReport(
                    scope_id=scope_id,
                    kind="release",
                    status="failed",
                    requests=1,
                    error_codes=(code,),
                )
            )
    if (
        parsed
        and schedule
        and any(
            s.scheduled_at <= clock() and s.period > parsed.target_period
            for s in schedule
        )
    ):
        reports[1] = ScopeReport(
            scope_id="latest_release",
            kind="release",
            status="partial",
            requests=1,
            input_ids=(parsed.record.input_id,),
            error_codes=("expected_release_missing",),
        )
    complete = all(r.status == "complete" for r in reports)
    progress = any(r.status != "failed" for r in reports)
    result = NewsInputCollection(
        collection_run_id=run_id,
        source_id="bls",
        adapter_version="bls_cpi_common_v1",
        query_version="latest_snapshot_and_schedule_v1",
        scope="latest_cpi_snapshot_only",
        window_start=window_start,
        window_end=window_end,
        finished_at=clock(),
        required_scope_ids=("schedule", "latest_release"),
        reports=tuple(reports),
        records=(parsed.record,) if parsed else (),
        status="complete" if complete else "partial" if progress else "failed",
    )
    return result, parsed
