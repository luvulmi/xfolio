"""국내 ETF 종목·설정 버전·원종가90일. 기존 AM/PM 제약은 보존한다."""

from pathlib import Path
from runpy import run_path

from alembic import op

snapshot = run_path(str(Path(__file__).parents[1] / "schema_0003.py"))
metadata = snapshot["metadata"]
revision = "0003_domestic_market"
down_revision = "0002_am_four_posts"
branch_labels = None
depends_on = None


def upgrade():
    metadata.create_all(op.get_bind(), checkfirst=False)
    for name in (
        "WATCHLIST_FUNCTION",
        "WATCHLIST_AUDIT_FUNCTION",
        "PRICE_FUNCTION",
        "INSTRUMENT_FUNCTION",
    ):
        op.execute(snapshot[name])
    op.execute(
        "CREATE TRIGGER validate_watchlist BEFORE INSERT OR UPDATE ON domestic_watchlist FOR EACH ROW EXECUTE FUNCTION validate_domestic_watchlist()"
    )
    op.execute(
        "CREATE TRIGGER audit_watchlist AFTER INSERT OR UPDATE ON domestic_watchlist FOR EACH ROW EXECUTE FUNCTION audit_domestic_watchlist()"
    )
    op.execute(
        "CREATE TRIGGER immutable_price BEFORE UPDATE ON domestic_price_snapshots FOR EACH ROW EXECUTE FUNCTION immutable_domestic_price()"
    )
    op.execute(
        "CREATE TRIGGER guard_instrument BEFORE UPDATE OR DELETE ON domestic_instruments FOR EACH ROW EXECUTE FUNCTION guard_domestic_instrument()"
    )


def downgrade():
    metadata.drop_all(op.get_bind(), checkfirst=False)
    for name in (
        "validate_domestic_watchlist",
        "audit_domestic_watchlist",
        "immutable_domestic_price",
        "guard_domestic_instrument",
    ):
        op.execute("DROP FUNCTION " + name + "()")
