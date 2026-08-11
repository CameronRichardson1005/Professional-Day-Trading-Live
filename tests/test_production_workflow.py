from datetime import datetime
from zoneinfo import ZoneInfo

import trading_bot.bot as bot_module
from trading_bot.bot import TradingBot


EASTERN = ZoneInfo("America/New_York")


def force_manipulation(monkeypatch):
    monkeypatch.setattr(
        bot_module,
        "ACTIVE_STRATEGY",
        "MANIPULATION_OPENING_15M",
    )


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
    force_manipulation(monkeypatch)
    events = []
    bot = make_bot(events)

    install_clock(
        monkeypatch,
        [
            datetime(
                2026,
                7,
                26,
                10,
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
    force_manipulation(monkeypatch)
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
    ]


def test_during_opening_window_tracks_then_waits(
    monkeypatch,
):
    force_manipulation(monkeypatch)
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
    ]


def test_after_opening_window_runs_strategy_immediately(
    monkeypatch,
):
    force_manipulation(monkeypatch)
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
    ]

def test_production_stops_after_cutoff(
        monkeypatch,
        capsys,
):
    force_manipulation(monkeypatch)
    import trading_bot.bot as production_bot_module

    real_datetime = production_bot_module.datetime

    class CutoffDateTime(real_datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(
                2026,
                7,
                27,
                10,
                0,
                tzinfo=tz,
            )

    monkeypatch.setattr(
        production_bot_module,
        "datetime",
        CutoffDateTime,
    )

    bot = object.__new__(
        production_bot_module.TradingBot
    )

    def unexpected_workflow(*args, **kwargs):
        raise AssertionError(
            "Production workflow should not start "
            "after the cutoff."
        )

    bot.run_live_tracker = unexpected_workflow
    bot.run_strategy_and_write = unexpected_workflow

    bot.run_production()

    output = capsys.readouterr().out

    assert (
        "The 10:00 New York production cutoff "
        "has passed."
        in output
    )
    assert (
        "spreadsheet writes were not started."
        in output
    )


def test_tracking_failure_prevents_strategy_write(
        monkeypatch,
):
    force_manipulation(monkeypatch)
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


def test_fibonacci_after_opening_starts_monitor(
        monkeypatch,
):
    events = []
    bot = object.__new__(TradingBot)

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
        ],
    )

    monkeypatch.setattr(
        bot_module,
        "ACTIVE_STRATEGY",
        "FIBONACCI_61_8",
    )

    bot.refresh_symbols_for_date = (
        lambda date_str: events.append(
            f"refresh:{date_str}"
        )
    )
    bot.initialise_sheets = (
        lambda: events.append("sheets")
    )
    bot.run_fibonacci_monitor = (
        lambda **kwargs: events.append(
            f"monitor:{kwargs['date_str']}"
        )
    )
    bot.run_live_tracker = (
        lambda: events.append("tracker")
    )
    bot.run_strategy_and_write = (
        lambda **kwargs: events.append("manipulation")
    )

    bot.run_production()

    assert events == [
        "refresh:2026-07-27",
        "sheets",
        "monitor:2026-07-27",
    ]
