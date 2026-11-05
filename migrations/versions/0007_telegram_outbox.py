"""Telegram outbox·조각별 시도. 가격 본문과 비밀을 저장하지 않는다."""

from pathlib import Path
from runpy import run_path

from alembic import op

schema = run_path(str(Path(__file__).parents[1] / "schema_0007.py"))
revision = "0007_telegram_outbox"
down_revision = "0006_notification_settings"
branch_labels = None
depends_on = None


def upgrade():
    schema["metadata"].create_all(op.get_bind(), checkfirst=False)


def downgrade():
    schema["metadata"].drop_all(op.get_bind(), checkfirst=False)
