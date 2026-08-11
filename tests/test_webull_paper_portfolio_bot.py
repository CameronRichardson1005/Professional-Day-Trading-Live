from datetime import UTC, datetime
from types import SimpleNamespace

import trading_bot.bot as bot_module

from trading_bot.bot import TradingBot


def test_refresh_portfolio_uses_cached_marks_and_same_store(
    monkeypatch,
):
    bot = object.__new__(TradingBot)

    bars = {
        "OPEN": [
            {
                "t": "2026-08-07T14:01:00Z",
                "c": 4.35,
            }
        ]
    }
    store = object()
    expected_portfolio = object()

    seen = {}

    def fake_latest_prices(
        bars_by_symbol,
    ):
        seen["bars"] = bars_by_symbol
        return {"OPEN": 4.35}

    def fake_load_portfolio(
        *,
        latest_prices,
        store,
    ):
        seen["latest_prices"] = latest_prices
        seen["store"] = store
        return expected_portfolio

    monkeypatch.setattr(
        bot_module,
        "latest_prices_from_completed_bars",
        fake_latest_prices,
    )
    monkeypatch.setattr(
        bot_module,
        "load_webull_paper_portfolio",
        fake_load_portfolio,
    )

    result = bot._refresh_webull_paper_portfolio(
        bars_by_symbol=bars,
        store=store,
    )

    assert result is expected_portfolio
    assert (
        bot._webull_paper_portfolio_snapshot
        is expected_portfolio
    )
    assert seen["bars"] is bars
    assert seen["latest_prices"] == {
        "OPEN": 4.35,
    }
    assert seen["store"] is store


def test_lifecycle_processing_refreshes_portfolio():
    bot = object.__new__(TradingBot)

    bars = {
        "OPEN": [
            {
                "t": "2026-08-07T14:01:00Z",
                "h": 4.40,
                "l": 4.20,
                "c": 4.35,
            }
        ]
    }

    class FakeStore:
        def load(self):
            return {}

    store = FakeStore()
    seen = {}

    class FakeTracker:
        def __init__(self):
            self.store = store

        def process_bars(
            self,
            *,
            bars_by_symbol,
        ):
            seen["processed"] = bars_by_symbol
            return []

    bot.webull_paper_lifecycle_tracker = (
        FakeTracker()
    )

    bot._cached_fibonacci_bars_for_lifecycle = (
        lambda **kwargs: bars
    )

    bot._print_webull_paper_lifecycle_changes = (
        lambda **kwargs: None
    )

    def refresh(
        *,
        bars_by_symbol,
        store,
    ):
        seen["refresh_bars"] = bars_by_symbol
        seen["refresh_store"] = store

    bot._refresh_webull_paper_portfolio = (
        refresh
    )

    bot._process_webull_paper_lifecycle(
        date_str="2026-08-07",
        evaluation_end=datetime(
            2026,
            8,
            7,
            14,
            2,
            tzinfo=UTC,
        ),
        data_feed="iex",
    )

    assert seen["processed"] is bars
    assert seen["refresh_bars"] is bars
    assert seen["refresh_store"] is store


def test_cutoff_finalization_refreshes_portfolio():
    bot = object.__new__(TradingBot)

    bars = {
        "OPEN": [
            {
                "t": "2026-08-07T14:59:00Z",
                "h": 4.40,
                "l": 4.20,
                "c": 4.35,
            }
        ]
    }

    cutoff = datetime(
        2026,
        8,
        7,
        15,
        0,
        tzinfo=UTC,
    )

    class FakeStore:
        def load(self):
            return {}

    store = FakeStore()
    seen = {}

    class FakeTracker:
        def __init__(self):
            self.store = store

        def finalize_at_cutoff(
            self,
            *,
            cutoff,
            bars_by_symbol,
        ):
            seen["cutoff"] = cutoff
            seen["finalized_bars"] = (
                bars_by_symbol
            )
            return []

    bot.webull_paper_lifecycle_tracker = (
        FakeTracker()
    )

    bot._cached_fibonacci_bars_for_lifecycle = (
        lambda **kwargs: bars
    )

    bot._print_webull_paper_lifecycle_changes = (
        lambda **kwargs: None
    )

    def refresh(
        *,
        bars_by_symbol,
        store,
    ):
        seen["refresh_bars"] = bars_by_symbol
        seen["refresh_store"] = store

    bot._refresh_webull_paper_portfolio = refresh

    bot._finalize_webull_paper_lifecycle(
        date_str="2026-08-07",
        cutoff=cutoff,
        data_feed="iex",
    )

    assert seen["cutoff"] == cutoff
    assert seen["finalized_bars"] is bars
    assert seen["refresh_bars"] is bars
    assert seen["refresh_store"] is store
