"""T03 실제 PostgreSQL migration·미전달/성공/실패/불명·90일 만료 검증."""

import os
import secrets
from datetime import timedelta
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from test_newsletter_news import NOW, integrated, link, official, summarized

from xfolio.db.newsletter_news import deliveries, items, runs
from xfolio.newsletter_news import NewsError
from xfolio.newsletter_news_store import NewsletterNewsStore


@pytest.fixture
def store():
    url = os.environ.get("XFOLIO_TEST_DATABASE_URL")
    if not url:
        pytest.skip("explicit isolated PostgreSQL required")
    base = NewsletterNewsStore.from_url(url)
    schema = "xf_t03_" + secrets.token_hex(8)
    with base.engine.begin() as conn:
        conn.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    engine = sa.create_engine(
        base.engine.url,
        hide_parameters=True,
        connect_args={"options": f"-csearch_path={schema}"},
    )
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    try:
        with engine.begin() as conn:
            config.attributes["connection"] = conn
            command.upgrade(config, "head")
        yield NewsletterNewsStore(engine), config
    finally:
        engine.dispose()
        with base.engine.begin() as conn:
            conn.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        base.engine.dispose()


def test_migration_upgrade_downgrade_preserves_domestic_and_legacy(store):
    db, config = store
    with db.engine.begin() as conn:
        tables = set(sa.inspect(conn).get_table_names())
        assert {
            "newsletter_news_items",
            "domestic_instruments",
            "publication_jobs",
        } <= tables
        config.attributes["connection"] = conn
        command.downgrade(config, "0003_domestic_market")
        tables = set(sa.inspect(conn).get_table_names())
        assert (
            "newsletter_news_items" not in tables and "domestic_instruments" in tables
        )
        command.upgrade(config, "head")
    from runpy import run_path

    from sqlalchemy.schema import CreateTable

    snapshot = run_path(str(Path(__file__).parents[1] / "migrations/schema_0004.py"))[
        "metadata"
    ]
    for name, table in items.metadata.tables.items():
        assert str(CreateTable(table).compile(dialect=db.engine.dialect)) == str(
            CreateTable(snapshot.tables[name]).compile(dialect=db.engine.dialect)
        )


def test_importance_is_per_run_and_preserves_legacy_item_identity(store):
    db, _ = store
    ranked = integrated(link())
    legacy = ranked.model_copy(
        update={
            "run_id": "legacy-before-importance",
            "selected": tuple(
                i.model_copy(update={"importance": None}) for i in ranked.selected
            ),
        }
    )
    old_ids = db.save_result(legacy, now=NOW)
    new_ids = db.save_result(ranked, now=NOW)
    assert old_ids == new_ids
    with db.engine.connect() as conn:
        saved = conn.execute(sa.select(items)).mappings().one()
        audit = conn.scalar(sa.select(runs.c.payload).where(runs.c.id == ranked.run_id))
    assert "importance" not in saved["payload"]
    assert (
        audit["selection_importance"][0]["importance"]["score"]
        == ranked.selected[0].importance.score
    )


def test_preview_not_sent_confirmed_only_recipient_scope_and_idempotence(store):
    db, _ = store
    item = link()
    result = integrated(item)
    db.save_result(result, now=NOW)
    db.save_result(result, now=NOW + timedelta(days=1))
    assert not db.seen_keys(recipient_scope="self", now=NOW)
    assert db.record_delivery(
        item,
        recipient_scope="self",
        status="confirmed",
        message_id="synthetic-message",
        now=NOW,
    )
    assert not db.record_delivery(
        item,
        recipient_scope="self",
        status="confirmed",
        message_id="synthetic-message",
        now=NOW,
    )
    assert db.seen_keys(recipient_scope="self", now=NOW) == frozenset(item.keys)
    assert not db.seen_keys(recipient_scope="other", now=NOW)
    assert integrated(
        item, seen_keys=db.seen_keys(recipient_scope="self", now=NOW)
    ).normal_zero
    with db.engine.connect() as conn:
        saved = conn.execute(sa.select(items)).mappings().one()
        assert saved["first_stored_at"] == NOW and saved[
            "expires_at"
        ] == NOW + timedelta(days=90)
        assert "facts" not in saved["payload"]
        assert conn.scalar(sa.select(sa.func.count()).select_from(runs)) == 1


@pytest.mark.parametrize("status", ["failed", "unknown"])
def test_failed_unknown_not_sent_and_cannot_relabel_as_confirmed(store, status):
    db, _ = store
    item = link()
    db.save_result(integrated(item), now=NOW)
    db.record_delivery(item, recipient_scope="self", status=status, now=NOW)
    assert not db.seen_keys(recipient_scope="self", now=NOW)
    with pytest.raises(NewsError, match="delivery_result_conflict"):
        db.record_delivery(
            item, recipient_scope="self", status="confirmed", message_id="fake", now=NOW
        )


def test_expiry_exact_boundary_cascades_receipts_and_run(store):
    db, _ = store
    item = link()
    db.save_result(integrated(item), now=NOW)
    db.record_delivery(
        item,
        recipient_scope="self",
        status="confirmed",
        message_id="synthetic",
        now=NOW,
    )
    expiry = NOW + timedelta(days=90)
    assert db.seen_keys(recipient_scope="self", now=expiry - timedelta(microseconds=1))
    assert not db.seen_keys(recipient_scope="self", now=expiry)
    assert db.purge_expired(now=expiry) == 1
    with db.engine.connect() as conn:
        assert conn.scalar(sa.select(sa.func.count()).select_from(deliveries)) == 0
        assert conn.scalar(sa.select(sa.func.count()).select_from(runs)) == 0


def test_official_stores_no_evidence_text_or_spans(store):
    db, _ = store
    item = summarized(official())
    result = integrated(official(), summary=summarized)
    db.save_result(result, now=NOW)
    with db.engine.connect() as conn:
        payload = conn.execute(sa.select(items.c.payload)).scalar_one()
        assert payload["summary_ko"] == item.summary_ko
        assert "facts" not in payload and "evidence_span" not in payload
