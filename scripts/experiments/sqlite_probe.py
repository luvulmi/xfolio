"""Disposable SQLite capability probe; never reads application data or calls APIs."""

import json
import platform
import sqlite3
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path


def check(condition: bool, label: str) -> None:
    if not condition:
        raise AssertionError(label)


def run_probe() -> dict:
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="xfolio_sqlite_probe_") as directory:
        database = Path(directory) / "probe.db"
        with closing(sqlite3.connect(database)) as setup:
            setup.execute("PRAGMA journal_mode=WAL")
            setup.executescript(
                "CREATE TABLE publication (event_key TEXT PRIMARY KEY, post_id TEXT);"
                "CREATE TABLE candidate (id INTEGER PRIMARY KEY, version INTEGER, "
                "approved_version INTEGER);"
                "INSERT INTO candidate VALUES (1, 2, NULL);"
            )
            setup.commit()

        barrier = threading.Barrier(2)

        def reserve(_worker: int) -> str:
            with closing(sqlite3.connect(database, timeout=5)) as connection:
                barrier.wait(timeout=5)
                try:
                    with connection:
                        connection.execute(
                            "INSERT INTO publication VALUES (?, ?)",
                            ("example_event", "fake_post_id"),
                        )
                except sqlite3.IntegrityError:
                    return "duplicate_rejected"
                return "reserved"

        with ThreadPoolExecutor(max_workers=2) as executor:
            reservations = sorted(executor.map(reserve, range(2)))
        check(reservations == ["duplicate_rejected", "reserved"], "unique reservation")

        with closing(sqlite3.connect(database)) as connection:
            stale = connection.execute(
                "UPDATE candidate SET approved_version=? "
                "WHERE id=1 AND version=? AND approved_version IS NULL",
                (1, 1),
            ).rowcount
            valid = connection.execute(
                "UPDATE candidate SET approved_version=? "
                "WHERE id=1 AND version=? AND approved_version IS NULL",
                (2, 2),
            ).rowcount
            repeated = connection.execute(
                "UPDATE candidate SET approved_version=? "
                "WHERE id=1 AND version=? AND approved_version IS NULL",
                (2, 2),
            ).rowcount
            connection.commit()
            check((stale, valid, repeated) == (0, 1, 0), "approval version CAS")

            try:
                with connection:
                    connection.execute("UPDATE candidate SET version=99 WHERE id=1")
                    connection.execute(
                        "INSERT INTO publication VALUES ('rollback', NULL)"
                    )
                    raise RuntimeError("intentional transaction failure")
            except RuntimeError:
                pass
            check(
                connection.execute("SELECT version FROM candidate").fetchone() == (2,)
                and connection.execute(
                    "SELECT COUNT(*) FROM publication WHERE event_key='rollback'"
                ).fetchone()
                == (0,),
                "transaction rollback",
            )

            backup_path = Path(directory) / "backup.db"
            restored_path = Path(directory) / "restored.db"
            with closing(sqlite3.connect(backup_path)) as backup:
                connection.backup(backup)
                connection.execute(
                    "UPDATE candidate SET version=3, approved_version=NULL"
                )
                connection.commit()
                with closing(sqlite3.connect(restored_path)) as restored:
                    backup.backup(restored)
            with closing(sqlite3.connect(restored_path)) as restored:
                check(
                    restored.execute("PRAGMA integrity_check").fetchone() == ("ok",)
                    and restored.execute("SELECT * FROM candidate").fetchall()
                    == [(1, 2, 2)]
                    and restored.execute("SELECT * FROM publication").fetchall()
                    == [("example_event", "fake_post_id")],
                    "backup restore snapshot",
                )

    return {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "sqlite": sqlite3.sqlite_version,
        "mode": "WAL, two threads with independent connections",
        "unique_reservation": reservations,
        "approval_rows_stale_valid_repeat": [stale, valid, repeated],
        "rollback": "passed",
        "backup_restore_integrity": "passed",
        "temporary_directory_cleaned": True,
        "elapsed_seconds": round(time.perf_counter() - started, 4),
    }


if __name__ == "__main__":
    print(json.dumps(run_probe(), indent=2))
