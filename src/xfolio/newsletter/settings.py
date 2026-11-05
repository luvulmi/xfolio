"""API와 worker가 공유하는 설정 조회·revision 변경 경계."""

import secrets
from datetime import timedelta

import sqlalchemy as sa

from xfolio.db.notification_settings import audit, settings
from xfolio.news.collection import aware
from xfolio.newsletter.edition import MorningSettings

FIELDS = frozenset(MorningSettings.model_fields) - {"revision"}


class NotificationSettingsError(ValueError):
    """비밀이나 요청값을 포함하지 않는 고정 오류."""


def record_audit(conn, *, actor, kind, before, after, revision, now):
    if not isinstance(actor, str) or not 1 <= len(actor) <= 254:
        raise NotificationSettingsError("invalid_actor")
    now = aware(now)
    conn.execute(
        audit.insert().values(
            id=secrets.token_hex(16),
            actor=actor,
            kind=kind,
            revision=revision,
            before=before,
            after=after,
            created_at=now,
            expires_at=now + timedelta(days=365),
        )
    )


class NotificationSettingsStore:
    def __init__(self, engine):
        if engine.dialect.name != "postgresql":
            raise NotificationSettingsError("postgresql_required")
        self.engine = engine

    def get(self, *, conn=None, for_update=False):
        if conn is None:
            if for_update:
                raise NotificationSettingsError("transaction_required")
            with self.engine.connect() as connection:
                return self.get(conn=connection)
        if for_update and not conn.in_transaction():
            raise NotificationSettingsError("transaction_required")
        query = sa.select(settings).where(settings.c.id == 1)
        if for_update:
            query = query.with_for_update()
        row = conn.execute(query).mappings().one_or_none()
        if row is None:
            raise NotificationSettingsError("settings_not_initialized")
        return MorningSettings.model_validate(
            {name: row[name] for name in MorningSettings.model_fields}
        )

    def update(self, *, expected_revision, changes, actor, now):
        if type(expected_revision) is not int or expected_revision < 1:
            raise NotificationSettingsError("invalid_revision")
        if (
            not changes
            or set(changes) - FIELDS
            or any(type(v) is not bool for v in changes.values())
        ):
            raise NotificationSettingsError("invalid_settings_change")
        if changes.get("intraday_enabled") or changes.get("close_enabled"):
            raise NotificationSettingsError("afternoon_not_accepted")
        now = aware(now)
        with self.engine.begin() as conn:
            current = self.get(conn=conn, for_update=True)
            if current.revision != expected_revision:
                raise NotificationSettingsError("revision_conflict")
            values = current.model_dump() | changes
            if values == current.model_dump():
                return current
            values["revision"] += 1
            result = MorningSettings.model_validate(values)
            conn.execute(
                settings.update()
                .where(settings.c.id == 1)
                .values(**values, updated_at=now)
            )
            record_audit(
                conn,
                actor=actor,
                kind="settings",
                before=current.model_dump(),
                after=result.model_dump(),
                revision=result.revision,
                now=now,
            )
            return result

    def purge_expired(self, *, now):
        with self.engine.begin() as conn:
            return conn.execute(
                audit.delete().where(audit.c.expires_at <= aware(now))
            ).rowcount
