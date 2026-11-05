import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from tests.support.am_fixtures import NOW, inputs
from tests.support.am_fixtures import (
    am_store as am_store,  # noqa: PLC0414 - 격리 fixture
)
from tests.support.paths import ROOT
from xfolio.db.schema import publication_jobs, publication_posts
from xfolio.legacy.am_edition import save_am_edition


def config(conn):
    result = Config(str(ROOT / "alembic.ini"))
    result.set_main_option("script_location", str(ROOT / "migrations"))
    result.attributes["connection"] = conn
    return result


def constraints(conn, table):
    return " ".join(c["sqltext"] for c in sa.inspect(conn).get_check_constraints(table))


def test_initial_ddl_snapshot_stays_three_then_new_migration_adds_four(am_store):
    with am_store.engine.begin() as conn:
        command.downgrade(config(conn), "base")
        command.upgrade(config(conn), "0001_operational_schema")
        assert "3" in constraints(conn, "publication_posts")
        assert "4" not in constraints(conn, "publication_posts")
        command.upgrade(config(conn), "head")
        assert "4" in constraints(conn, "publication_posts")
        command.downgrade(config(conn), "0001_operational_schema")
        assert "4" not in constraints(conn, "publication_posts")
        command.upgrade(config(conn), "head")


def test_fourth_position_and_reservation_are_allowed_but_fifth_is_not(am_store):
    job = save_am_edition(
        am_store.engine, inputs(), account_id="migration-test", now=NOW
    )
    with am_store.engine.begin() as conn:
        conn.execute(
            publication_jobs.update()
            .where(publication_jobs.c.id == job)
            .values(reserved_count=4)
        )
        conn.execute(
            publication_posts.insert().values(
                id="four",
                job_id=job,
                account_id="migration-test",
                position=4,
                content_version=1,
                state="reserved",
                active_claim=False,
                payload={},
            )
        )
    for table, values in (
        (publication_jobs, {"reserved_count": 5}),
        (publication_posts, {"position": 5}),
    ):
        with pytest.raises(sa.exc.IntegrityError), am_store.engine.begin() as conn:
            conn.execute(table.update().values(**values))
    with pytest.raises(sa.exc.IntegrityError), am_store.engine.begin() as conn:
        command.downgrade(config(conn), "0001_operational_schema")
    with am_store.engine.connect() as conn:
        assert "4" in constraints(conn, "publication_posts")
