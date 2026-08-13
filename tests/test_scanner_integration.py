from datetime import datetime as RealDateTime
from types import SimpleNamespace

import trading_bot.bot as bot_module

from trading_bot.bot import TradingBot
from trading_bot.config import CANDIDATE_TICKERS
from trading_bot.config import TICKERS
from trading_bot.scanner import StockScanner
from trading_bot.scanner import StockStats


def test_bot_refreshes_symbols_from_scanner_results():
    bot = object.__new__(TradingBot)

    bot.stocks = {
        "CORE": SimpleNamespace(symbol="CORE"),
    }
    bot.symbols_csv = "CORE"
    bot.scanner = StockScanner(
        current_symbols=["CORE"],
    )

    class FakeAlpaca:
        def __init__(self):
            self.requested_symbols = None

        def get_scanner_statistics(
                self,
                symbols_csv,
                date_str,
                feed,
        ):
            self.requested_symbols = symbols_csv

            return [
                StockStats(
                    symbol="SNAP",
                    valid_bars=30,
                    avg_volume=1_000_000,
                    avg_price=10.0,
                    avg_range=0.50,
                    avg_range_pct=5.0,
                ),
            ]

    bot.alpaca = FakeAlpaca()

    selected = bot.refresh_symbols_for_date(
        "2026-07-27"
    )

    assert selected == ["CORE", "SNAP"]
    assert list(bot.stocks) == ["CORE", "SNAP"]
    assert bot.symbols_csv == "CORE,SNAP"
    assert bot.alpaca.requested_symbols == ",".join(
        CANDIDATE_TICKERS
    )
    assert [
        stats.symbol
        for stats in bot.scanner_statistics
    ] == ["SNAP"]


def test_scanner_failure_uses_current_symbols():
    bot = object.__new__(TradingBot)

    original_stock = SimpleNamespace(
        symbol="CORE",
    )

    bot.stocks = {
        "CORE": original_stock,
        "OLD": SimpleNamespace(symbol="OLD"),
    }
    bot.symbols_csv = "CORE,OLD"
    bot.scanner = StockScanner(
        current_symbols=["CORE"],
    )

    class FailingAlpaca:
        def get_scanner_statistics(
                self,
                symbols_csv,
                date_str,
        ):
            raise RuntimeError(
                "CONTROLLED SCANNER FAILURE"
            )

    bot.alpaca = FailingAlpaca()

    selected = bot.refresh_symbols_for_date(
        "2026-07-27"
    )

    assert selected == ["CORE"]
    assert bot.stocks == {
        "CORE": original_stock,
    }
    assert bot.symbols_csv == "CORE"
    assert bot.scanner_statistics is None


def test_candidate_configuration_is_distinct():
    assert len(CANDIDATE_TICKERS) == len(
        set(CANDIDATE_TICKERS)
    )
    assert set(TICKERS).isdisjoint(
        CANDIDATE_TICKERS
    )


def test_scanner_universe_has_controlled_size():
    universe = list(TICKERS) + list(CANDIDATE_TICKERS)

    assert 20 <= len(universe) <= 30
    assert len(universe) == len(set(universe))
    assert len(TICKERS) == 6
    assert len(CANDIDATE_TICKERS) == 19
    assert "IONQ" in CANDIDATE_TICKERS


def test_default_scanner_never_selects_more_than_nine():
    statistics = [
        StockStats(
            symbol=symbol,
            valid_bars=30,
            avg_volume=2_000_000 - index,
            avg_price=10.0,
            avg_range=0.75,
            avg_range_pct=7.5,
        )
        for index, symbol in enumerate(CANDIDATE_TICKERS)
    ]

    scanner = StockScanner(
        current_symbols=TICKERS,
    )

    selected = scanner.select_symbols(statistics)

    assert selected[:len(TICKERS)] == TICKERS
    assert len(selected) == 9
    assert len(
        set(selected) & set(CANDIDATE_TICKERS)
    ) == 3
