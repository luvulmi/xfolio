"""가상 dry_run 미리보기만 보존하는 로컬 SQLite 저장소."""

import os
import sqlite3
from pathlib import Path
from typing import Protocol

from xfolio.compose import MorningPreview

DEFAULT_DB = Path(__file__).resolve().parents[2] / "data" / "xfolio.sqlite3"


class StorageError(RuntimeError):
    """접속 정보·드라이버 오류 원문을 노출하지 않는 저장 오류."""


class PreviewRepository(Protocol):
    def save(self, preview: MorningPreview) -> bool: ...

    def recent(self, limit: int = 10) -> list[MorningPreview]: ...


def configured_store(path: Path | str | None = None) -> PreviewRepository:
    """명시 경로는 로컬, 환경 URL이 있으면 원격. 연결 실패 시 대체하지 않는다."""
    if path is not None:
        return PreviewStore(path)
    url = os.environ.get("XFOLIO_DATABASE_URL", "").strip()
    if url:
        try:
            from xfolio.postgres import PostgresPreviewStore
        except ImportError:
            raise StorageError("PostgreSQL 선택 의존성 cloud를 설치하세요.") from None
        return PostgresPreviewStore(url)
    return PreviewStore()


class PreviewStore:
    def __init__(self, path: Path | str = DEFAULT_DB):
        self.path = Path(path)

    def save(self, preview: MorningPreview) -> bool:
        # 모델이 dry_run·synthetic·can_publish=False만 허용한다.
        preview = MorningPreview.model_validate_json(preview.model_dump_json())
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path, timeout=5) as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS preview_drafts ("
                "preview_id TEXT PRIMARY KEY, prepared_at TEXT NOT NULL, "
                "payload TEXT NOT NULL)"
            )
            changed = connection.execute(
                "INSERT OR IGNORE INTO preview_drafts VALUES (?, ?, ?)",
                (
                    preview.preview_id,
                    preview.prepared_at.isoformat(),
                    preview.model_dump_json(),
                ),
            ).rowcount
        return changed == 1

    def recent(self, limit: int = 10) -> list[MorningPreview]:
        if not 1 <= limit <= 100:
            raise ValueError("조회 개수는1~100이어야 합니다.")
        if not self.path.exists():
            return []
        with sqlite3.connect(self.path, timeout=5) as connection:
            exists = connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name='preview_drafts'"
            ).fetchone()
            if not exists:
                return []
            rows = connection.execute(
                "SELECT payload FROM preview_drafts ORDER BY prepared_at DESC, "
                "preview_id LIMIT ?",
                (limit,),
            ).fetchall()
        return [MorningPreview.model_validate_json(row[0]) for row in rows]
