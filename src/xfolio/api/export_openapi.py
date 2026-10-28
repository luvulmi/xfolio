"""현재 API의 OpenAPI를 통신 없이 저장한다."""

import json
from pathlib import Path

from xfolio.api.app import create_app
from xfolio.api.auth import Settings


def main():
    path = Path("contracts/openapi.json")
    path.parent.mkdir(exist_ok=True)
    path.write_text(
        json.dumps(create_app(Settings()).openapi(), ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
