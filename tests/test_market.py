"""외부 API 없이 시장 날짜·종가 검증과 CLI 동작을 확인한다."""

import json
from datetime import UTC, date, datetime
from decimal import Decimal

import pandas as pd
import pytest

from xfolio import cli, market

AS_OF = datetime(2026, 10, 23, 22, tzinfo=UTC)


@pytest.fixture(autouse=True)
def block_yahoo_network(monkeypatch):
    def blocked(*args, **kwargs):
        pytest.fail("단위 시험에서 Yahoo 네트워크 요청을 할 수 없습니다.")

    monkeypatch.setattr(market.yf, "Ticker", blocked)


def prices(values=("100", "101.005"), dates=("2026-10-22", "2026-10-23")):
    return pd.DataFrame(
        {"Close": list(values)},
        index=pd.DatetimeIndex(dates, tz="America/New_York"),
    )


def sample_snapshot():
    return market.collect_index_closes(as_of=AS_OF, history_loader=lambda *_: prices())


@pytest.mark.parametrize("calendar", ["NYSE", "NASDAQ"])
@pytest.mark.parametrize(
    ("timestamp", "previous", "latest"),
    [
        ("2026-07-08T19:59:00+00:00", "2026-07-06", "2026-07-07"),
        ("2026-07-08T20:00:00+00:00", "2026-07-07", "2026-07-08"),
        ("2026-01-07T20:59:00+00:00", "2026-01-05", "2026-01-06"),
        ("2026-01-07T21:00:00+00:00", "2026-01-06", "2026-01-07"),
        ("2026-07-03T22:00:00+00:00", "2026-07-01", "2026-07-02"),
        ("2026-07-05T22:00:00+00:00", "2026-07-01", "2026-07-02"),
        ("2026-11-26T22:00:00+00:00", "2026-11-24", "2026-11-25"),
        ("2026-11-27T17:59:00+00:00", "2026-11-24", "2026-11-25"),
        ("2026-11-27T18:00:00+00:00", "2026-11-25", "2026-11-27"),
    ],
)
def test_completed_sessions(calendar, timestamp, previous, latest):
    reference = datetime.fromisoformat(timestamp)
    previous_day, trade_day, closed_at = market.completed_sessions(reference, calendar)
    assert (previous_day.isoformat(), trade_day.isoformat()) == (previous, latest)
    assert closed_at <= reference
    assert closed_at.tzinfo == UTC


def test_two_indices_preserve_raw_close_and_source():
    calls = []

    def loader(symbol, start, end):
        calls.append((symbol, start, end))
        return prices() if symbol == "^GSPC" else prices(("200", "199.98"))

    snapshot = market.collect_index_closes(as_of=AS_OF, history_loader=loader)
    assert calls == [
        ("^GSPC", date(2026, 10, 22), date(2026, 10, 24)),
        ("^NDX", date(2026, 10, 22), date(2026, 10, 24)),
    ]
    sp500, nasdaq = snapshot.indices
    assert snapshot.trade_date == date(2026, 10, 23)
    assert sp500.close == Decimal("101.005")
    assert sp500.change_pct == Decimal("1.01")
    assert nasdaq.change_pct == Decimal("-0.01")
    assert sp500.provider == "Yahoo Finance"
    assert sp500.collector == "yfinance"
    assert "%5EGSPC" in sp500.source_url
    assert sp500.retrieved_at.tzinfo == UTC
    payload = json.loads(snapshot.model_dump_json())
    assert payload["indices"][0]["close"] == "101.005"


@pytest.mark.parametrize(
    "bad_value", [None, float("nan"), "Infinity", "0", "-1", "bad"]
)
def test_invalid_required_close_is_not_replaced(bad_value):
    with pytest.raises(market.MarketDataError):
        market.collect_index_closes(
            as_of=AS_OF, history_loader=lambda *_: prices(("100", bad_value))
        )


@pytest.mark.parametrize(
    "frame",
    [
        None,
        pd.DataFrame(),
        prices().rename(columns={"Close": "Adj Close"}),
        prices(("99", "100"), ("2026-10-21", "2026-10-22")),
        prices(("101", "102"), ("2026-10-23", "2026-10-23")),
        prices(("100",), ("2026-10-23",)),
        pd.DataFrame({"Close": [100, 101]}),
    ],
    ids=[
        "no-response",
        "empty",
        "no-close",
        "stale",
        "duplicate",
        "no-previous",
        "invalid-dates",
    ],
)
def test_bad_history_holds_the_whole_snapshot(frame):
    with pytest.raises(market.MarketDataError):
        market.collect_index_closes(as_of=AS_OF, history_loader=lambda *_: frame)


def test_partial_intraday_row_is_not_selected():
    reference = datetime(2026, 10, 23, 19, tzinfo=UTC)
    frame = prices(("100", "101", "999"), ("2026-10-21", "2026-10-22", "2026-10-23"))
    snapshot = market.collect_index_closes(
        as_of=reference, history_loader=lambda *_: frame
    )
    assert snapshot.trade_date == date(2026, 10, 22)
    assert snapshot.indices[0].close == Decimal(101)


def test_utc_dates_are_interpreted_in_exchange_timezone():
    frame = prices()
    frame.index = frame.index.tz_convert("UTC")
    snapshot = market.collect_index_closes(as_of=AS_OF, history_loader=lambda *_: frame)
    assert snapshot.indices[0].close == Decimal("101.005")


def test_negative_zero_and_half_up_display():
    snapshot = market.collect_index_closes(
        as_of=AS_OF, history_loader=lambda *_: prices(("100", "99.999"))
    )
    assert str(snapshot.indices[0].change_pct) == "0.00"
    assert market.display_number(Decimal("-0.001")) == "0.00"
    assert market.display_number(Decimal("101.005")) == "101.01"


def test_naive_reference_is_rejected():
    with pytest.raises(ValueError, match="시간대"):
        market.collect_index_closes(as_of=AS_OF.replace(tzinfo=None))


def test_provider_receives_unadjusted_daily_request(monkeypatch):
    calls = []

    class FakeTicker:
        def __init__(self, symbol):
            assert symbol == "^GSPC"

        def history(self, **kwargs):
            calls.append(kwargs)
            return prices()

    monkeypatch.setattr(market.yf, "Ticker", FakeTicker)
    market.load_yahoo_history("^GSPC", date(2026, 10, 22), date(2026, 10, 24))
    assert calls[0]["start"] == "2026-10-22"
    assert calls[0]["end"] == "2026-10-24"
    assert calls[0]["interval"] == "1d"
    assert calls[0]["auto_adjust"] is False
    assert calls[0]["repair"] is False


def test_provider_failure_aborts_without_partial_output(monkeypatch, capsys):
    def ticker_failure(_symbol):
        raise TimeoutError("synthetic timeout")

    monkeypatch.setattr(market.yf, "Ticker", ticker_failure)
    with pytest.raises(SystemExit) as failure:
        cli.main(["market-close", "--json"])
    assert failure.value.code == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert "TimeoutError" in output.err


def test_second_index_missing_aborts_whole_command(monkeypatch, capsys):
    def collect():
        return market.collect_index_closes(
            as_of=AS_OF,
            history_loader=lambda symbol, *_: (
                prices() if symbol == "^GSPC" else pd.DataFrame()
            ),
        )

    monkeypatch.setattr(cli, "collect_index_closes", collect)
    with pytest.raises(SystemExit) as failure:
        cli.main(["market-close", "--json"])
    assert failure.value.code == 1
    assert capsys.readouterr().out == ""


def test_cli_json_and_human_output(monkeypatch, capsys):
    snapshot = sample_snapshot()
    monkeypatch.setattr(cli, "collect_index_closes", lambda: snapshot)
    cli.main(["market-close", "--json"])
    assert json.loads(capsys.readouterr().out)["trade_date"] == "2026-10-23"
    cli.main(["market-close"])
    text = capsys.readouterr().out
    assert "S&P 500 (^GSPC): 101.01 / +1.01%" in text
    assert "Nasdaq-100 (^NDX)" in text
