"""Offline checks for the public master identity probe; no quote claims."""

import io
import runpy
import zipfile
from pathlib import Path

import pytest

PROBE = runpy.run_path(
    str(Path(__file__).resolve().parents[1] / "scripts/experiments/kis_market_probe.py")
)


def master_zip(codes):
    rows = "".join(f"{code:<9}KR{code}0000{'ETF':<12}{'0' * 227}\n" for code in codes)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("kospi_code.mst", rows.encode("cp949"))
    return buffer.getvalue()


def test_selects_only_three_requested_codes():
    rows = PROBE["select_rows"](master_zip(["005930", "360750", "379810", "458730"]))
    assert [row["code"] for row in rows] == ["360750", "379810", "458730"]
    assert all(row["name"] == "ETF" for row in rows)


@pytest.mark.parametrize(
    "codes", [["360750"], ["360750", "379810", "458730", "458730"]]
)
def test_missing_or_duplicate_identity_is_rejected(codes):
    with pytest.raises(ValueError, match="exactly three"):
        PROBE["select_rows"](master_zip(codes))
