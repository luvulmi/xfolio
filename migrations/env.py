"""명시적 URL만 사용한다. .env 또는 기존 preview DB 설정을 자동 읽지 않는다."""

import os

from alembic import context
from sqlalchemy import create_engine

from xfolio.db.schema import metadata

connection = context.config.attributes.get("connection")
url = os.environ.get("XFOLIO_MIGRATION_DATABASE_URL", "")
if connection is not None:
    context.configure(connection=connection, target_metadata=metadata)
    with context.begin_transaction():
        context.run_migrations()
elif context.is_offline_mode():
    if not url.startswith(("postgresql://", "postgresql+psycopg://")):
        raise ValueError("XFOLIO_MIGRATION_DATABASE_URL PostgreSQL URL required")
    url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    context.configure(url=url, target_metadata=metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    if not url.startswith(("postgresql://", "postgresql+psycopg://")):
        raise ValueError("XFOLIO_MIGRATION_DATABASE_URL PostgreSQL URL required")
    url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    with create_engine(url, hide_parameters=True).connect() as connection:
        context.configure(connection=connection, target_metadata=metadata)
        with context.begin_transaction():
            context.run_migrations()
