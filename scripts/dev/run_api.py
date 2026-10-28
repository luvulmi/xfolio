"""로컬 HTTPS proxy용 API 시작. 기존 Google 설정 재사용은 명시 옵션만 허용한다."""

import argparse
import secrets
import tomllib
from pathlib import Path
from urllib.parse import urlsplit

import uvicorn

from xfolio.api.app import create_app
from xfolio.api.auth import Settings

ROOT = Path(__file__).resolve().parents[2]


def development_settings(origin, use_streamlit_auth=False, secrets_path=None):
    settings = Settings.from_env()
    parts = urlsplit(origin)
    if (
        parts.scheme != "https"
        or parts.hostname not in {"localhost", "127.0.0.1"}
        or parts.username
        or parts.password
        or parts.path
        or parts.query
        or parts.fragment
    ):
        raise ValueError("local_https_origin_required")
    if not settings.database_url:
        raise ValueError("explicit_isolated_api_database_url_required")
    overrides = {
        "origin": origin,
        "cursor_secret": settings.cursor_secret or secrets.token_urlsafe(48),
    }
    if use_streamlit_auth:
        with Path(secrets_path or ROOT / ".streamlit" / "secrets.toml").open(
            "rb"
        ) as stream:
            data = tomllib.load(stream)
        auth = data.get("auth", {})
        admins = data.get("XFOLIO_ADMIN_EMAILS", [])
        if isinstance(admins, str):
            admins = [value.strip() for value in admins.split(",") if value.strip()]
        if not isinstance(admins, list) or not all(
            isinstance(value, str) for value in admins
        ):
            raise ValueError("invalid_operator_allowlist")
        overrides.update(
            google_client_id=auth.get("client_id", ""),
            google_client_secret=auth.get("client_secret", ""),
            allowed_emails=tuple(admins),
        )
    settings = Settings.model_validate({**settings.model_dump(), **overrides})
    if not settings.auth_ready:
        raise ValueError("google_auth_configuration_required")
    return settings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origin", default="https://localhost:8443")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--use-streamlit-auth", action="store_true")
    args = parser.parse_args()
    try:
        settings = development_settings(args.origin, args.use_streamlit_auth)
    except (OSError, ValueError, tomllib.TOMLDecodeError):
        parser.exit(
            2,
            "로컬 API 설정이 부족합니다. 격리 DB·Google 설정·HTTPS origin을 확인하세요.\n",
        )
    # 키·허용 운영자·DB URL을 출력하거나 새 파일로 저장하지 않는다.
    uvicorn.run(
        create_app(settings),
        host="127.0.0.1",
        port=args.port,
        proxy_headers=True,
        forwarded_allow_ips="127.0.0.1",
        access_log=False,
    )


if __name__ == "__main__":
    main()
