"""가상 자료 클라우드 저장 시험. 기본은 무통신이며 유료 API·게시를 호출하지 않는다."""

import argparse
import json
import math
import os
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path

from xfolio.demo import demo_preview
from xfolio.storage import StorageError, configured_store


def operator_allowed(
    claims: Mapping, allowed_emails: Sequence[str], *, now: datetime | None = None
) -> bool:
    """OIDC 인증과 별도로 Google의 허용 운영자·만료를 확인한다."""
    email, expiry, issuer = claims.get("email"), claims.get("exp"), claims.get("iss")
    if (
        not isinstance(issuer, str)
        or issuer not in {"https://accounts.google.com", "accounts.google.com"}
        or claims.get("email_verified") is not True
        or not isinstance(claims.get("sub"), str)
        or not claims["sub"]
        or not isinstance(email, str)
        or type(expiry) not in (int, float)
        or not math.isfinite(expiry)
    ):
        return False
    timestamp = (now or datetime.now(UTC)).timestamp()
    return expiry > timestamp and email.casefold() in {
        value.strip().casefold() for value in allowed_emails if isinstance(value, str)
    }


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run", action="store_true", help="실제 PostgreSQL에 가상 자료 저장"
    )
    parser.add_argument(
        "--initialize", action="store_true", help="가상 시험 schema 생성"
    )
    parser.add_argument("--migrate-sqlite", type=Path, help="가상 SQLite 원본 복사")
    args = parser.parse_args(argv)
    if not args.run:
        print(
            json.dumps(
                {"mode": "dry_run", "database_requests": 0, "can_publish": False}
            )
        )
        return
    if not os.environ.get("XFOLIO_DATABASE_URL", "").strip():
        parser.exit(2, "XFOLIO_DATABASE_URL 설정이 필요합니다.\n")
    try:
        store = configured_store()
        if args.initialize:
            store.initialize()
        migration = (
            store.migrate_sqlite(args.migrate_sqlite) if args.migrate_sqlite else None
        )
        preview = demo_preview()
        inserted = store.save(preview)
        if store.get(preview.preview_id) != preview:
            raise StorageError("저장한 가상 버전을 다시 조회하지 못했습니다.")
        if store.save(preview):
            raise StorageError("중복 버전이 다시 저장됐습니다.")
    except StorageError:
        parser.exit(1, "클라우드 DB 시험 실패: 접속·TLS·schema·권한을 확인하세요.\n")
    except (OSError, ValueError):
        parser.exit(2, "클라우드 DB 시험의 설정·가상 자료를 확인하세요.\n")
    print(
        json.dumps(
            {
                "mode": "run",
                "observed_at_utc": datetime.now(UTC).isoformat(),
                "status": "passed",
                "synthetic": True,
                "can_publish": False,
                "inserted": inserted,
                "roundtrip": True,
                "deduplicated": True,
                "migration": migration,
            }
        )
    )


if __name__ == "__main__":
    main()
