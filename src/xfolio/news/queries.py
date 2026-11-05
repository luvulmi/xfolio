"""검증 중인 좁은 검색 범위. 기사 중요도·완전성을 보장하지 않는다."""

from dataclasses import dataclass


@dataclass(frozen=True)
class NewsQuery:
    query_id: str
    search: str
    domains: tuple[str, ...] = ()
    symbols: tuple[str, ...] = ()


FOCUSED_QUERIES = (
    NewsQuery(
        "us_policy",
        '("Federal Reserve"|FOMC)+(announced|raised|cut|held|decision)',
        ("reuters.com", "apnews.com", "cnbc.com"),
    ),
    NewsQuery(
        "us_indicators",
        '("U.S."|US|"United States")+'
        '("consumer price index"|"nonfarm payrolls"|"gross domestic product")+'
        "(released|reported|rose|fell)",
        ("reuters.com", "apnews.com", "cnbc.com"),
    ),
    NewsQuery(
        "company_results",
        '("quarterly results"|"financial results"|"fiscal quarter")+'
        "(reported|announced)",
        ("reuters.com", "businesswire.com", "globenewswire.com"),
        ("AAPL", "MSFT", "NVDA"),
    ),
    NewsQuery(
        "company_changes",
        '"completed acquisition"|"signed agreement"|"regulatory approval"|'
        '"awarded contract"',
        ("reuters.com", "businesswire.com", "globenewswire.com"),
        ("AAPL", "MSFT", "NVDA"),
    ),
)
