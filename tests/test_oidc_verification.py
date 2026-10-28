"""Google 검증 경계의 서명/claim 시험. 토큰 교환과 JWKS HTTP는 모의한다."""

import asyncio
from datetime import UTC, datetime

import pytest
from authlib.jose import JsonWebKey, jwt
from authlib.jose.errors import JoseError

from xfolio.api.auth import GoogleProvider, Settings

NOW = datetime(2026, 10, 28, 8, 50, tzinfo=UTC)


@pytest.fixture
def verifier(monkeypatch):
    key = JsonWebKey.generate_key("RSA", 2048, is_private=True)
    key_data = key.as_dict(is_private=True)
    key_data["kid"] = "local-test"
    public = key.as_dict()
    public["kid"] = "local-test"
    tokens = {}

    class FakeExchange:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def fetch_token(self, url, *, code):
            assert url == "https://oauth2.googleapis.com/token" and code == "code"
            return {"id_token": tokens["value"]}

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"keys": [public]}

    class FakeHttp(FakeExchange):
        def __init__(self, **kwargs):
            pass

        async def get(self, url):
            assert url == "https://www.googleapis.com/oauth2/v3/certs"
            return FakeResponse()

    provider = GoogleProvider(Settings(google_client_id="local-client"))
    monkeypatch.setattr(provider, "client", lambda: FakeExchange())
    monkeypatch.setattr("xfolio.api.auth.httpx.AsyncClient", FakeHttp)

    def verify(**changes):
        bad_signature = changes.pop("_bad_signature", False)
        claims = {
            "iss": "https://accounts.google.com",
            "aud": "local-client",
            "sub": "local-subject",
            "nonce": "expected-nonce",
            "iat": int(NOW.timestamp()) - 60,
            "exp": int(NOW.timestamp()) + 600,
        }
        claims.update(changes)
        signing_key = (
            JsonWebKey.generate_key("RSA", 2048, is_private=True).as_dict(
                is_private=True
            )
            if bad_signature
            else key_data
        )
        signing_key["kid"] = "local-test"
        tokens["value"] = jwt.encode(
            {"alg": "RS256", "kid": "local-test"}, claims, signing_key
        ).decode()
        return asyncio.run(provider.verify("code", "expected-nonce", NOW))

    return verify


def test_verified_signature_and_claims_are_returned(verifier):
    assert verifier()["sub"] == "local-subject"


@pytest.mark.parametrize(
    "changes",
    [
        {"iss": "https://attacker.invalid"},
        {"aud": "other-client"},
        {"nonce": "other-flow"},
        {"exp": int(NOW.timestamp()) - 120},
        {"_bad_signature": True},
    ],
)
def test_signed_token_with_wrong_claims_is_rejected(verifier, changes):
    with pytest.raises(JoseError):
        verifier(**changes)
