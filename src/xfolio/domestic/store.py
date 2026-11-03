"""종목·설정 revision·원종가 버전·90일 보존의 트랜잭션 경계."""

import secrets
from datetime import datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert

from xfolio.db.domestic import (
    calendar_days,
    calendar_requests,
    instruments,
    market_runs,
    price_snapshots,
    watchlist,
    watchlist_versions,
)
from xfolio.domestic.calendar import KST
from xfolio.domestic.catalogue import default_instruments, search
from xfolio.domestic.models import (
    DEFAULT_CODES,
    HOLIDAY_PATH,
    PRICE_RETENTION_DAYS,
    Collection,
    DomesticError,
    Instrument,
    utc,
)


class DomesticStore:
    def __init__(self, engine):
        if engine.dialect.name != "postgresql":
            raise DomesticError("postgresql_required")
        self.engine = engine

    @classmethod
    def from_url(cls, url):
        if not url.startswith(("postgresql://", "postgresql+psycopg://")):
            raise DomesticError("postgresql_required")
        return cls(
            sa.create_engine(
                url.replace("postgresql://", "postgresql+psycopg://", 1),
                hide_parameters=True,
                pool_pre_ping=True,
            )
        )

    @staticmethod
    def _catalogue(conn, item):
        existing = conn.scalar(
            sa.select(instruments.c.isin).where(instruments.c.code == item.code)
        )
        if existing is not None and existing != item.isin:
            raise DomesticError("instrument_identity_changed")
        statement = insert(instruments).values(**item.model_dump())
        conn.execute(
            statement.on_conflict_do_update(
                index_elements=[instruments.c.code],
                set_={
                    "name": item.name,
                    "retrieved_at": item.retrieved_at,
                    "master_source": item.master_source,
                },
                where=instruments.c.retrieved_at <= item.retrieved_at,
            )
        )

    def bootstrap(self, now: datetime):
        now = utc(now)
        with self.engine.begin() as conn:
            conn.execute(sa.text("SELECT pg_advisory_xact_lock(718435903)"))
            for item in default_instruments(now):
                self._catalogue(conn, item)
            if conn.scalar(sa.select(watchlist.c.id)) is None:
                conn.execute(
                    watchlist.insert().values(
                        id=1, revision=1, codes=list(DEFAULT_CODES), updated_at=now
                    )
                )

    def import_catalogue(self, items):
        items = tuple(items)
        if len({i.code for i in items}) != len(items):
            raise DomesticError("duplicate_instrument")
        with self.engine.begin() as conn:
            for item in items:
                self._catalogue(conn, Instrument.model_validate(item))

    def verify_instrument(self, code, *, evidence: str):
        if not evidence.startswith("https://") or len(evidence) > 2048:
            raise DomesticError("eligibility_evidence_required")
        with self.engine.begin() as conn:
            changed = conn.execute(
                instruments.update()
                .where(instruments.c.code == code)
                .values(eligible=True, eligibility_basis=evidence)
            )
            if changed.rowcount != 1:
                raise DomesticError("instrument_not_found")

    def search(self, query, *, limit=20):
        with self.engine.connect() as conn:
            rows = conn.execute(sa.select(instruments)).mappings().all()
        return search(
            [Instrument.model_validate(dict(row)) for row in rows], query, limit=limit
        )

    def watchlist(self):
        with self.engine.connect() as conn:
            row = conn.execute(sa.select(watchlist)).mappings().one_or_none()
        if row is None:
            raise DomesticError("watchlist_not_initialized")
        return {"revision": row["revision"], "codes": tuple(row["codes"])}

    def replace_watchlist(self, codes, *, expected_revision: int, now: datetime):
        import re

        codes = tuple(codes)
        if (
            not 1 <= len(codes) <= 10
            or len(set(codes)) != len(codes)
            or any(
                not isinstance(c, str) or not re.fullmatch(r"[0-9]{6}", c)
                for c in codes
            )
        ):
            raise DomesticError("active_limit_or_duplicate")
        with self.engine.begin() as conn:
            row = (
                conn.execute(
                    sa.select(watchlist).where(watchlist.c.id == 1).with_for_update()
                )
                .mappings()
                .one()
            )
            if row["revision"] != expected_revision:
                raise DomesticError("revision_conflict")
            eligible = set(
                conn.scalars(
                    sa.select(instruments.c.code).where(
                        instruments.c.code.in_(codes), instruments.c.eligible.is_(True)
                    )
                )
            )
            if eligible != set(codes):
                raise DomesticError("ineligible_instrument")
            if tuple(row["codes"]) == codes:
                return row["revision"]
            revision = row["revision"] + 1
            conn.execute(
                watchlist.update()
                .where(watchlist.c.id == 1)
                .values(codes=list(codes), revision=revision, updated_at=utc(now))
            )
            return revision

    def save_calendar(self, rows, retrieved_at):
        retrieved_at = utc(retrieved_at)
        observed = retrieved_at.astimezone(KST).date()
        with self.engine.begin() as conn:
            for day, opened in rows.items():
                statement = insert(calendar_days).values(
                    observed_on=observed,
                    trade_date=day,
                    is_open=opened,
                    source="KIS:" + HOLIDAY_PATH,
                    retrieved_at=retrieved_at,
                )
                conn.execute(statement.on_conflict_do_nothing())
            conn.execute(
                calendar_requests.update()
                .where(calendar_requests.c.observed_on == observed)
                .values(status="complete", reason=None)
            )

    def claim_calendar(self, day, now):
        with self.engine.begin() as conn:
            statement = insert(calendar_requests).values(
                observed_on=day, started_at=utc(now), status="started"
            )
            return (
                conn.scalar(
                    statement.on_conflict_do_nothing().returning(
                        calendar_requests.c.observed_on
                    )
                )
                is not None
            )

    def fail_calendar(self, day, reason):
        with self.engine.begin() as conn:
            conn.execute(
                calendar_requests.update()
                .where(calendar_requests.c.observed_on == day)
                .values(status="failed", reason=reason)
            )

    def load_calendar(self, observed_on):
        with self.engine.connect() as conn:
            rows = (
                conn.execute(
                    sa.select(calendar_days).where(
                        calendar_days.c.observed_on == observed_on
                    )
                )
                .mappings()
                .all()
            )
        dates = {row["trade_date"]: row["is_open"] for row in rows}
        if not all(observed_on - timedelta(days=i) in dates for i in range(15)):
            return None
        return dates

    def save_collection(self, result: Collection, *, now: datetime):
        result = Collection.model_validate(result)
        now = utc(now)
        if result.finished_at > now:
            raise DomesticError("future_collection")
        run_id = secrets.token_hex(16)
        snapshots = {}
        with self.engine.begin() as conn:
            version_codes = conn.scalar(
                sa.select(watchlist_versions.c.codes).where(
                    watchlist_versions.c.revision == result.watchlist_revision
                )
            )
            if tuple(version_codes or ()) != result.requested_codes:
                raise DomesticError("watchlist_version_mismatch")
            conn.execute(
                market_runs.insert().values(
                    id=run_id,
                    watchlist_revision=result.watchlist_revision,
                    started_at=result.started_at,
                    finished_at=result.finished_at,
                    status=result.status,
                    errors=result.errors,
                    trade_date=result.quotes[0].latest.trade_date
                    if result.quotes
                    else None,
                )
            )
            # Stable lock order prevents deadlocks between overlapping collections.
            for quote in sorted(result.quotes, key=lambda q: q.code):
                conn.execute(
                    sa.select(instruments.c.code)
                    .where(instruments.c.code == quote.code)
                    .with_for_update()
                ).one()
                last = (
                    conn.execute(
                        sa.select(price_snapshots)
                        .where(
                            price_snapshots.c.code == quote.code,
                            price_snapshots.c.trade_date == quote.latest.trade_date,
                        )
                        .order_by(price_snapshots.c.version.desc())
                        .limit(1)
                    )
                    .mappings()
                    .first()
                )
                if last and quote.retrieved_at < last["retrieved_at"]:
                    raise DomesticError("stale_price_observation")
                if last and last["content_hash"] == quote.content_hash:
                    snapshots[quote.code] = last["id"]
                    continue
                key, version = (
                    secrets.token_hex(16),
                    (last["version"] + 1 if last else 1),
                )
                conn.execute(
                    price_snapshots.insert().values(
                        id=key,
                        code=quote.code,
                        trade_date=quote.latest.trade_date,
                        version=version,
                        content_hash=quote.content_hash,
                        supersedes=last["id"] if last else None,
                        run_id=run_id,
                        close=quote.latest.close,
                        previous_close=quote.previous.close,
                        raw_change_pct=quote.raw_change_pct,
                        change_pct=quote.change_pct if version == 1 else None,
                        price_as_of=quote.latest.price_as_of,
                        scheduled_close=quote.latest.scheduled_close,
                        retrieved_at=quote.retrieved_at,
                        first_stored_at=now,
                        expires_at=now + timedelta(days=PRICE_RETENTION_DAYS),
                        payload=quote.model_dump(mode="json"),
                    )
                )
                snapshots[quote.code] = key
            observations = [
                {
                    "code": q.code,
                    "snapshot_id": snapshots[q.code],
                    "retrieved_at": q.retrieved_at.isoformat(),
                }
                for q in result.quotes
            ]
            conn.execute(
                market_runs.update()
                .where(market_runs.c.id == run_id)
                .values(observations=observations)
            )
        return {
            "run_id": run_id,
            "snapshot_ids": tuple(
                snapshots[c] for c in result.requested_codes if c in snapshots
            ),
            "status": result.status,
        }

    def latest_prices(self, *, now: datetime):
        with self.engine.connect() as conn:
            rows = conn.execute(
                sa.select(price_snapshots)
                .where(price_snapshots.c.expires_at > utc(now))
                .order_by(
                    price_snapshots.c.code,
                    price_snapshots.c.trade_date.desc(),
                    price_snapshots.c.version.desc(),
                )
            ).mappings()
            result = {}
            for row in rows:
                result.setdefault(row["code"], dict(row))
        return result

    def purge_expired_prices(self, *, now: datetime):
        with self.engine.begin() as conn:
            result = conn.execute(
                price_snapshots.delete().where(price_snapshots.c.expires_at <= utc(now))
            )
            return result.rowcount

    def collect(self, client, *, as_of=None):
        frozen = self.watchlist()
        result = client.collect(
            frozen["codes"], as_of=as_of, watchlist_revision=frozen["revision"]
        )
        return result, self.save_collection(result, now=client.clock())
