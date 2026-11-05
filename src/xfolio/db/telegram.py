"""가격/뉴스 본문 없는 Telegram 발송 메타데이터와 조각별 영속 시도."""

import sqlalchemy as sa

metadata = sa.MetaData()
outbox = sa.Table(
    "telegram_outbox",
    metadata,
    sa.Column("id", sa.Text, primary_key=True),
    sa.Column("edition_id", sa.Text, nullable=False),
    sa.Column("recipient_scope", sa.Text, nullable=False),
    sa.Column("target_date", sa.Date, nullable=False),
    sa.Column("slot", sa.Text, nullable=False),
    sa.Column("transport_mode", sa.Text, nullable=False),
    sa.Column("status", sa.Text, nullable=False),
    sa.Column("part_count", sa.Integer, nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("lease_until", sa.DateTime(timezone=True)),
    sa.Column("claim_token", sa.Text),
    sa.Column("error_code", sa.Text),
    sa.UniqueConstraint("recipient_scope", "target_date", "slot", "transport_mode"),
    sa.CheckConstraint("slot = 'morning' AND transport_mode IN ('mock','live')"),
    sa.CheckConstraint(
        "status IN ('pending','sending','confirmed','partial','failed','unknown','retryable_failure','skipped')"
    ),
    sa.CheckConstraint("part_count > 0 AND updated_at >= created_at"),
    sa.CheckConstraint("expires_at = created_at + INTERVAL '8760 hours'"),
)
parts = sa.Table(
    "telegram_outbox_parts",
    metadata,
    sa.Column(
        "outbox_id",
        sa.Text,
        sa.ForeignKey(outbox.c.id, ondelete="CASCADE"),
        primary_key=True,
    ),
    sa.Column("position", sa.Integer, primary_key=True),
    sa.Column("content_hash", sa.Text, nullable=False),
    sa.Column("status", sa.Text, nullable=False),
    sa.Column("message_id", sa.Text),
    sa.Column("attempt_count", sa.Integer, nullable=False, server_default="0"),
    sa.Column("started_at", sa.DateTime(timezone=True)),
    sa.Column("finished_at", sa.DateTime(timezone=True)),
    sa.Column("retry_at", sa.DateTime(timezone=True)),
    sa.Column("error_code", sa.Text),
    sa.CheckConstraint("position > 0 AND attempt_count >= 0"),
    sa.CheckConstraint(
        "status IN ('pending','sending','confirmed','failed','unknown','retryable_failure')"
    ),
    sa.CheckConstraint("(status = 'confirmed') = (message_id IS NOT NULL)"),
)
attempts = sa.Table(
    "telegram_send_attempts",
    metadata,
    sa.Column("id", sa.Text, primary_key=True),
    sa.Column(
        "outbox_id",
        sa.Text,
        sa.ForeignKey(outbox.c.id, ondelete="CASCADE"),
        nullable=False,
    ),
    sa.Column("position", sa.Integer, nullable=False),
    sa.Column("attempt_number", sa.Integer, nullable=False),
    sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("finished_at", sa.DateTime(timezone=True)),
    sa.Column("status", sa.Text, nullable=False),
    sa.Column("error_code", sa.Text),
    sa.Column("message_id", sa.Text),
    sa.UniqueConstraint("outbox_id", "position", "attempt_number"),
    sa.CheckConstraint("position > 0 AND attempt_number > 0"),
    sa.CheckConstraint(
        "status IN ('sending','confirmed','failed','unknown','retryable_failure')"
    ),
)
sa.Index("ix_telegram_outbox_expiry", outbox.c.expires_at)
