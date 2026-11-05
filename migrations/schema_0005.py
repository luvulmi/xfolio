"""T04 신규 morning 편성. legacy AM 승인 테이블과 분리한다."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

metadata = sa.MetaData()
editions = sa.Table(
    "newsletter_editions",
    metadata,
    sa.Column("id", sa.Text, primary_key=True),
    sa.Column("recipient_scope", sa.Text, nullable=False),
    sa.Column("target_date", sa.Date, nullable=False),
    sa.Column("slot", sa.Text, nullable=False),
    sa.Column("status", sa.Text, nullable=False),
    sa.Column("input_hash", sa.Text, nullable=False),
    sa.Column("content_hash", sa.Text, nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("payload", JSONB, nullable=False),
    sa.UniqueConstraint("recipient_scope", "target_date", "slot"),
    sa.CheckConstraint("slot = 'morning'"),
    sa.CheckConstraint("status IN ('ready','partial','failed','skipped')"),
    sa.CheckConstraint(
        "expires_at > created_at AND expires_at <= created_at + INTERVAL '2160 hours'"
    ),
    sa.CheckConstraint("NOT (payload ? 'facts') AND NOT (payload ? 'evidence_span')"),
)
sa.Index("ix_newsletter_edition_expiry", editions.c.expires_at)

IMMUTABLE_FUNCTION = """CREATE FUNCTION immutable_newsletter_edition() RETURNS trigger
LANGUAGE plpgsql AS $$ BEGIN
  IF NEW IS DISTINCT FROM OLD THEN RAISE EXCEPTION 'newsletter_edition_is_immutable'; END IF;
  RETURN NEW;
END; $$"""
