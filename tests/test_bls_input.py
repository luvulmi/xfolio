"""CPI 공통 입력과 최신 snapshot 대조의 무통신 회귀."""

import socket
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from xfolio.bls import BLSError, parse_release
from xfolio.bls_input import collect_cpi_input, parse_cpi_input
from xfolio.news_input import InputRights

FIXTURES = Path(__file__).parent / "fixtures/bls"
HTML = (FIXTURES / "cpi.html").read_text(encoding="utf-8")
SCHEDULE = (FIXTURES / "schedule.html").read_text(encoding="utf-8")
NOW = datetime(2026, 10, 31, tzinfo=UTC)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("external_network_forbidden")

    monkeypatch.setattr(socket.socket, "connect", blocked)


def parse(html=HTML, **updates):
    return parse_cpi_input(
        html, **({"retrieved_at": NOW, "run_id": "cpi-test"} | updates)
    )


def rights():
    return InputRights(
        collection="permitted",
        review_id="unit-test",
        reviewed_by="tester",
        reviewed_at=NOW - timedelta(days=1),
        policy_reference="fixture-only test",
    )


def collect(handler, **updates):
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        return collect_cpi_input(
            **(
                {
                    "client": client,
                    "run_id": "cpi-test",
                    "rights": rights(),
                    "window_start": NOW - timedelta(days=1),
                    "window_end": NOW,
                    "clock": lambda: NOW,
                    "synthetic": True,
                }
                | updates
            )
        )


def test_common_cpi_preserves_original_publication_context_hash_and_legacy():
    common = parse()
    legacy = parse_release(HTML, retrieved_at=NOW, run_id="cpi-test")
    assert common.record.source_id == "bls"
    assert common.record.source_record_id == legacy.source.source_id
    assert common.record.content_hash == legacy.source.content_version
    assert common.record.publication.value == legacy.source.published_at
    assert common.record.publication.timezone == "America/New_York"
    assert "8:30 a.m. (ET) Wednesday, October 14, 2026" in common.record.publication.raw
    assert common.record.publication.reliable
    assert common.target_period == "2026-09"
    assert [c.comparison_basis for c in common.facts.claims] == [
        c.comparison_basis for c in legacy.event.claims
    ]
    assert common.record.event_key == common.facts.event_key
    assert common.record.fact_version == common.facts.fact_version
    assert common.record.rights.ai_transfer == "pending_review"


def test_unsupported_narrative_preserves_period_and_does_not_guess_claims():
    common = parse(HTML.replace("increased 0.6 percent", "was unchanged"))
    assert common.facts is None and common.target_period == "2026-09"
    assert common.record.content.sufficiency == "insufficient"


def test_same_version_recheck_preserves_initial_times_and_revision_links():
    original = parse()
    again = parse(previous=original.record, retrieved_at=NOW + timedelta(hours=1))
    assert not again.record.is_new_version
    assert again.record.retrieved_at == original.record.retrieved_at
    assert again.record.available_at == original.record.available_at
    assert again.record.last_checked_at > original.record.last_checked_at
    changed = parse(
        HTML.replace("0.6 percent", "0.7 percent"),
        previous=original.record,
        retrieved_at=NOW + timedelta(hours=1),
    )
    assert changed.record.supersedes == original.record.input_id
    assert changed.facts.event_key == original.facts.event_key
    assert changed.facts.fact_version != original.facts.fact_version
    assert changed.record.available_at > original.record.available_at


def test_unextracted_paragraph_correction_is_new_source_same_claims():
    original = parse()
    changed = parse(
        HTML.replace("9.1 percent", "9.2 percent"), previous=original.record
    )
    assert changed.record.supersedes == original.record.input_id
    assert changed.facts.fact_version == original.facts.fact_version
    assert changed.record.content_hash != original.record.content_hash


def test_latest_snapshot_is_complete_but_not_historical_window_zero():
    run, parsed = collect(
        lambda r: httpx.Response(
            200,
            text=SCHEDULE if "/schedule/" in str(r.url) else HTML,
            headers={"content-type": "text/html"},
        )
    )
    assert run.status == "complete" and run.scope == "latest_cpi_snapshot_only"
    assert not run.normal_zero and parsed.record.publication.value < run.window_start


@pytest.mark.parametrize("broken", ["schedule", "latest_release"])
def test_one_failed_request_keeps_other_scope_and_is_partial(broken):
    def handler(request):
        is_schedule = "/schedule/" in str(request.url)
        if is_schedule == (broken == "schedule"):
            return httpx.Response(500)
        return httpx.Response(
            200,
            text=SCHEDULE if is_schedule else HTML,
            headers={"content-type": "text/html"},
        )

    run, parsed = collect(handler)
    assert run.status == "partial" and not run.normal_zero
    assert any(r.error_codes == ("http_error",) for r in run.reports)
    assert (parsed is not None) == (broken == "schedule")


def test_due_but_missing_release_is_partial_even_if_narrative_is_unsupported():
    late = datetime(2026, 11, 10, 14, tzinfo=UTC)
    for html in (HTML, HTML.replace("increased 0.6 percent", "was unchanged")):
        run, parsed = collect(
            lambda r, html=html: httpx.Response(
                200,
                text=SCHEDULE if "/schedule/" in str(r.url) else html,
                headers={"content-type": "text/html"},
            ),
            clock=lambda: late,
        )
        assert parsed and run.status == "partial"
        assert run.reports[1].error_codes == ("expected_release_missing",)


def test_all_failed_or_rights_unverified_is_not_zero_success():
    run, parsed = collect(lambda r: httpx.Response(403))
    assert run.status == "failed" and parsed is None and not run.normal_zero
    with pytest.raises(BLSError, match="collection_not_permitted"):
        collect(lambda r: pytest.fail("must not call"), rights=InputRights())


def test_bls_same_version_is_no_updates_but_keeps_original_release():
    original = parse(data_origin="synthetic_fixture")
    run, parsed = collect(
        lambda r: httpx.Response(
            200,
            text=SCHEDULE if "/schedule/" in str(r.url) else HTML,
            headers={"content-type": "text/html"},
        ),
        previous=original.record,
    )
    assert run.no_updates and not run.normal_zero
    assert parsed.record.available_at == original.record.available_at


def test_wrong_release_time_and_mixed_origin_are_rejected():
    with pytest.raises(ValueError, match="weekday_mismatch"):
        parse(HTML.replace("Wednesday", "Thursday"))
    with pytest.raises(ValueError, match="previous_data_origin_mismatch"):
        parse(previous=parse(data_origin="synthetic_fixture").record)
