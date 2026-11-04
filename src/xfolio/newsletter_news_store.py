"""PostgreSQL 성공 전달만 기발송 제외. 수집 저장으로 성공 상태를 만들지 않는다."""

from datetime import timedelta

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert

from xfolio.db.newsletter_news import deliveries, items, runs
from xfolio.news_contracts import digest
from xfolio.newsletter_news import NewsError, NewsResult, aware


def item_id(item):
    return digest(item.provider + ":" + item.source_id + ":" + item.content_version)


class NewsletterNewsStore:
    def __init__(self, engine):
        if engine.dialect.name != "postgresql":
            raise NewsError("postgresql_required")
        self.engine = engine

    @classmethod
    def from_url(cls, url):
        from sqlalchemy.engine import make_url

        try:
            parsed = make_url(url)
            if parsed.get_backend_name() != "postgresql":
                raise ValueError
            parsed = parsed.set(drivername="postgresql+psycopg")
            return cls(sa.create_engine(parsed, hide_parameters=True))
        except ValueError:
            raise NewsError("postgresql_url_invalid") from None

    def seen_keys(self, *, recipient_scope, now):
        now = aware(now)
        with self.engine.connect() as conn:
            rows = (
                conn.execute(
                    sa.select(items.c.identity_keys)
                    .join(deliveries)
                    .where(
                        deliveries.c.recipient_scope == recipient_scope,
                        deliveries.c.status == "confirmed",
                        deliveries.c.recorded_at <= now,
                        items.c.expires_at > now,
                    )
                )
                .scalars()
                .all()
            )
        return frozenset(key for row in rows for key in row)

    def save_result(self, result, *, now):
        result = NewsResult.model_validate_json(result.model_dump_json())
        now = aware(now)
        if result.finished_at > now or any(
            i.retrieved_at > now for i in result.selected
        ):
            raise NewsError("storage_time_invalid")
        report = result.report()
        # run의 JSON에 자료를 복제하지 않는다. 선택 ID와 출처 집계만 보관한다.
        report["selected"] = [item_id(i) for i in result.selected]
        with self.engine.begin() as conn:
            conn.execute(
                insert(runs)
                .values(
                    id=result.run_id,
                    as_of=result.as_of,
                    finished_at=result.finished_at,
                    status=result.status,
                    expires_at=result.finished_at + timedelta(days=90),
                    payload=report,
                )
                .on_conflict_do_nothing(index_elements=[runs.c.id])
            )
            for item in result.selected:
                if item.kind == "official" and not item.summary_ko:
                    raise NewsError("summary_required")
                conn.execute(
                    insert(items)
                    .values(
                        id=item_id(item),
                        provider=item.provider,
                        source_id=item.source_id,
                        content_version=item.content_version,
                        published_at=item.published_at,
                        retrieved_at=item.retrieved_at,
                        first_stored_at=now,
                        expires_at=now + timedelta(days=90),
                        identity_keys=list(item.keys),
                        payload=item.metadata(),
                    )
                    .on_conflict_do_nothing(index_elements=[items.c.id])
                )
        return tuple(item_id(i) for i in result.selected)

    def record_delivery(self, item, *, recipient_scope, status, message_id=None, now):
        """T06 성공/실패/불명 결과용. unknown/confirmed를 후속 호출로 덮어쓰지 않는다."""
        now = aware(now)
        if (
            status not in {"confirmed", "failed", "unknown"}
            or not recipient_scope
            or (status == "confirmed") != bool(message_id)
        ):
            raise NewsError("delivery_result_invalid")
        key = digest(recipient_scope + ":" + item_id(item))
        with self.engine.begin() as conn:
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
                or not stored["first_stored_at"] <= now < stored["expires_at"]
            ):
                raise NewsError("item_missing_or_expired")
            existing = (
                conn.execute(sa.select(deliveries).where(deliveries.c.id == key))
                .mappings()
                .one_or_none()
            )
            if existing:
                if (
                    existing["status"] == status
                    and existing["message_id"] == message_id
                ):
                    return False
                raise NewsError("delivery_result_conflict")
            conn.execute(
                deliveries.insert().values(
                    id=key,
                    item_id=item_id(item),
                    recipient_scope=recipient_scope,
                    status=status,
                    message_id=message_id,
                    recorded_at=now,
                )
            )
        return True

    def purge_expired(self, *, now):
        now = aware(now)
        with self.engine.begin() as conn:
            count = conn.execute(
                items.delete().where(items.c.expires_at <= now)
            ).rowcount
            conn.execute(runs.delete().where(runs.c.expires_at <= now))
        return count
