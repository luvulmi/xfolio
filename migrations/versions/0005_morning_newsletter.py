"""자동 아침 뉴스레터 편성. 기존 승인/뉴스/가격 계약 보존."""

from pathlib import Path
from runpy import run_path

from alembic import op

schema = run_path(str(Path(__file__).parents[1] / "schema_0005.py"))
revision = "0005_morning_newsletter"
down_revision = "0004_newsletter_news"
branch_labels = None
depends_on = None


def upgrade():
    schema["metadata"].create_all(op.get_bind(), checkfirst=False)
    op.execute(schema["IMMUTABLE_FUNCTION"])
    op.execute(
        "CREATE TRIGGER guard_newsletter_edition BEFORE UPDATE ON newsletter_editions FOR EACH ROW EXECUTE FUNCTION immutable_newsletter_edition()"
    )


def downgrade():
    schema["metadata"].drop_all(op.get_bind(), checkfirst=False)
    op.execute("DROP FUNCTION immutable_newsletter_edition()")
