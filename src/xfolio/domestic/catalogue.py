"""공식 KOSPI 마스터 식별/검색. 이름만으로 해외 ETF를 활성화하지 않는다."""

import io
import re
import unicodedata
import zipfile
from datetime import datetime

import httpx

from xfolio.domestic.models import (
    DEFAULT_CODES,
    MASTER_URL,
    DomesticError,
    Instrument,
    utc,
)

DEFAULTS = {
    "360750": ("KR7360750004", "TIGER 미국S&P500"),
    "379810": ("KR7379810005", "KODEX 미국나스닥100"),
    "458730": ("KR7458730009", "TIGER 미국배당다우존스"),
}


def default_instruments(retrieved_at: datetime) -> tuple[Instrument, ...]:
    # Approved product scope + T01 identity/quote evidence. No new live claims.
    identity_observed_at = datetime.fromisoformat("2026-11-01T06:13:27.497309+00:00")
    if utc(retrieved_at) < identity_observed_at:
        raise DomesticError("default_identity_not_yet_observed")
    return tuple(
        Instrument(
            code=code,
            isin=DEFAULTS[code][0],
            name=DEFAULTS[code][1],
            retrieved_at=identity_observed_at,
            eligible=True,
            eligibility_basis="user_confirmed_default_scope:T01:2026-11-03",
        )
        for code in DEFAULT_CODES
    )


def parse_master(payload: bytes, retrieved_at: datetime) -> tuple[Instrument, ...]:
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            member = archive.getinfo("kospi_code.mst")
            if member.file_size > 20_000_000:
                raise ValueError
            text = archive.read(member).decode("cp949")
        result = []
        seen = set()
        for row in text.splitlines(keepends=True):
            if len(row) <= 249:
                raise ValueError
            identity = row[:-228]
            code, isin, name = (
                identity[:9].strip(),
                identity[9:21],
                identity[21:].strip(),
            )
            # KOSPI master also contains longer identifiers for other instruments.
            # This collector explicitly supports 6-digit stock/ETF codes only.
            if not re.fullmatch(r"[0-9]{6}", code):
                continue
            if code in seen:
                raise ValueError
            seen.add(code)
            # Only the three pre-approved defaults are eligible without review.
            approved = code in DEFAULTS and (isin, name) == DEFAULTS[code]
            result.append(
                Instrument(
                    code=code,
                    isin=isin,
                    name=name,
                    retrieved_at=retrieved_at,
                    eligible=approved,
                    eligibility_basis="user_confirmed_default_scope:T01:2026-11-03"
                    if approved
                    else None,
                )
            )
        if not result:
            raise ValueError
        return tuple(result)
    except (ValueError, KeyError, OSError, zipfile.BadZipFile, UnicodeDecodeError):
        raise DomesticError("invalid_master") from None


def search(instruments, query: str, *, limit=20):
    if not 1 <= limit <= 100:
        raise DomesticError("invalid_search_limit")

    def normalized(text):
        return "".join(unicodedata.normalize("NFKC", text).casefold().split())

    needle = normalized(query)
    if not needle:
        return ()
    return tuple(
        sorted(
            (i for i in instruments if needle in normalized(i.code + i.name)),
            key=lambda i: (i.code != query, i.code),
        )
    )[:limit]


def fetch_master(*, retrieved_at: datetime, client=None):
    own = client is None
    client = client or httpx.Client(timeout=20, follow_redirects=False, trust_env=False)
    try:
        response = client.get(MASTER_URL)  # Public origin, no auth headers.
        if response.status_code != 200:
            raise DomesticError("master_http_error")
        if len(response.content) > 20_000_000:
            raise DomesticError("master_too_large")
        return parse_master(response.content, retrieved_at)
    except httpx.RequestError:
        raise DomesticError("master_network_error") from None
    finally:
        if own:
            client.close()
