"""AM 4글 제약. 기존 PM 이력과 초기 0001 DDL을 보존한다."""

import sqlalchemy as sa
from alembic import op

revision = "0002_am_four_posts"
down_revision = "0001_operational_schema"
branch_labels = None
depends_on = None


def _replace(table, token, name, expression):
    constraints = [
        c
        for c in sa.inspect(op.get_bind()).get_check_constraints(table)
        if token in c["sqltext"]
    ]
    if len(constraints) != 1:
        raise RuntimeError("unexpected_publication_constraint")
    op.drop_constraint(constraints[0]["name"], table, type_="check")
    op.create_check_constraint(name, table, expression)


def upgrade():
    _replace(
        "publication_jobs",
        "reserved_count",
        "ck_jobs_reservation",
        "decision_revision >= 0 AND reserved_count BETWEEN 0 AND 4",
    )
    _replace(
        "publication_posts", "position", "ck_posts_position", "position BETWEEN 1 AND 4"
    )


def downgrade():
    # 4번째 기존 행이 있으면 이전 제약 적용에 실패하고 전체 트랜잭션을 되돌린다.
    _replace(
        "publication_jobs",
        "reserved_count",
        "ck_jobs_reservation",
        "decision_revision >= 0 AND reserved_count BETWEEN 0 AND 3",
    )
    _replace(
        "publication_posts", "position", "ck_posts_position", "position BETWEEN 1 AND 3"
    )
