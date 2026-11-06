"""T02/T03 원본 버전을 대조한 불변 아침 편성 저장. 송신/기발송 기록 없음."""

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert

from xfolio.db.domestic import (
    calendar_days,
    instruments,
    market_runs,
    price_snapshots,
    watchlist,
    watchlist_versions,
)
from xfolio.db.newsletter import editions
from xfolio.db.newsletter_news import deliveries, items, runs
from xfolio.domestic.models import CloseQuote
from xfolio.news.collection import aware
from xfolio.news.collection_store import NewsletterNewsStore, item_id
from xfolio.newsletter.edition import (
    MorningEdition,
    MorningInputs,
    NewsletterError,
    SendDecision,
    build_morning,
    check_send,
    fingerprint,
)


class NewsletterStore:
    def __init__(self, engine, *, schedule=None):
        if engine.dialect.name != "postgresql":
            raise NewsletterError("postgresql_required")
        self.engine = engine
        self.schedule = schedule

    @classmethod
    def from_url(cls, url):
        return cls(NewsletterNewsStore.from_url(url).engine)

    def save(self, inputs: MorningInputs, *, now: datetime, title_translations=None):
        inputs = MorningInputs.model_validate_json(inputs.model_dump_json())
        now = aware(now)
        key = fingerprint(
            [inputs.recipient_scope, inputs.target_date.isoformat(), "morning"]
        )
        with self.engine.begin() as conn:
            # 같은 수신자/날짜 슬롯의 경쟁 INSERT를 직렬화한다. outbox 점유는 별도다.
            conn.execute(sa.text("SELECT pg_advisory_xact_lock(718435904)"))
            old = (
                conn.execute(sa.select(editions).where(editions.c.id == key))
                .mappings()
                .one_or_none()
            )
            if old:
                if old["input_hash"] != inputs.input_hash:
                    raise NewsletterError("edition_input_conflict")
                if old["expires_at"] <= now:
                    raise NewsletterError("edition_expired")
                return self._decode(old)
            codes = conn.scalar(
                sa.select(watchlist_versions.c.codes).where(
                    watchlist_versions.c.revision == inputs.watchlist_revision
                )
            )
            if tuple(codes or ()) != inputs.codes:
                raise NewsletterError("watchlist_version_mismatch")
            catalogue = {
                r["code"]: r
                for r in conn.execute(
                    sa.select(instruments).where(instruments.c.code.in_(inputs.codes))
                ).mappings()
            }
            if any(
                i.code not in catalogue
                or catalogue[i.code]["isin"] != i.isin
                or catalogue[i.code]["name"] != i.name
                or not catalogue[i.code]["eligible"]
                for i in inputs.instruments
            ):
                raise NewsletterError("instrument_metadata_mismatch")
            calendar = {
                r["trade_date"]: r["is_open"]
                for r in conn.execute(
                    sa.select(calendar_days).where(
                        calendar_days.c.observed_on == inputs.target_date,
                        calendar_days.c.retrieved_at <= now,
                    )
                ).mappings()
            }
            if inputs.calendar_opened and any(
                calendar.get(day) is not opened
                for day, opened in inputs.calendar_opened.items()
            ):
                raise NewsletterError("calendar_version_mismatch")
            market = (
                conn.execute(
                    sa.select(market_runs).where(
                        market_runs.c.id == inputs.market_run_id
                    )
                )
                .mappings()
                .one_or_none()
            )
            if not market or any(
                market[k] != v
                for k, v in {
                    "watchlist_revision": inputs.market.watchlist_revision,
                    "started_at": inputs.market.started_at,
                    "finished_at": inputs.market.finished_at,
                    "status": inputs.market.status,
                    "errors": inputs.market.errors,
                }.items()
            ):
                raise NewsletterError("market_run_mismatch")
            observations = {o["code"]: o for o in market["observations"]}
            if set(observations) != {q.code for q in inputs.market.quotes}:
                raise NewsletterError("market_observations_mismatch")
            expiries, corrected, snapshot_ids = [], [], []
            for quote in inputs.market.quotes:
                observation = observations[quote.code]
                row = (
                    conn.execute(
                        sa.select(price_snapshots)
                        .where(price_snapshots.c.id == observation["snapshot_id"])
                        .with_for_update()
                    )
                    .mappings()
                    .one_or_none()
                )
                if not row or not row["first_stored_at"] <= now < row["expires_at"]:
                    raise NewsletterError("price_missing_or_expired")
                if (
                    datetime.fromisoformat(observation["retrieved_at"])
                    != quote.retrieved_at
                    or row["content_hash"] != quote.content_hash
                    or CloseQuote.model_validate(row["payload"]).content_hash
                    != quote.content_hash
                ):
                    raise NewsletterError("price_version_mismatch")
                latest = conn.scalar(
                    sa.select(sa.func.max(price_snapshots.c.version)).where(
                        price_snapshots.c.code == quote.code,
                        price_snapshots.c.trade_date == quote.latest.trade_date,
                    )
                )
                if latest != row["version"]:
                    raise NewsletterError("price_superseded")
                if row["version"] > 1:
                    corrected.append(quote.code)
                expiries.append(row["expires_at"])
                snapshot_ids.append(row["id"])
            run = (
                conn.execute(sa.select(runs).where(runs.c.id == inputs.news.run_id))
                .mappings()
                .one_or_none()
            )
            expected = inputs.news.report()
            expected["selected"] = [item_id(i) for i in inputs.news.selected]
            if (
                not run
                or run["payload"] != expected
                or not run["finished_at"] <= now < run["expires_at"]
            ):
                raise NewsletterError("news_run_missing_or_mismatch")
            expiries.append(run["expires_at"])
            for item in inputs.news.selected:
                stored = (
                    conn.execute(
                        sa.select(items)
                        .where(items.c.id == item_id(item))
                        .with_for_update()
                    )
                    .mappings()
                    .one_or_none()
                )
                if (
                    not stored
                    or stored["payload"] != item.metadata()
                    or not stored["first_stored_at"] <= now < stored["expires_at"]
                ):
                    raise NewsletterError("news_item_missing_or_mismatch")
                expiries.append(stored["expires_at"])
            edition = build_morning(
                inputs,
                now=now,
                corrected_codes=corrected,
                source_expires_at=min(expiries),
                schedule=self.schedule,
                title_translations=title_translations,
            )
            if edition.expires_at <= now:
                raise NewsletterError("source_expired")
            edition = MorningEdition.model_validate(
                edition.model_dump() | {"price_snapshot_ids": tuple(snapshot_ids)}
            )
            payload = edition.model_dump(mode="json")
            conn.execute(
                insert(editions).values(
                    id=edition.key,
                    recipient_scope=edition.recipient_scope,
                    target_date=edition.target_date,
                    slot=edition.slot,
                    status=edition.status,
                    input_hash=edition.input_hash,
                    content_hash=fingerprint(payload),
                    created_at=edition.created_at,
                    expires_at=edition.expires_at,
                    payload=payload,
                )
            )
            return edition

    @staticmethod
    def _decode(row):
        if fingerprint(row["payload"]) != row["content_hash"]:
            raise NewsletterError("edition_payload_mismatch")
        edition = MorningEdition.model_validate(row["payload"])
        if edition.key != row["id"] or edition.expires_at != row["expires_at"]:
            raise NewsletterError("edition_metadata_mismatch")
        return edition

    def get(self, key, *, now):
        with self.engine.connect() as conn:
            row = (
                conn.execute(
                    sa.select(editions).where(
                        editions.c.id == key,
                        editions.c.created_at <= aware(now),
                        editions.c.expires_at > aware(now),
                    )
                )
                .mappings()
                .one_or_none()
            )
        return self._decode(row) if row else None

    def purge_expired(self, *, now):
        with self.engine.begin() as conn:
            return conn.execute(
                editions.delete().where(editions.c.expires_at <= aware(now))
            ).rowcount

    def check(self, key, context):
        edition = self.get(key, now=context.now)
        if edition is None:
            return SendDecision(can_send=False, reasons=("edition_missing_or_expired",))
        reasons = list(check_send(edition, context, schedule=self.schedule).reasons)
        with self.engine.connect() as conn:
            opened = conn.scalar(
                sa.select(calendar_days.c.is_open).where(
                    calendar_days.c.observed_on == edition.target_date,
                    calendar_days.c.trade_date == edition.target_date,
                    calendar_days.c.retrieved_at <= context.now,
                )
            )
            if opened is not True:
                reasons.append("market_closed_or_unverified_in_database")
            current = conn.execute(sa.select(watchlist)).mappings().one_or_none()
            if (
                not current
                or current["revision"] != edition.watchlist_revision
                or tuple(current["codes"]) != edition.codes
            ):
                reasons.append("watchlist_changed_in_database")
            for snapshot_id in edition.price_snapshot_ids:
                row = (
                    conn.execute(
                        sa.select(price_snapshots).where(
                            price_snapshots.c.id == snapshot_id,
                            price_snapshots.c.expires_at > context.now,
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                latest = (
                    conn.scalar(
                        sa.select(sa.func.max(price_snapshots.c.version)).where(
                            price_snapshots.c.code == row["code"],
                            price_snapshots.c.trade_date == row["trade_date"],
                        )
                    )
                    if row
                    else None
                )
                if not row or row["version"] != latest:
                    reasons.append("price_missing_expired_or_superseded")
            for item_key in edition.news_item_ids:
                if not conn.scalar(
                    sa.select(items.c.id).where(
                        items.c.id == item_key, items.c.expires_at > context.now
                    )
                ):
                    reasons.append("news_item_missing_or_expired")
            keys = conn.scalars(
                sa.select(items.c.identity_keys)
                .join(deliveries)
                .where(
                    deliveries.c.recipient_scope == edition.recipient_scope,
                    deliveries.c.status.in_(["confirmed", "unknown"]),
                    deliveries.c.recorded_at <= context.now,
                    items.c.expires_at > context.now,
                )
            )
            if any(set(k).intersection(edition.news_keys) for k in keys):
                reasons.append("news_already_delivered_or_unknown")
        return SendDecision(can_send=not reasons, reasons=tuple(dict.fromkeys(reasons)))
