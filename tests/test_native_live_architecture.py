from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import trading_bot.bot as bot_module
from trading_bot.bot import TradingBot
from trading_bot.models import Stock


EASTERN = ZoneInfo("America/New_York")


def test_live_tracker_does_not_use_1min_tracker_or_stream(
    monkeypatch,
):
    bot = object.__new__(TradingBot)

    bot.stocks = {
        "TEST": Stock(
            symbol="TEST"
        )
    }
    bot.symbols_csv = "TEST"

    bot.scanner_statistics = None

    bot.refresh_symbols_for_date = (
        lambda date_str: ["TEST"]
    )

    bot.initialise_sheets = (
        lambda write_sheets=True: None
    )

    # The standalone live bot must not even import the
    # legacy 1Min WebSocket dependency.
    assert not hasattr(
        bot_module,
        "AlpacaStockStream",
    )

    # The standalone live bot must not require a tracker.
    assert not hasattr(
        bot,
        "tracker",
    )

    strategy_calls = []

    def fake_calculate_strategy(
        date_str,
    ):
        strategy_calls.append(
            date_str
        )

        bot.stocks[
            "TEST"
        ].opening_bar = {
            "t": "2026-08-11T13:30:00Z",
            "o": 10.0,
            "h": 11.0,
            "l": 9.0,
            "c": 10.5,
            "v": 100000,
        }

        bot.stocks[
            "TEST"
        ].signal = "NO INVEST"

    bot.calculate_strategy = (
        fake_calculate_strategy
    )

    bot.run_quick_flip_monitor = (
        lambda **kwargs: None
    )

    bot._publish_dashboard_session = (
        lambda **kwargs: None
    )

    class FakeDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            value = datetime(
                2026,
                8,
                11,
                9,
                46,
                tzinfo=EASTERN,
            )

            if tz is None:
                return value.replace(
                    tzinfo=None
                )

            return value.astimezone(
                tz
            )

    monkeypatch.setattr(
        bot_module,
        "datetime",
        FakeDateTime,
    )

    bot.run_live_tracker(
        write_sheets=False,
        publish_dashboard=False,
    )

    assert strategy_calls == [
        "2026-08-11"
    ]


def test_live_tracker_native_opening_bar_counts_as_complete(
    monkeypatch,
):
    bot = object.__new__(TradingBot)

    bot.stocks = {
        "TEST": Stock(
            symbol="TEST"
        )
    }

    bot.symbols_csv = "TEST"
    bot.scanner_statistics = None

    bot.refresh_symbols_for_date = (
        lambda date_str: ["TEST"]
    )

    bot.initialise_sheets = (
        lambda write_sheets=True: None
    )

    bot.tracker = SimpleNamespace()

    bot.calculate_strategy = (
        lambda date_str: setattr(
            bot.stocks["TEST"],
            "opening_bar",
            {
                "t": "2026-08-11T13:30:00Z",
                "o": 10.0,
                "h": 11.0,
                "l": 9.0,
                "c": 10.5,
                "v": 100000,
            },
        )
    )

    bot.run_quick_flip_monitor = (
        lambda **kwargs: None
    )

    captured = {}

    def fake_publish_dashboard_session(
        **kwargs,
    ):
        captured.update(
            kwargs
        )

    bot._publish_dashboard_session = (
        fake_publish_dashboard_session
    )

    class FakeDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            value = datetime(
                2026,
                8,
                11,
                9,
                46,
                tzinfo=EASTERN,
            )

            if tz is None:
                return value.replace(
                    tzinfo=None
                )

            return value.astimezone(
                tz
            )

    monkeypatch.setattr(
        bot_module,
        "datetime",
        FakeDateTime,
    )

    bot.run_live_tracker(
        write_sheets=False,
        publish_dashboard=True,
    )

    assert (
        captured["processed_bars"]["TEST"]
        == 15
    )
