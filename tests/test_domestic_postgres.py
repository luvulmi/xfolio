"""무작위 격리 schema에서0003·활성10개·정정/90일 만료를 실제 PG로 검증."""

import os
import secrets
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from threading import Barrier

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from test_domestic_market import NOW, client, collection, quote

from xfolio.db.domestic import (
    instruments,
    market_runs,
    price_snapshots,
    watchlist,
    watchlist_versions,
)
from xfolio.db.schema import content_drafts
from xfolio.domestic.models import DEFAULT_CODES, Collection, DomesticError, Instrument
from xfolio.domestic.store import DomesticStore


@pytest.fixture
def store():
    url = os.environ.get("XFOLIO_TEST_DATABASE_URL")
    if not url:
        pytest.skip("explicit isolated PostgreSQL required")
    base = DomesticStore.from_url(url)
    schema = "xf_domestic_" + secrets.token_hex(8)
    with base.engine.begin() as conn:
        conn.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    engine = sa.create_engine(
        base.engine.url,
        hide_parameters=True,
        connect_args={"options": f"-csearch_path={schema}"},
    )
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    try:
        with engine.begin() as conn:
            config.attributes["connection"] = conn
            command.upgrade(config, "head")
        result = DomesticStore(engine)
        result.bootstrap(NOW)
        yield result, config
    finally:
        engine.dispose()
        with base.engine.begin() as conn:
            conn.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        base.engine.dispose()


def extra_instruments(count=8):
    return [
        Instrument(
            code=f"60000{i}",
            isin=f"KR{60000 + i:010d}",
            name=f"Synthetic ETF {i}",
            retrieved_at=NOW,
        )
        for i in range(count)
    ]


def enable_extras(store):
    items = extra_instruments()
    store.import_catalogue(items)
    for item in items:
        store.verify_instrument(
            item.code,
            evidence="https://example.invalid/synthetic-verified-overseas-etf",
        )
    return [i.code for i in items]


def test_seed_search_revision_and_unverified_activation_rejection(store):
    db, _ = store
    assert db.watchlist() == {"revision": 1, "codes": DEFAULT_CODES}
    db.bootstrap(NOW)
    assert db.watchlist()["revision"] == 1
    item = extra_instruments(1)[0]
    db.import_catalogue([item])
    assert db.search(item.code)[0].code == item.code
    with pytest.raises(DomesticError, match="ineligible"):
        db.replace_watchlist([*DEFAULT_CODES, item.code], expected_revision=1, now=NOW)
    assert db.watchlist()["revision"] == 1
    assert (
        db.replace_watchlist(reversed(DEFAULT_CODES), expected_revision=1, now=NOW) == 2
    )
    assert db.watchlist()["codes"] == tuple(reversed(DEFAULT_CODES))
    with db.engine.connect() as conn:
        assert (
            conn.scalar(sa.select(sa.func.count()).select_from(watchlist_versions)) == 2
        )


def test_bootstrap_does_not_replace_fresh_master_provenance_with_seed_time(store):
    db, _ = store
    item = db.search(DEFAULT_CODES[0])[0]
    fresh = item.model_validate(
        item.model_dump() | {"name": "Synthetic renamed ETF", "retrieved_at": NOW}
    )
    db.import_catalogue([fresh])
    db.bootstrap(NOW + timedelta(days=1))
    result = db.search(DEFAULT_CODES[0])[0]
    assert result.name == fresh.name and result.retrieved_at == NOW


def test_reordered_collection_and_duplicate_observations_keep_exact_lookup_provenance(
    store,
):
    db, _ = store
    codes = tuple(reversed(DEFAULT_CODES))
    db.replace_watchlist(codes, expected_revision=1, now=NOW)
    first = db.save_collection(collection(codes=codes, revision=2), now=NOW)
    later = NOW + timedelta(minutes=2)
    second = db.save_collection(
        collection(codes=codes, revision=2, now=later), now=later
    )
    assert first["snapshot_ids"] == second["snapshot_ids"]
    with db.engine.connect() as conn:
        run = (
            conn.execute(
                sa.select(market_runs).where(market_runs.c.id == second["run_id"])
            )
            .mappings()
            .one()
        )
        assert [o["code"] for o in run["observations"]] == list(codes)
        assert [o["snapshot_id"] for o in run["observations"]] == list(
            second["snapshot_ids"]
        )
        assert all(o["retrieved_at"] == later.isoformat() for o in run["observations"])
        assert all(
            set(o) == {"code", "snapshot_id", "retrieved_at"}
            for o in run["observations"]
        )


def test_concurrent_changes_are_serialized_and_cannot_activate_eleventh(store):
    db, _ = store
    extras = enable_extras(db)
    nine = (*DEFAULT_CODES, *extras[:6])
    assert db.replace_watchlist(nine, expected_revision=1, now=NOW) == 2
    barrier = Barrier(2)

    def add(code):
        barrier.wait(timeout=10)
        try:
            return db.replace_watchlist((*nine, code), expected_revision=2, now=NOW)
        except DomesticError as exc:
            return str(exc)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(add, extras[6:8]))
    assert sorted(map(str, results)) == ["3", "revision_conflict"]
    assert len(db.watchlist()["codes"]) == 10
    with pytest.raises(DomesticError, match="limit"):
        db.replace_watchlist((*DEFAULT_CODES, *extras), expected_revision=3, now=NOW)


@pytest.mark.parametrize(
    "change", ["eleven", "duplicate", "revision", "unverified", "numeric_code"]
)
def test_direct_sql_cannot_bypass_watchlist_invariants(store, change):
    db, _ = store
    extras = enable_extras(db)
    codes, revision = list(DEFAULT_CODES), 2
    if change == "eleven":
        codes += extras
    elif change == "duplicate":
        codes += [codes[0]]
    elif change == "revision":
        revision = 9
    elif change == "numeric_code":
        codes = [int(DEFAULT_CODES[0])]
    else:
        codes += ["999999"]
    with pytest.raises(sa.exc.DBAPIError), db.engine.begin() as conn:
        conn.execute(
            watchlist.update().values(codes=codes, revision=revision, updated_at=NOW)
        )
    assert db.watchlist()["revision"] == 1


def test_duplicate_collection_is_idempotent_for_prices_without_extending_expiry(store):
    db, _ = store
    first = db.save_collection(collection(), now=NOW)
    later = NOW + timedelta(days=1)
    second = db.save_collection(collection(now=later), now=later)
    assert set(first["snapshot_ids"]) == set(second["snapshot_ids"])
    with db.engine.connect() as conn:
        rows = conn.execute(sa.select(price_snapshots)).mappings().all()
        assert len(rows) == 3
        assert all(r["expires_at"] == NOW + timedelta(days=90) for r in rows)
        assert conn.scalar(sa.select(sa.func.count()).select_from(market_runs)) == 2


def test_price_correction_and_reversion_create_immutable_versions(store):
    db, _ = store
    db.save_collection(collection(), now=NOW)
    q = quote()
    newer = NOW + timedelta(minutes=1)
    changed_day = q.latest.model_validate(q.latest.model_dump() | {"close": "25020"})
    changed = q.model_validate(
        q.model_dump()
        | {"latest": changed_day, "retrieved_at": newer, "basis_verified": False}
    )
    db.save_collection(
        collection(
            [changed, quote("379810", newer), quote("458730", newer)], now=newer
        ),
        now=newer,
    )
    reverted_time = newer + timedelta(minutes=1)
    db.save_collection(collection(now=reverted_time), now=reverted_time)
    with db.engine.connect() as conn:
        rows = (
            conn.execute(
                sa.select(price_snapshots)
                .where(price_snapshots.c.code == q.code)
                .order_by(price_snapshots.c.version)
            )
            .mappings()
            .all()
        )
    assert [r["version"] for r in rows] == [1, 2, 3]
    assert (
        rows[1]["supersedes"] == rows[0]["id"]
        and rows[2]["supersedes"] == rows[1]["id"]
    )
    assert rows[2]["change_pct"] is None
    with pytest.raises(sa.exc.DBAPIError), db.engine.begin() as conn:
        conn.execute(
            price_snapshots.update().values(expires_at=NOW + timedelta(days=365))
        )


def test_expiry_is_exactly_ninety_days_and_purge_preserves_price_free_audit(store):
    db, _ = store
    db.save_collection(collection(), now=NOW)
    cutoff = NOW + timedelta(days=90)
    assert len(db.latest_prices(now=cutoff - timedelta(microseconds=1))) == 3
    assert db.latest_prices(now=cutoff) == {}
    assert db.purge_expired_prices(now=cutoff) == 3
    with db.engine.connect() as conn:
        assert conn.scalar(sa.select(sa.func.count()).select_from(price_snapshots)) == 0
        assert (
            conn.scalar(sa.select(sa.func.count()).select_from(watchlist_versions)) == 1
        )
        assert conn.scalar(sa.select(sa.func.count()).select_from(market_runs)) == 1


def test_old_correction_reference_can_expire_without_destroying_newer_version(store):
    db, _ = store
    db.save_collection(collection(), now=NOW)
    newer = NOW + timedelta(days=1)
    q = quote(now=newer)
    changed = q.model_validate(
        q.model_dump()
        | {"basis_verified": False}
        | {
            "latest": q.latest.model_validate(
                q.latest.model_dump() | {"close": "25020"}
            )
        }
    )
    db.save_collection(
        collection(
            [changed, quote("379810", newer), quote("458730", newer)], now=newer
        ),
        now=newer,
    )
    assert db.purge_expired_prices(now=NOW + timedelta(days=90)) == 3
    remaining = db.latest_prices(now=NOW + timedelta(days=90))
    assert set(remaining) == {"360750"} and remaining["360750"]["supersedes"] is None


def test_bad_watchlist_snapshot_rolls_back_entire_run(store):
    db, _ = store
    with pytest.raises(DomesticError, match="version_mismatch"):
        db.save_collection(collection(revision=999), now=NOW)
    with db.engine.connect() as conn:
        assert conn.scalar(sa.select(sa.func.count()).select_from(market_runs)) == 0


def test_calendar_cache_and_collection_connect_without_live_requests(store):
    db, _ = store
    adapter = client(cache=db)
    result, saved = db.collect(adapter)
    assert result.status == saved["status"] == "complete"
    assert (
        db.load_calendar(
            NOW.astimezone(__import__("zoneinfo").ZoneInfo("Asia/Seoul")).date()
        )
        is not None
    )
    assert len(db.latest_prices(now=NOW)) == 3


def test_partial_failure_and_stale_response_do_not_replace_good_prices(store):
    db, _ = store
    partial = Collection(
        started_at=NOW,
        finished_at=NOW,
        requested_codes=DEFAULT_CODES,
        watchlist_revision=1,
        quotes=(quote(),),
        errors={"379810": "timeout", "458730": "rate_limited"},
    )
    assert db.save_collection(partial, now=NOW)["status"] == "partial"
    assert set(db.latest_prices(now=NOW)) == {"360750"}
    older = quote(now=NOW - timedelta(seconds=1))
    with pytest.raises(DomesticError, match="stale"):
        db.save_collection(
            collection([older, quote("379810"), quote("458730")]), now=NOW
        )
    with db.engine.connect() as conn:
        assert conn.scalar(sa.select(sa.func.count()).select_from(market_runs)) == 1


def test_cannot_invalidate_active_catalogue_and_legacy_rows_survive_downgrade(store):
    db, config = store
    with pytest.raises(sa.exc.DBAPIError), db.engine.begin() as conn:
        conn.execute(instruments.delete().where(instruments.c.code == DEFAULT_CODES[0]))
    with db.engine.begin() as conn:
        conn.execute(
            content_drafts.insert().values(
                id="legacy-preserved",
                edition_id="legacy",
                version=1,
                content_hash="unchanged",
                synthetic=True,
                validation_passed=False,
                payload={},
            )
        )
        config.attributes["connection"] = conn
        command.downgrade(config, "0002_am_four_posts")
        assert conn.scalar(sa.select(content_drafts.c.id)) == "legacy-preserved"
        command.upgrade(config, "head")
        assert conn.scalar(sa.select(content_drafts.c.id)) == "legacy-preserved"


def test_calendar_daily_claim_survives_process_restart_and_failed_attempt(store):
    db, _ = store
    from xfolio.domestic.calendar import KST

    day = NOW.astimezone(KST).date()
    assert db.claim_calendar(day, NOW)
    db.fail_calendar(day, "timeout")
    other = DomesticStore(db.engine)
    assert not other.claim_calendar(day, NOW)
    assert other.load_calendar(day) is None


def test_auth_failure_does_not_consume_the_daily_calendar_request(store):
    import httpx

    db, _ = store
    failed = client(
        lambda request: httpx.Response(403, text="test-app-secret-never-output"),
        cache=db,
    )
    assert failed.collect(DEFAULT_CODES).status == "failed"
    # A fresh credential/client instance can recover without a calendar retry.
    recovered = client(cache=db).collect(DEFAULT_CODES)
    assert recovered.status == "complete"


def test_price_hash_ignores_decimal_format_and_expiry_is_utc_duration_across_dst(store):
    db, _ = store
    q = quote()
    equivalent = q.model_validate(
        q.model_dump()
        | {
            "latest": q.latest.model_validate(
                q.latest.model_dump() | {"close": "25010.0000"}
            )
        }
    )
    assert equivalent.content_hash == q.content_hash
    from datetime import UTC, datetime

    stored = datetime(2027, 2, 15, tzinfo=UTC)
    with db.engine.begin() as conn:
        conn.execute(sa.text("SET TIME ZONE 'America/New_York'"))
    db.save_collection(collection(), now=stored)
    assert (
        len(db.latest_prices(now=stored + timedelta(days=90) - timedelta(seconds=1)))
        == 3
    )
    assert db.latest_prices(now=stored + timedelta(days=90)) == {}
