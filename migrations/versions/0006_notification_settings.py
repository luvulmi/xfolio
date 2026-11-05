"""공용 알림 설정·변경 감사. 실제 자동운영 활성화와 구분."""

from datetime import UTC, datetime
from pathlib import Path
from runpy import run_path

from alembic import op

schema = run_path(str(Path(__file__).parents[1] / "schema_0006.py"))
revision = "0006_notification_settings"
down_revision = "0005_morning_newsletter"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    schema["metadata"].create_all(conn, checkfirst=False)
    conn.execute(
        schema["settings"]
        .insert()
        .values(
            id=1,
            revision=1,
            morning_enabled=True,
            paused=False,
            intraday_enabled=False,
            close_enabled=False,
            updated_at=datetime.now(UTC),
        )
    )


def downgrade():
    schema["metadata"].drop_all(op.get_bind(), checkfirst=False)
