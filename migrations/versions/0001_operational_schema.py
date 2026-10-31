"""8개 운영 테이블. 기존 가상 preview_drafts를 변경하지 않는다."""

from pathlib import Path
from runpy import run_path

from alembic import op

# 당시 DDL snapshot. 현재 metadata 변경이 이미 배포된 0001의 의미를 바꾸지 않는다.
metadata = run_path(str(Path(__file__).parents[1] / "schema_0001.py"))["metadata"]

revision = "0001_operational_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    metadata.create_all(op.get_bind(), checkfirst=False)
    op.execute("""CREATE FUNCTION reject_draft_update() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN RAISE EXCEPTION 'content_drafts versions are immutable'; END; $$""")
    op.execute("""CREATE TRIGGER immutable_content_drafts BEFORE UPDATE ON content_drafts
    FOR EACH ROW EXECUTE FUNCTION reject_draft_update()""")


def downgrade():
    op.execute("DROP TRIGGER immutable_content_drafts ON content_drafts")
    op.execute("DROP FUNCTION reject_draft_update()")
    metadata.drop_all(op.get_bind(), checkfirst=False)
