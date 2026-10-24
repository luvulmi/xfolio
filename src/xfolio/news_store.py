"""허용된 BLS 텍스트와 수집 메타데이터를 저장한다. 게시 상태와 독립이다."""

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

from xfolio.news_contracts import CollectionRun, EvidenceBundle
from xfolio.storage import DEFAULT_DB


class NewsStore:
    def __init__(self, path: Path | str = DEFAULT_DB):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS news_cursors (
                    cursor_key TEXT PRIMARY KEY, completed_until TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS collection_runs (
                    run_id TEXT PRIMARY KEY, payload TEXT NOT NULL,
                    cursor_after TEXT, checkpoint_result TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS evidence_bundles (
                    source_id TEXT NOT NULL, content_version TEXT NOT NULL,
                    event_key TEXT NOT NULL, fact_version TEXT NOT NULL,
                    payload TEXT NOT NULL, PRIMARY KEY(source_id, content_version));
            """)

    def connect(self):
        return sqlite3.connect(self.path, timeout=5)

    def cursor(self, provider, query_version, scope):
        key = json.dumps([provider, query_version, scope])
        with self.connect() as db:
            row = db.execute(
                "SELECT completed_until FROM news_cursors WHERE cursor_key=?", (key,)
            ).fetchone()
        return datetime.fromisoformat(row[0]) if row else None

    def finish(self, run: CollectionRun) -> str:
        run = CollectionRun.model_validate_json(run.model_dump_json())
        payload = run.model_dump_json()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute(
                "SELECT payload, checkpoint_result FROM collection_runs WHERE run_id=?",
                (run.run_id,),
            ).fetchone()
            if previous:
                if previous[0] != payload:
                    raise ValueError("run_id_conflict")
                return previous[1]
            row = db.execute(
                "SELECT completed_until FROM news_cursors WHERE cursor_key=?",
                (run.cursor_key,),
            ).fetchone()
            cursor = datetime.fromisoformat(row[0]) if row else None
            result = "not_complete"
            if run.status == "complete":
                if cursor != run.cursor_before:
                    result = "stale_cursor"
                elif cursor and run.window_start > cursor:
                    result = "gap_requires_recovery"
                elif cursor and run.window_end <= cursor:
                    result = "already_covered"
                else:
                    result = "advanced"
                    db.execute(
                        "INSERT INTO news_cursors VALUES (?,?) ON CONFLICT(cursor_key) DO UPDATE SET completed_until=excluded.completed_until",
                        (run.cursor_key, run.end_utc),
                    )
                    cursor = run.window_end
            db.execute(
                "INSERT INTO collection_runs VALUES (?,?,?,?)",
                (
                    run.run_id,
                    payload,
                    cursor.astimezone(UTC).isoformat() if cursor else None,
                    result,
                ),
            )
        return result

    def save_evidence(self, bundle: EvidenceBundle) -> str:
        bundle = EvidenceBundle.model_validate_json(bundle.model_dump_json())
        source, event = bundle.source, bundle.event
        url = urlsplit(source.source_url)
        if (
            source.provider != "BLS"
            or source.permission_scope != "bls_public_text"
            or url.hostname != "www.bls.gov"
            or not url.path.startswith("/news.release/")
        ):
            raise ValueError("evidence_storage_not_permitted")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute(
                "SELECT fact_version FROM evidence_bundles WHERE event_key=? ORDER BY rowid DESC",
                (event.event_key,),
            ).fetchall()
            result = (
                "new_event"
                if not rows
                else (
                    "same_claims_new_source_review_required"
                    if event.fact_version in {r[0] for r in rows}
                    else "changed_fact_review_required"
                )
            )
            if rows:
                event = event.model_copy(update={"prior_event_version": rows[0][0]})
                bundle = bundle.model_copy(update={"event": event})
            changed = db.execute(
                "INSERT OR IGNORE INTO evidence_bundles VALUES (?,?,?,?,?)",
                (
                    source.source_id,
                    source.content_version,
                    event.event_key,
                    event.fact_version,
                    bundle.model_dump_json(),
                ),
            ).rowcount
        return result if changed else "same_source_version"
