"""8개 운영 저장 단위의 SQLAlchemy Core 계약."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

metadata = sa.MetaData()

news_cursors = sa.Table(
    "news_cursors",
    metadata,
    sa.Column("id", sa.Text, primary_key=True),
    sa.Column("provider", sa.Text, nullable=False),
    sa.Column("query_version", sa.Text, nullable=False),
    sa.Column("scope", sa.Text, nullable=False),
    sa.Column("completed_until", sa.DateTime(timezone=True)),
    sa.Column("revision", sa.Integer, nullable=False, server_default="0"),
    sa.UniqueConstraint("provider", "query_version", "scope"),
)
collection_runs = sa.Table(
    "collection_runs",
    metadata,
    sa.Column("id", sa.Text, primary_key=True),
    sa.Column("provider", sa.Text, nullable=False),
    sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
    sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
    sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("status", sa.Text, nullable=False),
    sa.Column("payload", JSONB, nullable=False),
    sa.CheckConstraint("status IN ('complete','partial','failed')"),
    sa.CheckConstraint("window_start < window_end AND window_end <= finished_at"),
)
evidence_bundles = sa.Table(
    "evidence_bundles",
    metadata,
    sa.Column("id", sa.Text, primary_key=True),
    sa.Column("source_id", sa.Text, nullable=False),
    sa.Column("content_version", sa.Text, nullable=False),
    sa.Column("event_key", sa.Text, nullable=False),
    sa.Column("published_at", sa.DateTime(timezone=True)),
    sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("rights_verified", sa.Boolean, nullable=False, server_default=sa.false()),
    sa.Column("payload", JSONB, nullable=False),
    sa.UniqueConstraint("source_id", "content_version"),
)
content_drafts = sa.Table(
    "content_drafts",
    metadata,
    sa.Column("id", sa.Text, primary_key=True),
    sa.Column("edition_id", sa.Text, nullable=False),
    sa.Column("version", sa.Integer, nullable=False),
    sa.Column("content_hash", sa.Text, nullable=False),
    sa.Column("synthetic", sa.Boolean, nullable=False, server_default=sa.true()),
    sa.Column(
        "validation_passed", sa.Boolean, nullable=False, server_default=sa.false()
    ),
    sa.Column("payload", JSONB, nullable=False),
    sa.UniqueConstraint("edition_id", "version"),
    sa.CheckConstraint("version > 0"),
)
publication_jobs = sa.Table(
    "publication_jobs",
    metadata,
    sa.Column("id", sa.Text, primary_key=True),
    sa.Column("account_id", sa.Text, nullable=False),
    sa.Column("target_date", sa.Date, nullable=False),
    sa.Column("edition", sa.Text, nullable=False),
    sa.Column("draft_id", sa.Text, sa.ForeignKey("content_drafts.id"), nullable=False),
    sa.Column("decision_revision", sa.Integer, nullable=False, server_default="0"),
    sa.Column("status", sa.Text, nullable=False, server_default="prepared"),
    sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("first_attempt_at", sa.DateTime(timezone=True)),
    sa.Column("reserved_count", sa.Integer, nullable=False, server_default="0"),
    sa.Column("stop_requested", sa.Boolean, nullable=False, server_default=sa.false()),
    sa.Column("payload", JSONB, nullable=False),
    sa.UniqueConstraint("account_id", "target_date", "edition"),
    sa.CheckConstraint("edition IN ('AM','PM')"),
    sa.CheckConstraint("scheduled_at < expires_at"),
    sa.CheckConstraint("decision_revision >= 0 AND reserved_count BETWEEN 0 AND 3"),
)
publication_posts = sa.Table(
    "publication_posts",
    metadata,
    sa.Column("id", sa.Text, primary_key=True),
    sa.Column("job_id", sa.Text, sa.ForeignKey("publication_jobs.id"), nullable=False),
    sa.Column("account_id", sa.Text, nullable=False),
    sa.Column("position", sa.Integer, nullable=False),
    sa.Column("content_version", sa.Integer, nullable=False),
    sa.Column("event_key", sa.Text),
    sa.Column("fact_version", sa.Text),
    sa.Column("state", sa.Text, nullable=False),
    sa.Column("active_claim", sa.Boolean, nullable=False, server_default=sa.false()),
    sa.Column("x_id", sa.Text),
    sa.Column("payload", JSONB, nullable=False),
    sa.UniqueConstraint("job_id", "content_version", "position"),
    sa.CheckConstraint("position BETWEEN 1 AND 3"),
    sa.CheckConstraint(
        "NOT active_claim OR (event_key IS NOT NULL AND fact_version IS NOT NULL)"
    ),
)
sa.Index(
    "uq_active_event_claim",
    publication_posts.c.account_id,
    publication_posts.c.event_key,
    publication_posts.c.fact_version,
    unique=True,
    postgresql_where=publication_posts.c.active_claim.is_(True),
)
usage_ledger = sa.Table(
    "usage_ledger",
    metadata,
    sa.Column("id", sa.Text, primary_key=True),
    sa.Column("provider", sa.Text, nullable=False),
    sa.Column("month", sa.Text, nullable=False),
    sa.Column("job_id", sa.Text, sa.ForeignKey("publication_jobs.id")),
    sa.Column("state", sa.Text, nullable=False),
    sa.Column("amount_krw", sa.Numeric(14, 4), nullable=False),
    sa.Column("payload", JSONB, nullable=False),
    sa.CheckConstraint("amount_krw >= 0"),
    sa.CheckConstraint("state IN ('estimated','reserved','confirmed','released')"),
)
operations_events = sa.Table(
    "operations_events",
    metadata,
    sa.Column("id", sa.Text, primary_key=True),
    sa.Column("kind", sa.Text, nullable=False),
    sa.Column("scope", sa.Text),
    sa.Column("unique_key", sa.Text),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("expires_at", sa.DateTime(timezone=True)),
    sa.Column("payload", JSONB, nullable=False),
    sa.UniqueConstraint("kind", "scope", "unique_key"),
)
