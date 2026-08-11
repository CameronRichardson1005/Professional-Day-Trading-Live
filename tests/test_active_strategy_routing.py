from types import SimpleNamespace

import trading_bot.bot as bot_module

from trading_bot.bot import TradingBot
from trading_bot.models import Stock


def make_bot():
    bot = object.__new__(TradingBot)
    bot.stocks = {
        "TEST": Stock(symbol="TEST"),
    }
    bot.symbols_csv = "TEST"
    return bot


def test_router_uses_preserved_manipulation_strategy(
        monkeypatch,
):
    bot = make_bot()
    events = []

    bot._calculate_manipulation_strategy = (
        lambda date_str: events.append(
            ("manipulation", date_str)
        )
    )
    bot._calculate_fibonacci_strategy = (
        lambda **kwargs: events.append(
            ("fibonacci", kwargs["date_str"])
        )
    )

    monkeypatch.setattr(
        bot_module,
        "ACTIVE_STRATEGY",
        "MANIPULATION_OPENING_15M",
    )

    bot.calculate_strategy("2026-08-03")

    assert events == [
        ("manipulation", "2026-08-03"),
    ]


def test_router_uses_fibonacci_strategy(
        monkeypatch,
):
    bot = make_bot()
    events = []

    bot._calculate_manipulation_strategy = (
        lambda date_str: events.append(
            ("manipulation", date_str)
        )
    )
    bot._calculate_fibonacci_strategy = (
        lambda **kwargs: events.append(
            ("fibonacci", kwargs["date_str"])
        )
    )

    monkeypatch.setattr(
        bot_module,
        "ACTIVE_STRATEGY",
        "FIBONACCI_61_8",
    )

    bot.calculate_strategy("2026-08-03")

    assert events == [
        ("fibonacci", "2026-08-03"),
    ]


def test_fibonacci_route_passes_only_available_bars(
        monkeypatch,
):
    bot = make_bot()

    captured = {}

    class FakeAlpaca:
        def get_opening_15min_bars(
                self,
                symbols_csv,
                date_str,
                feed,
        ):
            return {"TEST": None}

        def get_previous_day_ranges_all(
                self,
                symbols_csv,
                date_str,
                feed,
        ):
            return {"TEST": 1.0}

        def get_historical_1min_bars(
                self,
                symbols_csv,
                start_iso,
                end_iso,
                feed,
        ):
            captured["start"] = start_iso
            captured["end"] = end_iso
            return {"TEST": []}

    class FakeFibonacci:
        def evaluate(self, **kwargs):
            captured["bars"] = kwargs["bars"]
            kwargs["stock"].signal = "NO INVEST"

    bot.alpaca = FakeAlpaca()
    bot.fibonacci_strategy = FakeFibonacci()

    bot._calculate_fibonacci_strategy(
        date_str="2026-08-03",
        evaluation_end=bot_module.datetime(
            2026,
            8,
            3,
            10,
            5,
        ),
        data_feed="sip",
    )

    assert captured["start"].endswith("13:30:00Z")
    assert captured["end"].endswith("14:05:00Z")
    assert captured["bars"] == []


def test_manipulation_class_remains_available():
    from trading_bot.strategy import ManipulationStrategy

    strategy = ManipulationStrategy()

    assert hasattr(strategy, "evaluate")
