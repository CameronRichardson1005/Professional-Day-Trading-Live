from datetime import datetime
from zoneinfo import ZoneInfo

import trading_bot.bot as bot_module
from trading_bot.bot import TradingBot


EASTERN = ZoneInfo("America/New_York")


def make_bot(events):
    bot = object.__new__(TradingBot)

    bot.write_webull_daily_pnl = (
        lambda date_str: events.append(
            f"pnl:{date_str}"
        )
    )

    return bot


def install_clock(monkeypatch, times):
    real_datetime = datetime

    class FakeDateTime(real_datetime):
        queued_times = list(times)

        @classmethod
        def now(cls, tz=None):
            return cls.queued_times.pop(0)

    monkeypatch.setattr(
        bot_module,
        "datetime",
        FakeDateTime,
    )


def test_eod_waits_until_1605_then_writes_pnl(
    monkeypatch,
):
    events = []
    bot = make_bot(events)

    install_clock(
        monkeypatch,
        [
            datetime(
                2026,
                8,
                13,
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

    bot._run_production_eod_pnl(
        date_str="2026-08-13",
        eastern=EASTERN,
    )

    assert events == [
        "sleep:18300.0",
        "pnl:2026-08-13",
    ]


def test_eod_after_1605_runs_immediately(
    monkeypatch,
):
    events = []
    bot = make_bot(events)

    install_clock(
        monkeypatch,
        [
            datetime(
                2026,
                8,
                13,
                16,
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

    bot._run_production_eod_pnl(
        date_str="2026-08-13",
        eastern=EASTERN,
    )

    assert events == [
        "pnl:2026-08-13",
    ]
