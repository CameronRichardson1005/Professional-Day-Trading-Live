from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from trading_bot.bot import TradingBot
from trading_bot.models import Stock


EASTERN = ZoneInfo("America/New_York")


def bar(timestamp, close=10.0):
    return {
        "t": timestamp,
        "o": close,
        "h": close,
        "l": close,
        "c": close,
        "v": 100,
    }


class FakeAlpaca:
    def __init__(self):
        self.calls = []
        self.responses = []
        self.error = None

    def get_historical_1min_bars(
            self,
            *,
            symbols_csv,
            start_iso,
            end_iso,
            feed,
    ):
        self.calls.append(
            (
                symbols_csv,
                start_iso,
                end_iso,
                feed,
            )
        )

        if self.error is not None:
            raise self.error

        if self.responses:
            return self.responses.pop(0)

        return {
            symbol: []
            for symbol in symbols_csv.split(",")
        }


def make_bot():
    bot = object.__new__(TradingBot)
    bot.stocks = {
        "OPEN": Stock(symbol="OPEN"),
        "SOUN": Stock(symbol="SOUN"),
    }
    bot.symbols_csv = "OPEN,SOUN"
    bot.alpaca = FakeAlpaca()
    return bot


def test_intraday_cache_fetches_only_incremental_range():
    bot = make_bot()

    bot.alpaca.responses = [
        {
            "OPEN": [
                bar("2026-08-07T13:30:00Z"),
                bar("2026-08-07T13:44:00Z"),
            ],
            "SOUN": [],
        },
        {
            "OPEN": [
                bar("2026-08-07T13:44:00Z"),
                bar("2026-08-07T13:45:00Z"),
            ],
            "SOUN": [],
        },
    ]

    session_start = datetime(
        2026, 8, 7, 9, 30,
        tzinfo=EASTERN,
    )

    first = bot._get_fibonacci_intraday_bars(
        date_str="2026-08-07",
        data_feed="iex",
        session_start=session_start,
        evaluation_end=datetime(
            2026, 8, 7, 9, 45,
            tzinfo=EASTERN,
        ),
    )

    second = bot._get_fibonacci_intraday_bars(
        date_str="2026-08-07",
        data_feed="iex",
        session_start=session_start,
        evaluation_end=datetime(
            2026, 8, 7, 9, 46,
            tzinfo=EASTERN,
        ),
    )

    assert bot.alpaca.calls == [
        (
            "OPEN,SOUN",
            "2026-08-07T13:30:00Z",
            "2026-08-07T13:45:00Z",
            "iex",
        ),
        (
            "OPEN,SOUN",
            "2026-08-07T13:44:00Z",
            "2026-08-07T13:46:00Z",
            "iex",
        ),
    ]

    assert [
        item["t"]
        for item in first["OPEN"]
    ] == [
        "2026-08-07T13:30:00Z",
        "2026-08-07T13:44:00Z",
    ]

    assert [
        item["t"]
        for item in second["OPEN"]
    ] == [
        "2026-08-07T13:30:00Z",
        "2026-08-07T13:44:00Z",
        "2026-08-07T13:45:00Z",
    ]


def test_intraday_cache_deduplicates_overlap():
    bot = make_bot()

    bot.alpaca.responses = [
        {
            "OPEN": [
                bar(
                    "2026-08-07T13:44:00Z",
                    close=10.0,
                ),
            ],
            "SOUN": [],
        },
        {
            "OPEN": [
                bar(
                    "2026-08-07T13:44:00Z",
                    close=10.5,
                ),
            ],
            "SOUN": [],
        },
    ]

    session_start = datetime(
        2026, 8, 7, 9, 30,
        tzinfo=EASTERN,
    )

    bot._get_fibonacci_intraday_bars(
        date_str="2026-08-07",
        data_feed="iex",
        session_start=session_start,
        evaluation_end=datetime(
            2026, 8, 7, 9, 45,
            tzinfo=EASTERN,
        ),
    )

    result = bot._get_fibonacci_intraday_bars(
        date_str="2026-08-07",
        data_feed="iex",
        session_start=session_start,
        evaluation_end=datetime(
            2026, 8, 7, 9, 46,
            tzinfo=EASTERN,
        ),
    )

    assert len(result["OPEN"]) == 1
    assert result["OPEN"][0]["c"] == 10.5


def test_intraday_cache_reuses_covered_range():
    bot = make_bot()

    bot.alpaca.responses = [{
        "OPEN": [
            bar("2026-08-07T13:30:00Z"),
        ],
        "SOUN": [],
    }]

    session_start = datetime(
        2026, 8, 7, 9, 30,
        tzinfo=EASTERN,
    )

    kwargs = {
        "date_str": "2026-08-07",
        "data_feed": "iex",
        "session_start": session_start,
        "evaluation_end": datetime(
            2026, 8, 7, 9, 45,
            tzinfo=EASTERN,
        ),
    }

    first = bot._get_fibonacci_intraday_bars(
        **kwargs
    )
    second = bot._get_fibonacci_intraday_bars(
        **kwargs
    )

    assert first == second
    assert len(bot.alpaca.calls) == 1


def test_failed_incremental_fetch_preserves_cache():
    bot = make_bot()

    bot.alpaca.responses = [{
        "OPEN": [
            bar("2026-08-07T13:30:00Z"),
        ],
        "SOUN": [],
    }]

    session_start = datetime(
        2026, 8, 7, 9, 30,
        tzinfo=EASTERN,
    )

    bot._get_fibonacci_intraday_bars(
        date_str="2026-08-07",
        data_feed="iex",
        session_start=session_start,
        evaluation_end=datetime(
            2026, 8, 7, 9, 45,
            tzinfo=EASTERN,
        ),
    )

    bot.alpaca.error = ConnectionError(
        "temporary Alpaca failure"
    )

    with pytest.raises(
        ConnectionError,
        match="temporary Alpaca failure",
    ):
        bot._get_fibonacci_intraday_bars(
            date_str="2026-08-07",
            data_feed="iex",
            session_start=session_start,
            evaluation_end=datetime(
                2026, 8, 7, 9, 46,
                tzinfo=EASTERN,
            ),
        )

    bot.alpaca.error = None

    cached = bot._get_fibonacci_intraday_bars(
        date_str="2026-08-07",
        data_feed="iex",
        session_start=session_start,
        evaluation_end=datetime(
            2026, 8, 7, 9, 45,
            tzinfo=EASTERN,
        ),
    )

    assert [
        item["t"]
        for item in cached["OPEN"]
    ] == [
        "2026-08-07T13:30:00Z",
    ]


def test_intraday_cache_separates_symbol_sets():
    bot = make_bot()

    session_start = datetime(
        2026, 8, 7, 9, 30,
        tzinfo=EASTERN,
    )
    evaluation_end = datetime(
        2026, 8, 7, 9, 45,
        tzinfo=EASTERN,
    )

    bot._get_fibonacci_intraday_bars(
        date_str="2026-08-07",
        data_feed="iex",
        session_start=session_start,
        evaluation_end=evaluation_end,
    )

    bot.stocks["RIVN"] = Stock(symbol="RIVN")
    bot.symbols_csv = "OPEN,SOUN,RIVN"

    bot._get_fibonacci_intraday_bars(
        date_str="2026-08-07",
        data_feed="iex",
        session_start=session_start,
        evaluation_end=evaluation_end,
    )

    assert len(bot.alpaca.calls) == 2
