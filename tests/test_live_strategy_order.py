from datetime import datetime as RealDateTime
from types import SimpleNamespace
from unittest.mock import Mock

import trading_bot.bot as bot_module
from trading_bot.bot import TradingBot
from trading_bot.models import Stock


def test_live_strategy_runs_before_dashboard(
        monkeypatch,
):
    monkeypatch.setattr(
        bot_module,
        "ACTIVE_STRATEGY",
        "MANIPULATION_OPENING_15M",
    )

    events = []

    class FrozenDateTime(RealDateTime):
        @classmethod
        def now(cls, tz=None):
            return cls(
                2026,
                7,
                28,
                9,
                25,
                tzinfo=tz,
            )

    class FakeThread:
        def __init__(self, *args, **kwargs):
            self.target = kwargs["target"]

        def start(self):
            events.append("stream-start")

        def join(self, timeout=None):
            events.append("stream-join")

        def is_alive(self):
            return False

    class FakeTracker:
        def track_window(
                self,
                date_str,
                window_start,
                window_end,
        ):
            events.append("track")

        def merge_stream_bars(
                self,
                streamed_bars,
        ):
            events.append("merge")

    bot = object.__new__(TradingBot)
    bot.stocks = {
        "OPEN": Stock(symbol="OPEN"),
    }
    bot.symbol_reliability = None
    bot.scanner_statistics = None
    bot.scanner = SimpleNamespace()
    bot.sheets = Mock()
    bot.tracker = FakeTracker()

    bot.refresh_symbols_for_date = (
        lambda date_str: ["OPEN"]
    )
    bot.initialise_sheets = (
        lambda write_sheets=True: None
    )

    bot.run_strategy_and_write = (
        lambda date_str: events.append("strategy")
    )

    bot._publish_dashboard_session = (
        lambda **kwargs: events.append("dashboard")
    )

    monkeypatch.setattr(
        bot_module,
        "datetime",
        FrozenDateTime,
    )
    monkeypatch.setattr(
        bot_module,
        "Thread",
        FakeThread,
    )

    class FakeStream:
        def __init__(self, *args, **kwargs):
            pass

        def collect_until(self, stop_time):
            return {}

    monkeypatch.setattr(
        bot_module,
        "AlpacaStockStream",
        FakeStream,
    )

        # Quick Flip's real 09:45-11:00 monitor is tested
    # separately. This routing test must not enter a
    # real-time sleep.
    bot.run_quick_flip_monitor = (
        lambda **kwargs: events.append("quick-flip")
    )

    bot.run_live_tracker(
        write_sheets=True,
        publish_dashboard=True,
    )

    assert "strategy" in events
    assert "dashboard" in events
    assert events.index("strategy") < events.index(
        "dashboard"
    )
