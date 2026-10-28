"""Google OIDC 검증·서버 측 세션. 기본 설정에서는 인증을 열지 않는다."""

import os
import secrets
from datetime import timedelta
from urllib.parse import urlsplit

import httpx
from authlib.integrations.httpx_client import AsyncOAuth2Client
from authlib.jose import JsonWebKey, jwt
from pydantic import BaseModel

from xfolio.api.store import ApiError
from xfolio.cloud import operator_allowed


class Settings(BaseModel):
    origin: str = "https://localhost:8443"
    database_url: str = ""
    google_client_id: str = ""
    google_client_secret: str = ""
    allowed_emails: tuple[str, ...] = ()
    cursor_secret: str = ""
    mode: str = "dry_run"

    @classmethod
    def from_env(cls):
        return cls(
            origin=os.environ.get(
                "XFOLIO_PUBLIC_ORIGIN", "https://localhost:8443"
            ).rstrip("/"),
            database_url=os.environ.get("XFOLIO_API_DATABASE_URL", ""),
            google_client_id=os.environ.get("XFOLIO_GOOGLE_CLIENT_ID", ""),
            google_client_secret=os.environ.get("XFOLIO_GOOGLE_CLIENT_SECRET", ""),
            allowed_emails=tuple(
                filter(
                    None,
                    (
                        s.strip().casefold()
                        for s in os.environ.get("XFOLIO_ALLOWED_EMAILS", "").split(",")
                    ),
                )
            ),
            cursor_secret=os.environ.get("XFOLIO_API_CURSOR_SECRET", ""),
            mode=os.environ.get("XFOLIO_MODE", "dry_run"),
        )

    @property
    def auth_ready(self):
        origin = urlsplit(self.origin)
        return bool(
            self.google_client_id
            and self.google_client_secret
            and self.allowed_emails
            and origin.scheme == "https"
            and origin.hostname
            and not origin.username
            and not origin.password
            and not origin.path
            and not origin.query
            and not origin.fragment
            and len(self.cursor_secret) >= 32
            and self.mode in {"dry_run", "reviewed", "auto"}
        )


class GoogleProvider:
    def __init__(self, settings):
        self.settings = settings

    def client(self):
        return AsyncOAuth2Client(
            self.settings.google_client_id,
            self.settings.google_client_secret,
            scope="openid email profile",
            redirect_uri=self.settings.origin + "/api/auth/callback",
        )

    async def authorize(self, state, nonce):
        async with self.client() as client:
            url, _ = client.create_authorization_url(
                "https://accounts.google.com/o/oauth2/v2/auth",
                state=state,
                nonce=nonce,
            )
            return url

    async def verify(self, code, nonce, now):
        async with self.client() as client:
            token = await client.fetch_token(
                "https://oauth2.googleapis.com/token", code=code
            )
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get("https://www.googleapis.com/oauth2/v3/certs")
            response.raise_for_status()
            keys = JsonWebKey.import_key_set(response.json())
        claims = jwt.decode(
            token["id_token"],
            keys,
            claims_options={
                "iss": {
                    "essential": True,
                    "values": ["https://accounts.google.com", "accounts.google.com"],
                },
                "aud": {"essential": True, "value": self.settings.google_client_id},
                "exp": {"essential": True},
                "nonce": {"essential": True, "value": nonce},
            },
        )
        claims.validate(now=int(now.timestamp()), leeway=30)
        # Restrict the signature algorithm as well as signature/issuer/audience/nonce.
        if claims.header.get("alg") != "RS256":
            raise ApiError("AUTH_FAILED", 403)
        return dict(claims)


def new_session(store, settings, claims, now):
    if not operator_allowed(claims, settings.allowed_emails, now=now):
        raise ApiError("OPERATOR_FORBIDDEN", 403)
    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    payload = {
        "email": claims["email"],
        "display_name": claims.get("name", claims["email"]),
        "csrf_token": csrf,
        "last_seen": now.isoformat(),
    }
    store.put_event("session", token, payload, now, now + timedelta(hours=12))
    return token
