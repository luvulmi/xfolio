"""국내 시장 전용 PostgreSQL 계약. legacy 8개 테이블과 독립된 metadata."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

metadata = sa.MetaData()

instruments = sa.Table(
    "domestic_instruments",
    metadata,
    sa.Column("code", sa.Text, primary_key=True),
    sa.Column("isin", sa.Text, nullable=False, unique=True),
    sa.Column("name", sa.Text, nullable=False),
    sa.Column("market", sa.Text, nullable=False, server_default="KRX"),
    sa.Column("currency", sa.Text, nullable=False, server_default="KRW"),
    sa.Column("master_source", sa.Text, nullable=False),
    sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("eligible", sa.Boolean, nullable=False, server_default=sa.false()),
    sa.Column("eligibility_basis", sa.Text),
    sa.CheckConstraint(
        "code ~ '^[0-9]{6}$' AND isin ~ '^[A-Z]{2}[0-9A-Z]{9}[0-9]$' AND length(name) BETWEEN 1 AND 120"
    ),
    sa.CheckConstraint("market = 'KRX' AND currency = 'KRW'"),
    sa.CheckConstraint(
        "NOT eligible OR (eligibility_basis IS NOT NULL AND length(eligibility_basis) > 0)"
    ),
)
watchlist = sa.Table(
    "domestic_watchlist",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("revision", sa.Integer, nullable=False),
    sa.Column("codes", JSONB, nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("id = 1 AND revision > 0"),
    sa.CheckConstraint(
        "jsonb_typeof(codes) = 'array' AND jsonb_array_length(codes) BETWEEN 1 AND 10"
    ),
)
watchlist_versions = sa.Table(
    "domestic_watchlist_versions",
    metadata,
    sa.Column("revision", sa.Integer, primary_key=True),
    sa.Column("codes", JSONB, nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
)
calendar_requests = sa.Table(
    "domestic_calendar_requests",
    metadata,
    sa.Column("observed_on", sa.Date, primary_key=True),
    sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("status", sa.Text, nullable=False),
    sa.Column("reason", sa.Text),
    sa.CheckConstraint("status IN ('started','complete','failed')"),
)
calendar_days = sa.Table(
    "domestic_calendar_days",
    metadata,
    sa.Column("observed_on", sa.Date, primary_key=True),
    sa.Column("trade_date", sa.Date, primary_key=True),
    sa.Column("is_open", sa.Boolean, nullable=False),
    sa.Column("source", sa.Text, nullable=False),
    sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
)
market_runs = sa.Table(
    "domestic_market_runs",
    metadata,
    sa.Column("id", sa.Text, primary_key=True),
    sa.Column(
        "watchlist_revision",
        sa.Integer,
        sa.ForeignKey(watchlist_versions.c.revision),
        nullable=False,
    ),
    sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("status", sa.Text, nullable=False),
    sa.Column("errors", JSONB, nullable=False),
    sa.Column("trade_date", sa.Date),
    sa.Column(
        "observations", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")
    ),
    sa.CheckConstraint("started_at <= finished_at"),
    sa.CheckConstraint("status IN ('complete','partial','failed')"),
)
price_snapshots = sa.Table(
    "domestic_price_snapshots",
    metadata,
    sa.Column("id", sa.Text, primary_key=True),
    sa.Column("code", sa.Text, sa.ForeignKey(instruments.c.code), nullable=False),
    sa.Column("trade_date", sa.Date, nullable=False),
    sa.Column("version", sa.Integer, nullable=False),
    sa.Column("market", sa.Text, nullable=False, server_default="KRX"),
    sa.Column("currency", sa.Text, nullable=False, server_default="KRW"),
    sa.Column(
        "price_basis",
        sa.Text,
        nullable=False,
        server_default="unadjusted_regular_close",
    ),
    sa.Column("content_hash", sa.Text, nullable=False),
    sa.Column(
        "supersedes",
        sa.Text,
        sa.ForeignKey("domestic_price_snapshots.id", ondelete="SET NULL"),
    ),
    sa.Column("run_id", sa.Text, sa.ForeignKey(market_runs.c.id), nullable=False),
    sa.Column("close", sa.Numeric(18, 4), nullable=False),
    sa.Column("previous_close", sa.Numeric(18, 4), nullable=False),
    sa.Column("raw_change_pct", sa.Numeric(24, 8), nullable=False),
    sa.Column("change_pct", sa.Numeric(24, 8)),
    sa.Column("price_as_of", sa.DateTime(timezone=True)),
    sa.Column("scheduled_close", sa.DateTime(timezone=True), nullable=False),
    sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("first_stored_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("payload", JSONB, nullable=False),
    sa.UniqueConstraint("code", "trade_date", "version"),
    sa.CheckConstraint("close > 0 AND previous_close > 0 AND version > 0"),
    sa.CheckConstraint(
        "market = 'KRX' AND currency = 'KRW' AND price_basis = 'unadjusted_regular_close'"
    ),
    sa.CheckConstraint("price_as_of IS NULL OR price_as_of <= retrieved_at"),
    sa.CheckConstraint(
        "close < 'Infinity'::numeric AND previous_close < 'Infinity'::numeric"
    ),
    sa.CheckConstraint(
        "raw_change_pct NOT IN ('NaN'::numeric,'Infinity'::numeric,'-Infinity'::numeric)"
    ),
    sa.CheckConstraint(
        "scheduled_close <= retrieved_at AND retrieved_at <= first_stored_at"
    ),
    sa.CheckConstraint("expires_at = first_stored_at + INTERVAL '2160 hours'"),
    sa.CheckConstraint("(version = 1) OR change_pct IS NULL"),
)
sa.Index("ix_domestic_price_expiry", price_snapshots.c.expires_at)

WATCHLIST_FUNCTION = """CREATE FUNCTION validate_domestic_watchlist() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  PERFORM pg_advisory_xact_lock(718435903);
  IF EXISTS (SELECT 1 FROM jsonb_array_elements(NEW.codes) c WHERE jsonb_typeof(c) <> 'string') THEN
    RAISE EXCEPTION 'instrument_code_must_be_string';
  END IF;
  IF TG_OP = 'UPDATE' AND NEW.revision <> OLD.revision + 1 THEN
    RAISE EXCEPTION 'watchlist_revision_conflict';
  END IF;
  IF TG_OP = 'INSERT' AND NEW.revision <> 1 THEN
    RAISE EXCEPTION 'watchlist_initial_revision';
  END IF;
  IF (SELECT count(*) FROM jsonb_array_elements_text(NEW.codes)) <>
     (SELECT count(DISTINCT c) FROM jsonb_array_elements_text(NEW.codes) c) THEN
    RAISE EXCEPTION 'duplicate_instrument';
  END IF;
  IF EXISTS (SELECT 1 FROM jsonb_array_elements_text(NEW.codes) c
             WHERE NOT EXISTS (SELECT 1 FROM domestic_instruments i WHERE i.code = c AND i.eligible)) THEN
    RAISE EXCEPTION 'ineligible_instrument';
  END IF;
  RETURN NEW;
END; $$"""
WATCHLIST_AUDIT_FUNCTION = """CREATE FUNCTION audit_domestic_watchlist() RETURNS trigger
LANGUAGE plpgsql AS $$ BEGIN
  INSERT INTO domestic_watchlist_versions(revision,codes,created_at)
  VALUES (NEW.revision,NEW.codes,NEW.updated_at);
  RETURN NEW;
END; $$"""
PRICE_FUNCTION = """CREATE FUNCTION immutable_domestic_price() RETURNS trigger
LANGUAGE plpgsql AS $$ BEGIN
  IF NEW.supersedes IS NULL AND OLD.supersedes IS NOT NULL AND
     (to_jsonb(NEW) - 'supersedes') = (to_jsonb(OLD) - 'supersedes') THEN RETURN NEW; END IF;
  IF NEW IS DISTINCT FROM OLD THEN RAISE EXCEPTION 'price_version_is_immutable'; END IF;
  RETURN NEW;
END; $$"""
INSTRUMENT_FUNCTION = """CREATE FUNCTION guard_domestic_instrument() RETURNS trigger
LANGUAGE plpgsql AS $$ BEGIN
  PERFORM pg_advisory_xact_lock(718435903);
  IF EXISTS (SELECT 1 FROM domestic_watchlist WHERE codes ? OLD.code) AND
     (TG_OP = 'DELETE' OR NEW.code <> OLD.code OR NOT NEW.eligible) THEN
    RAISE EXCEPTION 'active_instrument_cannot_be_invalidated';
  END IF;
  IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
  RETURN NEW;
END; $$"""
