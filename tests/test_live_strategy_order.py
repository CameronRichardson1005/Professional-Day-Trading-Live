from datetime import datetime as RealDateTime
from types import SimpleNamespace

import trading_bot.bot as bot_module
from trading_bot.bot import TradingBot
from trading_bot.models import Stock


def test_live_strategy_runs_before_dashboard(
        monkeypatch,
):
    events = []

    class FrozenDateTime(RealDateTime):
        @classmethod
        def now(cls, tz=None):
            return cls(
                2026,
                7,
                28,
                9,
                46,
                tzinfo=tz,
            )

    bot = object.__new__(TradingBot)

    bot.stocks = {
        "OPEN": Stock(symbol="OPEN"),
    }

    bot.symbols_csv = "OPEN"
    bot.symbol_reliability = None
    bot.scanner_statistics = None
    bot.scanner = SimpleNamespace()

    bot.refresh_symbols_for_date = (
        lambda date_str: ["OPEN"]
    )

    bot.initialise_sheets = (
        lambda write_sheets=True: None
    )

    def calculate_strategy(**kwargs):
        events.append("strategy")

        bot.stocks["OPEN"].opening_bar = {
            "t": "2026-07-28T13:30:00Z",
            "o": 4.0,
            "h": 4.5,
            "l": 3.8,
            "c": 4.2,
            "v": 100000,
        }

    bot.calculate_strategy = calculate_strategy

    bot._publish_dashboard_session = (
        lambda **kwargs: events.append(
            "dashboard"
        )
    )

    bot.run_quick_flip_monitor = (
        lambda **kwargs: events.append(
            "quick-flip"
        )
    )

    monkeypatch.setattr(
        bot_module,
        "datetime",
        FrozenDateTime,
    )

    bot.run_live_tracker(
        write_sheets=False,
        publish_dashboard=True,
    )

    assert "strategy" in events
    assert "dashboard" in events

    assert events.index(
        "strategy"
    ) < events.index(
        "dashboard"
    )
