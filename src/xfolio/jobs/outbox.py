"""영속 Telegram 점유/시도/결과. 외부 전송과 DB commit의 원자성을 가정하지 않는다."""

import re
import secrets
from contextlib import nullcontext
from datetime import timedelta
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert

from xfolio.db.domestic import calendar_days, instruments, price_snapshots, watchlist
from xfolio.db.newsletter import editions
from xfolio.db.newsletter_news import deliveries as news_deliveries
from xfolio.db.newsletter_news import items as news_items
from xfolio.db.schema import operations_events, usage_ledger
from xfolio.db.telegram import attempts, outbox, parts
from xfolio.domestic.calendar import KST
from xfolio.jobs.telegram import SendResult, split_text
from xfolio.news_contracts import digest
from xfolio.newsletter import BudgetState, NewsletterError, SendContext
from xfolio.newsletter_news import aware
from xfolio.newsletter_store import NewsletterStore


class OutboxError(ValueError):
    """비밀 없는 고정 오류 코드."""


class _TransactionEngine:
    """T04의 읽기 검사를 같은 잠금/트랜잭션 안에 바인딩한다."""

    def __init__(self, conn):
        self.conn, self.dialect = conn, conn.dialect

    def connect(self):
        return nullcontext(self.conn)


def _json_value(value):
    return value.isoformat() if hasattr(value, "isoformat") else value


class TelegramOutboxStore:
    def __init__(
        self,
        engine,
        *,
        settings_store=None,
        recipient_scope="self",
        monthly_limit=Decimal(50000),
    ):
        if engine.dialect.name != "postgresql":
            raise OutboxError("postgresql_required")
        monthly_limit = Decimal(monthly_limit)
        if not monthly_limit.is_finite() or not 0 < monthly_limit <= 50000:
            raise OutboxError("monthly_limit_invalid")
        self.engine, self.recipient_scope = engine, recipient_scope
        self.monthly_limit = monthly_limit
        if settings_store is None:
            from xfolio.notification_settings import NotificationSettingsStore

            settings_store = NotificationSettingsStore(engine)
        self.settings_store = settings_store

    def enqueue(self, edition_id, *, now, mode="mock"):
        now = aware(now)
        if mode not in {"mock", "live"}:
            raise OutboxError("transport_mode_invalid")
        with self.engine.begin() as conn:
            edition = NewsletterStore(_TransactionEngine(conn)).get(edition_id, now=now)
            if edition is None or edition.recipient_scope != self.recipient_scope:
                raise OutboxError("edition_missing_or_wrong_recipient")
            if edition.status not in {"ready", "partial"}:
                raise OutboxError("edition_not_prepared")
            text_parts = split_text(edition.body)
            key = digest(edition.key + ":" + mode)
            inserted = conn.scalar(
                insert(outbox)
                .values(
                    id=key,
                    edition_id=edition.key,
                    recipient_scope=edition.recipient_scope,
                    target_date=edition.target_date,
                    slot=edition.slot,
                    transport_mode=mode,
                    status="pending",
                    part_count=len(text_parts),
                    created_at=now,
                    updated_at=now,
                    expires_at=now + timedelta(days=365),
                )
                .on_conflict_do_nothing()
                .returning(outbox.c.id)
            )
            if inserted:
                conn.execute(
                    parts.insert(),
                    [
                        {
                            "outbox_id": key,
                            "position": position,
                            "content_hash": digest(text),
                            "status": "pending",
                            "attempt_count": 0,
                        }
                        for position, text in enumerate(text_parts, 1)
                    ],
                )
            return key

    def _row(self, conn, key):
        return (
            conn.execute(sa.select(outbox).where(outbox.c.id == key).with_for_update())
            .mappings()
            .one_or_none()
        )

    def _guard(self, conn, row, *, now):
        # The caller holds the shared AI-budget advisory lock and this outbox row.
        settings = self.settings_store.get(conn=conn, for_update=True)
        current = (
            conn.execute(
                sa.select(watchlist).where(watchlist.c.id == 1).with_for_update()
            )
            .mappings()
            .one_or_none()
        )
        if current is None:
            raise OutboxError("watchlist_not_initialized")
        conn.execute(
            sa.select(instruments.c.code)
            .where(instruments.c.code.in_(current["codes"]))
            .order_by(instruments.c.code)
            .with_for_update()
        ).all()
        conn.execute(
            sa.select(editions.c.id)
            .where(editions.c.id == row["edition_id"])
            .with_for_update()
        ).all()
        edition = NewsletterStore(_TransactionEngine(conn)).get(
            row["edition_id"], now=now
        )
        if edition is not None:
            conn.execute(
                sa.select(price_snapshots.c.id)
                .where(price_snapshots.c.id.in_(edition.price_snapshot_ids))
                .order_by(price_snapshots.c.id)
                .with_for_update()
            ).all()
            conn.execute(
                sa.select(news_items.c.id)
                .where(news_items.c.id.in_(edition.news_item_ids))
                .order_by(news_items.c.id)
                .with_for_update()
            ).all()
        day = row["target_date"]
        opened = (
            conn.execute(
                sa.select(calendar_days)
                .where(
                    calendar_days.c.observed_on == day,
                    calendar_days.c.trade_date == day,
                    calendar_days.c.retrieved_at <= now,
                )
                .with_for_update()
            )
            .mappings()
            .one_or_none()
        )
        month = now.astimezone(KST).strftime("%Y-%m")
        totals = dict(
            conn.execute(
                sa.select(usage_ledger.c.state, sa.func.sum(usage_ledger.c.amount_krw))
                .where(usage_ledger.c.month == month)
                .group_by(usage_ledger.c.state)
            ).all()
        )
        context = SendContext(
            now=now,
            settings=settings,
            watchlist_revision=current["revision"],
            active_codes=tuple(current["codes"]),
            recipient_scope=self.recipient_scope,
            allowed_recipient_scopes=(self.recipient_scope,),
            chat_type="private",
            market_open=opened["is_open"] if opened else None,
            calendar_checked_at=now,
            budget=BudgetState(
                month=month,
                checked_at=now,
                limit_krw=self.monthly_limit,
                confirmed_krw=totals.get("confirmed", 0),
                reserved_krw=totals.get("reserved", 0) + totals.get("estimated", 0),
                expected_krw=0,
            ),
        )
        decision = NewsletterStore(_TransactionEngine(conn)).check(
            row["edition_id"], context
        )
        reasons = tuple(
            r
            for r in decision.reasons
            if not (row["transport_mode"] == "mock" and r == "dry_run_or_synthetic")
        )
        return reasons

    def claim(self, key, *, now):
        now = aware(now)
        with self.engine.begin() as conn:
            conn.execute(sa.text("SELECT pg_advisory_xact_lock(718435902)"))
            row = self._row(conn, key)
            if not row or row["status"] not in {"pending", "retryable_failure"}:
                return None
            retry = conn.scalar(
                sa.select(parts.c.retry_at).where(
                    parts.c.outbox_id == key, parts.c.status == "retryable_failure"
                )
            )
            if retry is not None and retry > now:
                return None
            reasons = self._guard(conn, row, now=now)
            if reasons:
                confirmed = conn.scalar(
                    sa.select(sa.func.count())
                    .select_from(parts)
                    .where(parts.c.outbox_id == key, parts.c.status == "confirmed")
                )
                if confirmed:
                    self._finish(conn, row, now=now, failure=reasons[0])
                else:
                    conn.execute(
                        outbox.update()
                        .where(outbox.c.id == key)
                        .values(status="skipped", error_code=reasons[0], updated_at=now)
                    )
                return None
            token = secrets.token_hex(16)
            conn.execute(
                outbox.update()
                .where(outbox.c.id == key)
                .values(
                    status="sending",
                    claim_token=token,
                    lease_until=now + timedelta(seconds=90),
                    updated_at=now,
                )
            )
            return token

    def start_part(self, key, position, token, *, now):
        now = aware(now)
        with self.engine.begin() as conn:
            conn.execute(sa.text("SELECT pg_advisory_xact_lock(718435902)"))
            row = self._row(conn, key)
            if (
                not row
                or row["status"] != "sending"
                or row["claim_token"] != token
                or row["lease_until"] <= now
            ):
                return None
            part = (
                conn.execute(
                    sa.select(parts)
                    .where(parts.c.outbox_id == key, parts.c.position == position)
                    .with_for_update()
                )
                .mappings()
                .one_or_none()
            )
            if not part or part["status"] not in {"pending", "retryable_failure"}:
                return None
            if conn.scalar(
                sa.select(sa.func.count())
                .select_from(parts)
                .where(
                    parts.c.outbox_id == key,
                    parts.c.position < position,
                    parts.c.status != "confirmed",
                )
            ):
                return None
            if part["retry_at"] is not None and part["retry_at"] > now:
                return None
            reasons = self._guard(conn, row, now=now)
            if reasons:
                self._finish(conn, row, now=now, failure=reasons[0])
                return None
            attempt = secrets.token_hex(16)
            conn.execute(
                attempts.insert().values(
                    id=attempt,
                    outbox_id=key,
                    position=position,
                    attempt_number=part["attempt_count"] + 1,
                    started_at=now,
                    status="sending",
                )
            )
            conn.execute(
                parts.update()
                .where(parts.c.outbox_id == key, parts.c.position == position)
                .values(
                    status="sending",
                    started_at=now,
                    attempt_count=part["attempt_count"] + 1,
                    retry_at=None,
                    error_code=None,
                )
            )
            conn.execute(
                outbox.update()
                .where(outbox.c.id == key)
                .values(lease_until=now + timedelta(seconds=90), updated_at=now)
            )
            return attempt

    def finish_part(self, key, position, token, attempt, result: SendResult, *, now):
        now = aware(now)
        if result.status not in {"confirmed", "failed", "unknown", "retryable_failure"}:
            raise OutboxError("transport_result_invalid")
        if (result.status == "confirmed") != bool(result.message_id):
            raise OutboxError("transport_receipt_invalid")
        if result.message_id and not re.fullmatch(
            r"(?:mock-)?[1-9][0-9]*", result.message_id
        ):
            raise OutboxError("transport_receipt_invalid")
        safe_errors = {
            None,
            "telegram_text_invalid",
            "telegram_result_unknown",
            "telegram_response_invalid",
            "telegram_rate_limited",
            "telegram_retry_after_invalid",
            "telegram_receipt_unverified",
            "telegram_request_rejected",
            "message_content_mismatch",
            "transport_interrupted",
        }
        if result.error_code not in safe_errors:
            raise OutboxError("transport_error_code_invalid")
        with self.engine.begin() as conn:
            row = self._row(conn, key)
            if not row or row["status"] != "sending" or row["claim_token"] != token:
                raise OutboxError("claim_lost_result_unknown")
            part = (
                conn.execute(
                    sa.select(parts)
                    .where(parts.c.outbox_id == key, parts.c.position == position)
                    .with_for_update()
                )
                .mappings()
                .one()
            )
            record = (
                conn.execute(sa.select(attempts).where(attempts.c.id == attempt))
                .mappings()
                .one_or_none()
            )
            if (
                part["status"] != "sending"
                or not record
                or record["status"] != "sending"
                or record["outbox_id"] != key
                or record["position"] != position
            ):
                raise OutboxError("attempt_state_conflict")
            retry_at = (
                now + timedelta(seconds=result.retry_after)
                if result.status == "retryable_failure" and result.retry_after
                else None
            )
            if result.status == "retryable_failure" and retry_at is None:
                raise OutboxError("retry_after_required")
            conn.execute(
                attempts.update()
                .where(attempts.c.id == attempt)
                .values(
                    status=result.status,
                    finished_at=now,
                    message_id=result.message_id,
                    error_code=result.error_code,
                )
            )
            conn.execute(
                parts.update()
                .where(parts.c.outbox_id == key, parts.c.position == position)
                .values(
                    status=result.status,
                    finished_at=now,
                    message_id=result.message_id,
                    error_code=result.error_code,
                    retry_at=retry_at,
                )
            )
            if result.status == "confirmed":
                states = conn.scalars(
                    sa.select(parts.c.status).where(parts.c.outbox_id == key)
                ).all()
                if all(s == "confirmed" for s in states):
                    self._finish(conn, row, now=now)
            elif result.status == "retryable_failure":
                from xfolio.newsletter import at

                if retry_at >= at(row["target_date"], 8, 10):
                    self._finish(conn, row, now=now, failure="retry_exceeds_deadline")
                else:
                    conn.execute(
                        outbox.update()
                        .where(outbox.c.id == key)
                        .values(
                            status="retryable_failure",
                            claim_token=None,
                            lease_until=None,
                            updated_at=now,
                            error_code=result.error_code,
                        )
                    )
            else:
                self._finish(conn, row, now=now, failure=result.error_code)

    def _record_news(self, conn, row, state, now):
        if row["transport_mode"] != "live" or state not in {
            "confirmed",
            "partial",
            "unknown",
        }:
            return
        edition = NewsletterStore(_TransactionEngine(conn)).get(
            row["edition_id"], now=now
        )
        if edition is None:
            return
        message_ids = conn.scalars(
            sa.select(parts.c.message_id)
            .where(parts.c.outbox_id == row["id"], parts.c.status == "confirmed")
            .order_by(parts.c.position)
        ).all()
        for item in edition.news_item_ids:
            conn.execute(
                sa.select(news_items.c.id)
                .where(news_items.c.id == item)
                .with_for_update()
            ).all()
            conn.execute(
                insert(news_deliveries)
                .values(
                    id=digest(row["recipient_scope"] + ":" + item),
                    item_id=item,
                    recipient_scope=row["recipient_scope"],
                    status="confirmed" if state == "confirmed" else "unknown",
                    message_id=",".join(message_ids) if state == "confirmed" else None,
                    recorded_at=now,
                )
                .on_conflict_do_nothing()
            )

    def _finish(self, conn, row, *, now, failure=None):
        states = conn.scalars(
            sa.select(parts.c.status).where(parts.c.outbox_id == row["id"])
        ).all()
        state = (
            "unknown"
            if "unknown" in states or "sending" in states
            else "confirmed"
            if all(s == "confirmed" for s in states)
            else "partial"
            if "confirmed" in states
            else "failed"
        )
        conn.execute(
            outbox.update()
            .where(outbox.c.id == row["id"])
            .values(
                status=state,
                error_code=failure,
                lease_until=None,
                claim_token=None,
                updated_at=now,
            )
        )
        self._record_news(conn, row, state, now)

    def recover_stale(self, *, now):
        now = aware(now)
        recovered = 0
        with self.engine.begin() as conn:
            rows = (
                conn.execute(
                    sa.select(outbox)
                    .where(outbox.c.status == "sending", outbox.c.lease_until <= now)
                    .with_for_update(skip_locked=True)
                )
                .mappings()
                .all()
            )
            for row in rows:
                conn.execute(
                    parts.update()
                    .where(parts.c.outbox_id == row["id"], parts.c.status == "sending")
                    .values(
                        status="unknown",
                        error_code="worker_interrupted",
                        finished_at=now,
                    )
                )
                conn.execute(
                    attempts.update()
                    .where(
                        attempts.c.outbox_id == row["id"],
                        attempts.c.status == "sending",
                    )
                    .values(
                        status="unknown",
                        error_code="worker_interrupted",
                        finished_at=now,
                    )
                )
                conn.execute(
                    outbox.update()
                    .where(outbox.c.id == row["id"])
                    .values(
                        status="unknown",
                        error_code="worker_interrupted",
                        updated_at=now,
                        claim_token=None,
                        lease_until=None,
                    )
                )
                self._record_news(conn, row, "unknown", now)
                recovered += 1
        return recovered

    def _serialize(self, conn, row, *, now, detail):
        result = {
            k: _json_value(v)
            for k, v in row.items()
            if k not in {"claim_token", "lease_until"}
        }
        if detail:
            result["parts"] = [
                {k: _json_value(v) for k, v in p.items()}
                for p in conn.execute(
                    sa.select(parts)
                    .where(parts.c.outbox_id == row["id"])
                    .order_by(parts.c.position)
                ).mappings()
            ]
            result["attempts"] = [
                {k: _json_value(v) for k, v in p.items()}
                for p in conn.execute(
                    sa.select(attempts)
                    .where(attempts.c.outbox_id == row["id"])
                    .order_by(attempts.c.started_at)
                ).mappings()
            ]
            edition = NewsletterStore(_TransactionEngine(conn)).get(
                row["edition_id"], now=now
            )
            result["body"] = edition.body if edition else None
        return result

    def list_deliveries(self, *, now, limit=50):
        now = aware(now)
        if not 1 <= limit <= 100:
            raise OutboxError("limit_invalid")
        with self.engine.connect() as conn:
            return [
                self._serialize(conn, row, now=now, detail=False)
                for row in conn.execute(
                    sa.select(outbox)
                    .where(outbox.c.expires_at > now, outbox.c.created_at <= now)
                    .order_by(outbox.c.created_at.desc(), outbox.c.id)
                    .limit(limit)
                ).mappings()
            ]

    def get_delivery(self, id, *, now):
        now = aware(now)
        with self.engine.connect() as conn:
            row = (
                conn.execute(
                    sa.select(outbox).where(
                        outbox.c.id == id,
                        outbox.c.created_at <= now,
                        outbox.c.expires_at > now,
                    )
                )
                .mappings()
                .one_or_none()
            )
            return self._serialize(conn, row, now=now, detail=True) if row else None

    def purge_expired(self, *, now):
        with self.engine.begin() as conn:
            count = conn.execute(
                outbox.delete().where(outbox.c.expires_at <= aware(now))
            ).rowcount
            conn.execute(
                operations_events.delete().where(
                    operations_events.c.kind == "newsletter_worker",
                    operations_events.c.expires_at <= aware(now),
                )
            )
            return count

    def record_worker_state(self, *, day, status, reason, now):
        """휴장/미확인도 본문 없는 서버 관측으로 남긴다. 같은 사유는 하루1회."""
        now = aware(now)
        allowed = {
            "weekend",
            "market_closed",
            "calendar_unverified",
            "market_closed_or_unverified",
            "outside_preparation_window",
            "outside_send_window",
            "edition_missing_or_expired",
        }
        if status not in {"failed", "skipped"} or reason not in allowed:
            raise OutboxError("worker_state_invalid")
        key = digest(f"{self.recipient_scope}:{day}:{reason}")
        with self.engine.begin() as conn:
            conn.execute(
                insert(operations_events)
                .values(
                    id=key,
                    kind="newsletter_worker",
                    scope=self.recipient_scope,
                    unique_key=key,
                    created_at=now,
                    expires_at=now + timedelta(days=365),
                    payload={
                        "target_date": day.isoformat(),
                        "slot": "morning",
                        "status": status,
                        "reason": reason,
                    },
                )
                .on_conflict_do_nothing()
            )


def dispatch(store, key, transport, *, clock):
    """한 번에 각 pending 조각을 전송. 429는 다음 호출에서만 안전 재시도한다."""
    row = store.get_delivery(key, now=clock())
    if not row or row["transport_mode"] != transport.mode:
        raise OutboxError("transport_mode_mismatch")
    token = store.claim(key, now=clock())
    if token is None:
        return store.get_delivery(key, now=clock())
    if not row["body"]:
        raise NewsletterError("edition_missing_or_expired")
    text_parts = split_text(row["body"])
    for part, text in zip(row["parts"], text_parts, strict=True):
        if part["status"] == "confirmed":
            continue
        attempt = store.start_part(key, part["position"], token, now=clock())
        if attempt is None:
            break
        if part["content_hash"] != digest(text):
            result = SendResult("failed", error_code="message_content_mismatch")
        else:
            try:
                result = transport.send(text)
            except Exception:  # noqa: BLE001 -- adapter 예외도 성공 여부를 확정할 수 없다.
                # The request may have reached Telegram; never auto-retry this case.
                result = SendResult("unknown", error_code="transport_interrupted")
        store.finish_part(key, part["position"], token, attempt, result, now=clock())
        if result.status != "confirmed":
            break
    return store.get_delivery(key, now=clock())
