from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from xfolio.bls import parse_release
from xfolio.cli import main
from xfolio.news_contracts import CollectionRun, EvidenceBundle, EvidenceClaim
from xfolio.news_models import NewsCollection, NewsQueryReport
from xfolio.news_queries import FOCUSED_QUERIES
from xfolio.news_store import NewsStore

NOW = datetime(2026, 10, 25, tzinfo=UTC)
HTML = (Path(__file__).parent / "fixtures/bls/cpi.html").read_text(encoding="utf-8")


def run(**updates):
    values = {
        "run_id": "one",
        "provider": "Marketaux",
        "query_version": "q1",
        "scope": "morning",
        "window_start": NOW - timedelta(days=1),
        "window_end": NOW,
        "finished_at": NOW,
        "required_queries": ("macro", "sector"),
        "completed_queries": ("macro", "sector"),
        "status": "complete",
        "requests": 2,
    }
    return CollectionRun(**(values | updates))


def test_complete_requires_every_required_query_and_no_error():
    with pytest.raises(ValidationError, match="incomplete_required_queries"):
        run(completed_queries=("macro",))
    with pytest.raises(ValidationError):
        run(error="page_budget")


def test_cursor_persists_and_repeat_is_idempotent(tmp_path):
    db = tmp_path / "news.sqlite"
    assert NewsStore(db).finish(run()) == "advanced"
    assert NewsStore(db).cursor("Marketaux", "q1", "morning") == NOW
    assert NewsStore(db).finish(run()) == "advanced"
    assert NewsStore(db).cursor("Marketaux", "q2", "morning") is None


@pytest.mark.parametrize("status", ["partial", "failed"])
def test_unsuccessful_collection_never_advances_existing_cursor(tmp_path, status):
    store = NewsStore(tmp_path / "n.db")
    store.finish(run())
    assert (
        store.finish(
            run(
                run_id="two",
                status=status,
                completed_queries=(),
                cursor_before=NOW,
                window_end=NOW + timedelta(hours=1),
                finished_at=NOW + timedelta(hours=1),
            )
        )
        == "not_complete"
    )
    assert store.cursor("Marketaux", "q1", "morning") == NOW


def test_gap_and_concurrent_stale_writer_are_recorded_without_advancing(tmp_path):
    store = NewsStore(tmp_path / "n.db")
    store.finish(run())
    assert (
        store.finish(
            run(
                run_id="stale",
                window_end=NOW + timedelta(hours=1),
                finished_at=NOW + timedelta(hours=1),
            )
        )
        == "stale_cursor"
    )
    assert (
        store.finish(
            run(
                run_id="gap",
                cursor_before=NOW,
                window_start=NOW + timedelta(minutes=1),
                window_end=NOW + timedelta(hours=1),
                finished_at=NOW + timedelta(hours=1),
            )
        )
        == "gap_requires_recovery"
    )
    assert store.cursor("Marketaux", "q1", "morning") == NOW


def test_overlap_advances_without_rewind_and_run_id_cannot_be_reused(tmp_path):
    store = NewsStore(tmp_path / "n.db")
    store.finish(run())
    assert (
        store.finish(
            run(
                run_id="overlap",
                cursor_before=NOW,
                window_end=NOW + timedelta(hours=1),
                finished_at=NOW + timedelta(hours=1),
            )
        )
        == "advanced"
    )
    with pytest.raises(ValueError, match="run_id_conflict"):
        store.finish(run(requests=3))


def test_long_window_rejected():
    with pytest.raises(ValidationError, match="invalid_time_window"):
        run(window_start=NOW - timedelta(days=8))


def test_evidence_storage_version_and_event_identity(tmp_path):
    store = NewsStore(tmp_path / "n.db")
    original = parse_release(HTML, retrieved_at=NOW, run_id="a")
    assert store.save_evidence(original) == "new_event"
    assert store.save_evidence(original) == "same_source_version"
    updated = parse_release(
        HTML.replace("0.6 percent", "0.7 percent"), retrieved_at=NOW, run_id="b"
    )
    assert store.save_evidence(updated) == "changed_fact_review_required"


def test_source_rights_and_linked_span_cannot_be_bypassed(tmp_path):
    bundle = parse_release(HTML, retrieved_at=NOW, run_id="a")
    raw = bundle.model_dump()
    raw["source"]["permission_scope"] = "unverified"
    with pytest.raises(ValueError, match="evidence_storage_not_permitted"):
        NewsStore(tmp_path / "n.db").save_evidence(EvidenceBundle.model_validate(raw))
    raw = bundle.model_dump()
    raw["event"]["claims"][0]["evidence_span"] = "Headline only number 999"
    with pytest.raises(ValidationError, match="evidence_span_missing"):
        EvidenceBundle.model_validate(raw)


def test_numeric_and_conditional_context_is_required():
    bundle = parse_release(HTML, retrieved_at=NOW, run_id="a")
    raw = bundle.event.claims[0].model_dump()
    with pytest.raises(ValidationError, match="numeric_context_required"):
        EvidenceClaim(**(raw | {"unit": None}))
    with pytest.raises(ValidationError, match="truncated_condition"):
        EvidenceClaim(**(raw | {"certainty": "conditional"}))


def test_unextracted_paragraph_change_requires_review(tmp_path):
    store = NewsStore(tmp_path / "n.db")
    store.save_evidence(parse_release(HTML, retrieved_at=NOW, run_id="a"))
    changed = parse_release(
        HTML.replace("9.1 percent", "9.2 percent"), retrieved_at=NOW, run_id="b"
    )
    assert store.save_evidence(changed) == "same_claims_new_source_review_required"


def test_news_cli_saves_complete_query_set_without_article_body(
    tmp_path, monkeypatch, capsys
):
    from xfolio import cli

    collection = NewsCollection(
        status="complete",
        window_start=NOW - timedelta(days=1),
        window_end=NOW,
        collected_at=NOW,
        requests=4,
        query_reports=tuple(
            NewsQueryReport(
                query_id=q.query_id, search=q.search, status="complete", requests=1
            )
            for q in FOCUSED_QUERIES
        ),
    )
    monkeypatch.setattr(cli, "collect_news", lambda **kwargs: collection)
    main(
        [
            "news-check",
            "--start",
            (NOW - timedelta(days=1)).isoformat(),
            "--end",
            NOW.isoformat(),
            "--run",
            "--save-run",
            "--db",
            str(tmp_path / "n.db"),
        ]
    )
    assert '"checkpoint_result": "advanced"' in capsys.readouterr().out
