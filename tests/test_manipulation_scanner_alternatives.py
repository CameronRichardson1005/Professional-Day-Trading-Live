from trading_bot.bot import TradingBot
from trading_bot.models import Stock
from trading_bot.scanner import StockStats
from trading_bot.strategy import (
    ManipulationStrategy,
)


def stats(
    symbol,
):
    return StockStats(
        symbol=symbol,
        valid_bars=30,
        avg_volume=1_000_000,
        avg_price=10.0,
        avg_range=1.0,
        avg_range_pct=6.0,
    )


def opening_bar():
    return {
        "t": "2026-08-14T13:30:00Z",
        "o": 10.50,
        "h": 11.00,
        "l": 10.00,
        "c": 10.10,
        "v": 100000,
    }


class FakeMarketData:
    def get_opening_15min_bars(
        self,
        *,
        symbols_csv,
        date_str,
    ):
        del date_str

        return {
            symbol: opening_bar()
            for symbol
            in symbols_csv.split(",")
        }

    def get_previous_day_ranges_all(
        self,
        *,
        symbols_csv,
        date_str,
    ):
        del date_str

        return {
            symbol: 1.0
            for symbol
            in symbols_csv.split(",")
        }


def make_bot():
    bot = TradingBot.__new__(
        TradingBot
    )

    bot.strategy = (
        ManipulationStrategy()
    )

    bot.stocks = {
        "OFFICIAL": Stock(
            symbol="OFFICIAL"
        ),
    }

    bot.symbols_csv = "OFFICIAL"

    bot.scanner_alternative_candidates = [
        (
            4,
            stats("ALT4"),
        ),
        (
            5,
            stats("ALT5"),
        ),
        (
            6,
            stats("ALT6"),
        ),
    ]

    bot.manipulation_alternative_stocks = {}

    bot._get_webull_strategy_market_data = (
        lambda:
        FakeMarketData()
    )

    return bot


def test_manipulation_alternatives_can_generate_invest():
    bot = make_bot()

    bot._calculate_manipulation_strategy(
        date_str="2026-08-14",
    )

    assert set(
        bot.manipulation_alternative_stocks
    ) == {
        "ALT4",
        "ALT5",
        "ALT6",
    }

    assert all(
        stock.signal == "INVEST"
        for stock
        in bot.manipulation_alternative_stocks.values()
    )


def test_alternatives_never_enter_official_stock_universe():
    bot = make_bot()

    original_symbols = set(
        bot.stocks
    )

    bot._calculate_manipulation_strategy(
        date_str="2026-08-14",
    )

    assert set(
        bot.stocks
    ) == original_symbols

    assert (
        bot.symbols_csv
        == "OFFICIAL"
    )

    assert not (
        set(
            bot.manipulation_alternative_stocks
        )
        & set(
            bot.stocks
        )
    )

    assert (
        bot.current_invest_symbols()
        == [
            "OFFICIAL",
        ]
    )


def test_alternative_failure_does_not_change_official_signal():
    bot = make_bot()

    def fail_alternatives(
        *,
        date_str,
        market_data,
    ):
        del (
            date_str,
            market_data,
        )

        raise RuntimeError(
            "simulated alternative failure"
        )

    bot._calculate_manipulation_alternatives = (
        fail_alternatives
    )

    bot._calculate_manipulation_strategy(
        date_str="2026-08-14",
    )

    assert (
        bot.stocks[
            "OFFICIAL"
        ].signal
        == "INVEST"
    )

    assert (
        bot.manipulation_alternative_stocks
        == {}
    )
