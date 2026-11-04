"""개인 뉴스레터 수집·최소 메타데이터·기발송 계약. legacy 테이블과 독립."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

metadata = sa.MetaData()
runs = sa.Table(
    "newsletter_news_runs",
    metadata,
    sa.Column("id", sa.Text, primary_key=True),
    sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
    sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("status", sa.Text, nullable=False),
    sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("payload", JSONB, nullable=False),
    sa.CheckConstraint("status IN ('complete','partial','failed')"),
    sa.CheckConstraint("as_of <= finished_at"),
    sa.CheckConstraint("expires_at = finished_at + INTERVAL '2160 hours'"),
)
items = sa.Table(
    "newsletter_news_items",
    metadata,
    sa.Column("id", sa.Text, primary_key=True),
    sa.Column("provider", sa.Text, nullable=False),
    sa.Column("source_id", sa.Text, nullable=False),
    sa.Column("content_version", sa.Text, nullable=False),
    sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("first_stored_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("identity_keys", JSONB, nullable=False),
    sa.Column("payload", JSONB, nullable=False),
    sa.UniqueConstraint("provider", "source_id", "content_version"),
    sa.CheckConstraint("provider IN ('Finnhub','BLS','BEA','Board')"),
    sa.CheckConstraint(
        "published_at <= retrieved_at AND retrieved_at <= first_stored_at"
    ),
    sa.CheckConstraint("expires_at = first_stored_at + INTERVAL '2160 hours'"),
    sa.CheckConstraint(
        "NOT (payload ? 'facts') AND NOT (payload ? 'text') AND NOT (payload ? 'evidence_span')"
    ),
)
deliveries = sa.Table(
    "newsletter_news_deliveries",
    metadata,
    sa.Column("id", sa.Text, primary_key=True),
    sa.Column(
        "item_id",
        sa.Text,
        sa.ForeignKey(items.c.id, ondelete="CASCADE"),
        nullable=False,
    ),
    sa.Column("recipient_scope", sa.Text, nullable=False),
    sa.Column("status", sa.Text, nullable=False),
    sa.Column("message_id", sa.Text),
    sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
    sa.UniqueConstraint("item_id", "recipient_scope"),
    sa.CheckConstraint("status IN ('confirmed','failed','unknown')"),
    sa.CheckConstraint(
        "(status = 'confirmed' AND message_id IS NOT NULL) OR (status <> 'confirmed' AND message_id IS NULL)"
    ),
)
sa.Index("ix_newsletter_news_expiry", items.c.expires_at)
