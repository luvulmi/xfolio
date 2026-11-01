"""Inspect public KIS KOSPI master rows; never request accounts or place orders."""

import hashlib
import io
import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import urlopen

URL = "https://new.real.download.dws.co.kr/common/master/kospi_code.mst.zip"
CODES = {"360750", "379810", "458730"}
OUTPUT_BASE = Path("tasks/verification/assets/market")


def select_rows(payload: bytes) -> list[dict[str, str]]:
    """Follow the official parser's 228-character fixed-width suffix contract."""
    selected = []
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        content = archive.read("kospi_code.mst").decode("cp949")
    for line in content.splitlines(keepends=True):
        identity = line[:-228]
        code = identity[:9].strip()
        if code in CODES:
            selected.append(
                {"code": code, "isin": identity[9:21], "name": identity[21:].strip()}
            )
    if {row["code"] for row in selected} != CODES or len(selected) != len(CODES):
        raise ValueError("Expected exactly three unique ETF master rows")
    return selected


def main() -> None:
    with urlopen(URL, timeout=30) as response:
        payload = response.read()
    rows = select_rows(payload)
    output = OUTPUT_BASE / datetime.now(UTC).strftime("kis_%Y-%m-%dT%H%M%S%fZ")
    output.mkdir(parents=True, exist_ok=False)
    result = {
        "source": URL,
        "retrieved_at": datetime.now(UTC).isoformat(),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "kind": "public_master_identity_only",
        "authenticated_quotes_verified": False,
        "rows": rows,
    }
    (output / "selected_master.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=True))


if __name__ == "__main__":
    main()
