from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from xfolio.bls import (
    RELEASE_URL,
    BLSError,
    fetch_html,
    inspect_bls,
    parse_release,
    parse_schedule,
)
from xfolio.cli import main

FIXTURES = Path(__file__).parent / "fixtures" / "bls"
HTML = (FIXTURES / "cpi.html").read_text(encoding="utf-8")
SCHEDULE = (FIXTURES / "schedule.html").read_text(encoding="utf-8")
NOW = datetime(2026, 10, 25, tzinfo=UTC)


def bundle(html=HTML, now=NOW):
    return parse_release(html, retrieved_at=now, run_id="offline")


def test_actual_narrative_preserves_units_period_and_different_bases():
    result = bundle()
    assert result.source.published_at == datetime(2026, 10, 14, 12, 30, tzinfo=UTC)
    assert result.source.updated_at is None
    assert result.event.period_or_transaction == "2026-09"
    assert [(c.value, c.unit, c.comparison_basis) for c in result.event.claims] == [
        ("0.6", "percent", "previous_month_seasonally_adjusted"),
        ("3.7", "percent", "12_months_unadjusted"),
    ]
    assert result.event.eligibility_status == "review_required"
    assert all(c.evidence_span in result.source.text for c in result.event.claims)


def test_schedule_winter_summer_timezone_and_no_fabricated_past_rows():
    rows = parse_schedule(SCHEDULE)
    assert rows[0].period == "2026-10"
    assert rows[0].scheduled_at.hour == 13
    assert rows[5].scheduled_at.hour == 12
    assert not any(r.period == "2026-09" for r in rows)


@pytest.mark.parametrize(
    "old,new,error",
    [
        ("<PRE>", "<div>", "missing_release_body"),
        ("(ET)", "", "missing_release_identity_or_time"),
        ("Wednesday", "Tuesday", "weekday_mismatch"),
    ],
)
def test_structure_or_timestamp_error_holds(old, new, error):
    with pytest.raises(BLSError, match=error):
        bundle(HTML.replace(old, new))


def test_future_embargo_is_not_a_published_release():
    with pytest.raises(BLSError, match="not_released"):
        bundle(now=datetime(2026, 10, 14, 12, 29, tzinfo=UTC))


def test_unsupported_monthly_text_does_not_guess_numeric_claim():
    result = bundle(HTML.replace("increased 0.6 percent", "was unchanged"))
    assert result.event.claims == ()
    assert "unsupported_narrative" in result.event.reason_codes


def test_version_changes_only_for_narrative_and_not_page_navigation():
    original = bundle()
    assert (
        bundle(
            HTML.replace("<body>", "<body><nav>Updated nav</nav>")
        ).source.content_version
        == original.source.content_version
    )
    updated = bundle(HTML.replace("0.6 percent", "0.7 percent"))
    assert updated.event.event_key == original.event.event_key
    assert updated.event.fact_version != original.event.fact_version
    assert updated.source.content_version != original.source.content_version


@pytest.mark.parametrize("status", [403, 429, 500, 302])
def test_http_failure_does_not_parse_or_follow_redirect(status):
    calls = []

    def handler(request):
        calls.append(request)
        assert request.headers["User-Agent"] == "XFolio-Research/1.0"
        return httpx.Response(status, headers={"location": "https://example.com"})

    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as client,
        pytest.raises(BLSError, match=f"http_{status}"),
    ):
        fetch_html(client, RELEASE_URL)
    assert len(calls) == 1


def test_missing_expected_release_holds_without_cursor_advance():
    def handler(request):
        text = SCHEDULE if "/schedule/" in str(request.url) else HTML
        return httpx.Response(200, text=text, headers={"content-type": "text/html"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        _, report = inspect_bls(
            client=client, run_id="offline", now=datetime(2026, 11, 10, 14, tzinfo=UTC)
        )
    assert report["state"] == "expected_release_missing"
    assert report["cursor_advanced"] is False
    assert report["can_publish"] is False


def test_empty_schedule_fails_instead_of_no_scheduled_release():
    with pytest.raises(BLSError, match="missing_or_duplicate_schedule"):
        parse_schedule("<html></html>")


def test_bls_cli_default_is_offline(capsys):
    main(["bls-check"])
    assert '"network_requests": 0' in capsys.readouterr().out
