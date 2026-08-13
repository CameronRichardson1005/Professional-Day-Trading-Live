from datetime import datetime
from zoneinfo import ZoneInfo

import trading_bot.bot as bot_module
from trading_bot.bot import TradingBot


EASTERN = ZoneInfo("America/New_York")


def make_bot(events):
    bot = object.__new__(TradingBot)

    bot.run_live_tracker = lambda: events.append(
        "tracker"
    )

    bot.run_strategy_and_write = (
        lambda date_str=None: events.append(
            f"strategy:{date_str}"
        )
    )

    bot.write_webull_daily_pnl = (
        lambda date_str: events.append(
            f"pnl:{date_str}"
        )
    )

    return bot


def install_clock(monkeypatch, times):
    class FakeDateTime(datetime):
        queued_times = list(times)

        @classmethod
        def now(cls, tz=None):
            return cls.queued_times.pop(0)

    monkeypatch.setattr(
        bot_module,
        "datetime",
        FakeDateTime,
    )


def test_weekend_stops_without_running_workflow(
    monkeypatch,
):
    events = []
    bot = make_bot(events)

    install_clock(
        monkeypatch,
        [
            datetime(
                2026,
                7,
                26,
                11,
                0,
                tzinfo=EASTERN,
            ),
        ],
    )

    monkeypatch.setattr(
        bot_module.time_module,
        "sleep",
        lambda seconds: events.append(
            f"sleep:{seconds}"
        ),
    )

    bot.run_production()

    assert events == []


def test_before_open_waits_then_runs_full_workflow(
    monkeypatch,
):
    events = []
    bot = make_bot(events)

    install_clock(
        monkeypatch,
        [
            datetime(
                2026,
                7,
                27,
                9,
                0,
                tzinfo=EASTERN,
            ),
            datetime(
                2026,
                7,
                27,
                9,
                45,
                15,
                tzinfo=EASTERN,
            ),
        ],
    )

    monkeypatch.setattr(
        bot_module.time_module,
        "sleep",
        lambda seconds: events.append(
            f"sleep:{seconds}"
        ),
    )

    bot.run_production()

    assert events == [
        "sleep:1800.0",
        "tracker",
        "sleep:22785.0",
        "pnl:2026-07-27",
    ]


def test_during_opening_window_tracks_then_waits(
    monkeypatch,
):
    events = []
    bot = make_bot(events)

    install_clock(
        monkeypatch,
        [
            datetime(
                2026,
                7,
                27,
                9,
                40,
                tzinfo=EASTERN,
            ),
            datetime(
                2026,
                7,
                27,
                9,
                45,
                10,
                tzinfo=EASTERN,
            ),
        ],
    )

    monkeypatch.setattr(
        bot_module.time_module,
        "sleep",
        lambda seconds: events.append(
            f"sleep:{seconds}"
        ),
    )

    bot.run_production()

    assert events == [
        "tracker",
        "sleep:22790.0",
        "pnl:2026-07-27",
    ]


def test_after_opening_window_runs_strategy_immediately(
    monkeypatch,
):
    events = []
    bot = make_bot(events)

    install_clock(
        monkeypatch,
        [
            datetime(
                2026,
                7,
                27,
                9,
                50,
                tzinfo=EASTERN,
            ),
            datetime(
                2026,
                7,
                27,
                9,
                50,
                tzinfo=EASTERN,
            ),
        ],
    )

    monkeypatch.setattr(
        bot_module.time_module,
        "sleep",
        lambda seconds: events.append(
            f"sleep:{seconds}"
        ),
    )

    bot.run_production()

    assert events == [
        "strategy:2026-07-27",
        "sleep:22500.0",
        "pnl:2026-07-27",
    ]

def test_production_skips_trading_after_cutoff_but_runs_eod_pnl(
        monkeypatch,
        capsys,
):
    import trading_bot.bot as production_bot_module

    real_datetime = production_bot_module.datetime

    class CutoffDateTime(real_datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(
                2026,
                7,
                27,
                11,
                0,
                tzinfo=tz,
            )

    monkeypatch.setattr(
        production_bot_module,
        "datetime",
        CutoffDateTime,
    )

    events = []

    monkeypatch.setattr(
        production_bot_module.time_module,
        "sleep",
        lambda seconds: events.append(
            f"sleep:{seconds}"
        ),
    )

    bot = object.__new__(
        production_bot_module.TradingBot
    )

    def unexpected_workflow(*args, **kwargs):
        raise AssertionError(
            "Trading workflow should not start "
            "after the 11:00 cutoff."
        )

    bot.run_live_tracker = unexpected_workflow
    bot.run_strategy_and_write = unexpected_workflow

    bot.write_webull_daily_pnl = (
        lambda date_str: events.append(
            f"pnl:{date_str}"
        )
    )

    bot.run_production()

    output = capsys.readouterr().out

    assert events == [
        "sleep:18300.0",
        "pnl:2026-07-27",
    ]

    assert (
        "The 11:00 New York strategy cutoff "
        "has passed."
        in output
    )

    assert (
        "Morning trading workflow will not "
        "be started."
        in output
    )

    assert (
        "Running read-only end-of-day Webull P&L "
        "reconciliation..."
        in output
    )

    assert (
        "End-of-day Google Sheets P&L "
        "update completed."
        in output
    )



def test_tracking_failure_prevents_strategy_write(
        monkeypatch,
):
    import pytest
    import trading_bot.bot as production_bot_module

    real_datetime = production_bot_module.datetime

    class OpeningWindowDateTime(real_datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(
                2026,
                7,
                27,
                9,
                35,
                tzinfo=tz,
            )

    monkeypatch.setattr(
        production_bot_module,
        "datetime",
        OpeningWindowDateTime,
    )

    bot = object.__new__(
        production_bot_module.TradingBot
    )

    def fail_tracking():
        raise RuntimeError("Tracker failed.")

    def unexpected_strategy(*args, **kwargs):
        raise AssertionError(
            "Strategy writes must not run after "
            "a tracking failure."
        )

    bot.run_live_tracker = fail_tracking
    bot.run_strategy_and_write = unexpected_strategy

    with pytest.raises(
        RuntimeError,
        match="Tracker failed",
    ):
        bot.run_production()
