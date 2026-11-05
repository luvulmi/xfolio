"""PostgreSQL DDL 정적 계약. 실제 실행/잠금 시험은 별도다."""

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from xfolio.db.schema import metadata, publication_posts


def test_eight_operational_tables_and_postgresql_ddl():
    assert len(metadata.tables) == 8
    assert "preview_drafts" not in metadata.tables
    for table in metadata.sorted_tables:
        ddl = str(CreateTable(table).compile(dialect=postgresql.dialect()))
        assert "CREATE TABLE" in ddl
    indexes = "\n".join(
        str(CreateIndex(i).compile(dialect=postgresql.dialect()))
        for i in publication_posts.indexes
    )
    assert (
        "UNIQUE INDEX uq_active_event_claim" in indexes
        and "WHERE active_claim IS true" in indexes
    )
