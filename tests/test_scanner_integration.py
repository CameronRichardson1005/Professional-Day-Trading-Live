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
    bot.tracker = object()
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
    assert bot.tracker is None
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
    bot.tracker = object()
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
    assert bot.tracker is None
    assert bot.scanner_statistics is None


def test_candidate_configuration_is_distinct():
    assert len(CANDIDATE_TICKERS) == len(
        set(CANDIDATE_TICKERS)
    )
    assert set(TICKERS).isdisjoint(
        CANDIDATE_TICKERS
    )


def test_live_scanner_and_dashboard_run_before_tracking(
        monkeypatch,
):
    monkeypatch.setattr(
        bot_module,
        "ACTIVE_STRATEGY",
        "MANIPULATION_OPENING_15M",
    )

    bot = object.__new__(TradingBot)
    bot.scanner = object()
    events = []

    class FrozenDateTime(RealDateTime):
        @classmethod
        def now(cls, tz=None):
            return cls(
                2026,
                7,
                27,
                9,
                25,
                tzinfo=tz,
            )

    class FakeTracker:
        def track_window(
                self,
                date_str,
                window_start,
                window_end,
        ):
            events.append(
                ("track", date_str)
            )

    class FakeSheets:
        def write_scanner_dashboard(
                self,
                date_str,
                statistics,
                selected_symbols,
                scanner,
        ):
            events.append(
                (
                    "dashboard",
                    date_str,
                    tuple(
                        stats.symbol
                        for stats in statistics
                    ),
                    tuple(selected_symbols),
                )
            )

    def fake_refresh(date_str):
        events.append(
            ("refresh", date_str)
        )
        bot.scanner_statistics = [
            SimpleNamespace(symbol="SNAP"),
        ]
        return ["CORE", "SNAP"]

    def fake_initialise(
            write_sheets: bool = True,
    ):
        events.append(
            ("initialise", write_sheets)
        )
        bot.sheets = FakeSheets()
        bot.tracker = FakeTracker()

    monkeypatch.setattr(
        bot_module,
        "datetime",
        FrozenDateTime,
    )

    bot.refresh_symbols_for_date = fake_refresh
    bot.initialise_sheets = fake_initialise

    # Quick Flip live timing is tested separately.
    # Prevent this opening-workflow unit test from
    # entering the real 09:45-11:00 monitor.
    bot.run_quick_flip_monitor = (
        lambda **kwargs: None
    )

    bot.run_live_tracker()

    assert events == [
        ("refresh", "2026-07-27"),
        ("initialise", True),
        (
            "dashboard",
            "2026-07-27",
            ("SNAP",),
            ("CORE", "SNAP"),
        ),
        ("track", "2026-07-27"),
    ]



def test_dashboard_failure_does_not_stop_tracking(
        monkeypatch,
):
    monkeypatch.setattr(
        bot_module,
        "ACTIVE_STRATEGY",
        "MANIPULATION_OPENING_15M",
    )

    bot = object.__new__(TradingBot)
    bot.scanner = object()
    events = []

    class FrozenDateTime(RealDateTime):
        @classmethod
        def now(cls, tz=None):
            return cls(
                2026,
                7,
                27,
                9,
                25,
                tzinfo=tz,
            )

    class FakeTracker:
        def track_window(
                self,
                date_str,
                window_start,
                window_end,
        ):
            events.append(
                ("track", date_str)
            )

    class FailingSheets:
        def write_scanner_dashboard(
                self,
                date_str,
                statistics,
                selected_symbols,
                scanner,
        ):
            events.append(
                ("dashboard", date_str)
            )
            raise RuntimeError(
                "CONTROLLED DASHBOARD FAILURE"
            )

    def fake_refresh(date_str):
        events.append(
            ("refresh", date_str)
        )
        bot.scanner_statistics = [
            SimpleNamespace(symbol="SNAP"),
        ]
        return ["CORE", "SNAP"]

    def fake_initialise(
            write_sheets: bool = True,
    ):
        events.append(
            ("initialise", write_sheets)
        )
        bot.sheets = FailingSheets()
        bot.tracker = FakeTracker()

    monkeypatch.setattr(
        bot_module,
        "datetime",
        FrozenDateTime,
    )

    bot.refresh_symbols_for_date = fake_refresh
    bot.initialise_sheets = fake_initialise

    # Quick Flip live timing is tested separately.
    # Prevent this opening-workflow unit test from
    # entering the real 09:45-11:00 monitor.
    bot.run_quick_flip_monitor = (
        lambda **kwargs: None
    )

    bot.run_live_tracker()

    assert events == [
        ("refresh", "2026-07-27"),
        ("initialise", True),
        ("dashboard", "2026-07-27"),
        ("track", "2026-07-27"),
    ]


def test_scanner_universe_has_controlled_size():
    universe = list(TICKERS) + list(CANDIDATE_TICKERS)

    assert 20 <= len(universe) <= 30
    assert len(universe) == len(set(universe))
    assert len(TICKERS) == 6
    assert len(CANDIDATE_TICKERS) == 18


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
