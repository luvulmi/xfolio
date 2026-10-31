from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pandas as pd
import pytest

from xfolio.etf import ETFSnapshot, collect_etf_closes, etf_post_text, load_etf_history
from xfolio.market import MarketDataError, completed_sessions

NOW = datetime(2026, 10, 28, 22, 20, tzinfo=UTC)


def frame(previous, current, closes=(100, 101)):
    return pd.DataFrame(
        {"Close": closes, "Dividends": [0, 0], "Stock Splits": [0, 0]},
        index=pd.DatetimeIndex([str(previous), str(current)], tz="America/New_York"),
    )


def snapshot(loader=None, **updates):
    previous, current, _ = completed_sessions(NOW, "NYSE")
    return collect_etf_closes(
        **(
            {
                "as_of": NOW,
                "clock": lambda: NOW,
                "synthetic": True,
                "history_loader": loader
                or (
                    lambda *args: (
                        frame(previous, current),
                        {"currency": "USD", "instrumentType": "ETF"},
                    )
                ),
            }
            | updates
        )
    )


def test_three_etfs_same_completed_day_usd_close_and_price_return():
    result = snapshot()
    assert [p.symbol for p in result.prices] == ["SPY", "QQQ", "DIA"]
    assert all(p.change_pct == Decimal("1.00") for p in result.prices)
    assert ETFSnapshot.model_validate_json(result.model_dump_json()) == result
    text = etf_post_text(result)
    assert "USD" in text and "분배금 미포함" in text and "지수" not in text


@pytest.mark.parametrize(
    "change",
    [
        "currency",
        "instrument",
        "missing",
        "duplicate",
        "zero",
        "nan",
        "actions",
        "split",
        "stale",
    ],
)
def test_invalid_any_symbol_aborts_entire_snapshot(change):
    previous, current, _ = completed_sessions(NOW, "NYSE")

    def loader(symbol, *args):
        history, metadata = (
            frame(previous, current),
            {"currency": "USD", "instrumentType": "ETF"},
        )
        if symbol == "QQQ":
            if change == "currency":
                metadata["currency"] = "KRW"
            elif change == "instrument":
                metadata["instrumentType"] = "INDEX"
            elif change == "missing":
                history = history.iloc[:1]
            elif change == "duplicate":
                history = pd.concat([history, history.iloc[-1:]])
            elif change == "zero":
                history.iloc[-1, 0] = 0
            elif change == "nan":
                history.iloc[-1, 0] = float("nan")
            elif change == "actions":
                history = history.drop(columns="Dividends")
            elif change == "split":
                history.loc[history.index[-1], "Stock Splits"] = 2
            elif change == "stale":
                history.index = history.index - timedelta(days=7)
        return history, metadata

    with pytest.raises(MarketDataError):
        snapshot(loader)


def test_dividend_is_recorded_without_adding_to_price_return_and_revision_is_visible():
    original = snapshot()
    previous, current, _ = completed_sessions(NOW, "NYSE")

    def loader(*args):
        history = frame(previous, current, (100, 99))
        history.loc[history.index[-1], "Dividends"] = 2
        return history, {"currency": "USD", "instrumentType": "ETF"}

    changed = snapshot(loader, previous=original)
    assert changed.prices[0].change_pct == Decimal("-1.00")
    assert (
        changed.prices[0].dividend == 2 and changed.supersedes == original.content_hash
    )


def test_loader_uses_unadjusted_close_actions_and_same_ticker_metadata(monkeypatch):
    previous, current, _ = completed_sessions(NOW, "NYSE")
    calls = []

    class Ticker:
        def __init__(self, symbol):
            calls.append(symbol)

        def history(self, **kwargs):
            calls.append(kwargs)
            return frame(previous, current)

        def get_history_metadata(self):
            return {"currency": "USD", "instrumentType": "ETF"}

    monkeypatch.setattr("xfolio.etf.yf.Ticker", Ticker)
    history, meta = load_etf_history("SPY", previous, current + timedelta(days=1))
    assert calls[0] == "SPY" and not calls[1]["auto_adjust"] and not calls[1]["repair"]
    assert calls[1]["actions"] and meta["currency"] == "USD" and len(history) == 2


def test_etf_cli_uses_etf_model_without_changing_legacy_index_command(
    monkeypatch, capsys
):
    from xfolio.cli import main

    monkeypatch.setattr("xfolio.etf.collect_etf_closes", snapshot)
    main(["etf-close", "--json"])
    assert '"etf_snapshot_v1"' in capsys.readouterr().out
    main(["etf-close"])
    assert "SPY" in capsys.readouterr().out
