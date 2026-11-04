"""개인 뉴스 수집·메타데이터·성공 전달 이력. 기존 X/국내 가격 계약 보존."""

from pathlib import Path
from runpy import run_path

from alembic import op

metadata = run_path(str(Path(__file__).parents[1] / "schema_0004.py"))["metadata"]
revision = "0004_newsletter_news"
down_revision = "0003_domestic_market"
branch_labels = None
depends_on = None


def upgrade():
    metadata.create_all(op.get_bind(), checkfirst=False)


def downgrade():
    metadata.drop_all(op.get_bind(), checkfirst=False)
