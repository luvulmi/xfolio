"""T05 singleton 알림 설정과 가격 없는1년 변경 감사."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

metadata = sa.MetaData()
settings = sa.Table(
    "notification_settings",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("revision", sa.Integer, nullable=False),
    sa.Column("morning_enabled", sa.Boolean, nullable=False),
    sa.Column("paused", sa.Boolean, nullable=False),
    sa.Column("intraday_enabled", sa.Boolean, nullable=False),
    sa.Column("close_enabled", sa.Boolean, nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("id = 1"),
    sa.CheckConstraint("revision >= 1"),
)
audit = sa.Table(
    "notification_setting_audit",
    metadata,
    sa.Column("id", sa.Text, primary_key=True),
    sa.Column("actor", sa.Text, nullable=False),
    sa.Column("kind", sa.Text, nullable=False),
    sa.Column("revision", sa.Integer, nullable=False),
    sa.Column("before", JSONB, nullable=False),
    sa.Column("after", JSONB, nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("kind IN ('settings','watchlist')"),
    sa.CheckConstraint("expires_at > created_at"),
)
sa.Index("ix_notification_audit_expiry", audit.c.expires_at)
