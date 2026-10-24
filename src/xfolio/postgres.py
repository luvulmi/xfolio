"""가상 미리보기 PostgreSQL 저장소. 실제 승인·발행 원장과 구분한다."""

import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path

import certifi
import psycopg

from xfolio.compose import MorningPreview
from xfolio.storage import StorageError

SCHEMA = """
CREATE TABLE IF NOT EXISTS preview_drafts (
    preview_id TEXT PRIMARY KEY,
    prepared_at TIMESTAMPTZ NOT NULL,
    payload TEXT NOT NULL
)
"""
INSERT = """
INSERT INTO preview_drafts (preview_id, prepared_at, payload)
VALUES (%s, %s, %s) ON CONFLICT (preview_id) DO NOTHING
"""


class PostgresPreviewStore:
    def __init__(self, url: str):
        if not url.strip():
            raise ValueError("PostgreSQL 접속 설정이 필요합니다.")
        self._url = url

    @contextmanager
    def _connect(self):
        with psycopg.connect(
            self._url,
            connect_timeout=10,
            sslmode="verify-full",
            sslrootcert=certifi.where(),
        ) as connection:
            # Neon pooler는 startup options를 허용하지 않아 트랜잭션 안에서 제한한다.
            connection.execute("SET LOCAL statement_timeout = 10000")
            connection.execute("SET LOCAL lock_timeout = 5000")
            yield connection

    def initialize(self) -> None:
        """DDL 권한이 있는 계정으로 별도 실행한다."""
        try:
            with self._connect() as connection:
                connection.execute(SCHEMA)
        except psycopg.Error:
            raise StorageError("PostgreSQL 초기화에 실패했습니다.") from None

    @staticmethod
    def _insert(connection, preview: MorningPreview) -> bool:
        return (
            connection.execute(
                INSERT,
                (
                    preview.preview_id,
                    preview.prepared_at,
                    preview.model_dump_json(),
                ),
            ).rowcount
            == 1
        )

    def save(self, preview: MorningPreview) -> bool:
        preview = MorningPreview.model_validate_json(preview.model_dump_json())
        try:
            with self._connect() as connection:
                return self._insert(connection, preview)
        except psycopg.Error:
            raise StorageError("PostgreSQL 저장에 실패했습니다.") from None

    def get(self, preview_id: str) -> MorningPreview | None:
        try:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT payload FROM preview_drafts WHERE preview_id = %s",
                    (preview_id,),
                ).fetchone()
        except psycopg.Error:
            raise StorageError("PostgreSQL 버전 조회에 실패했습니다.") from None
        return MorningPreview.model_validate_json(row[0]) if row else None

    def recent(self, limit: int = 10) -> list[MorningPreview]:
        if not 1 <= limit <= 100:
            raise ValueError("조회 개수는1~100이어야 합니다.")
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    "SELECT payload FROM preview_drafts "
                    "ORDER BY prepared_at DESC, preview_id LIMIT %s",
                    (limit,),
                ).fetchall()
        except psycopg.Error:
            raise StorageError("PostgreSQL 조회에 실패했습니다.") from None
        return [MorningPreview.model_validate_json(row[0]) for row in rows]

    def migrate_sqlite(self, source: Path) -> dict[str, int]:
        """원본은 읽기 전용, 대상은 전부 성공하거나 전부 롤백한다."""
        try:
            with closing(
                sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)
            ) as connection:
                rows = connection.execute(
                    "SELECT payload FROM preview_drafts ORDER BY prepared_at, preview_id"
                ).fetchall()
        except sqlite3.Error:
            raise StorageError("SQLite 원본을 읽지 못했습니다.") from None
        previews = [MorningPreview.model_validate_json(row[0]) for row in rows]
        try:
            with self._connect() as connection:
                added = sum(self._insert(connection, preview) for preview in previews)
        except psycopg.Error:
            raise StorageError("이전 실패로 PostgreSQL 복사를 롤백했습니다.") from None
        return {"source_rows": len(previews), "inserted": added}
