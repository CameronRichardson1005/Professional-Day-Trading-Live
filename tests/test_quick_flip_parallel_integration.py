from datetime import datetime
from zoneinfo import ZoneInfo

from trading_bot.bot import TradingBot
from trading_bot.models import Stock
from trading_bot.quick_flip_monitor import (
    QuickFlipMonitor,
)
from trading_bot.strategy import (
    ManipulationStrategy,
)


class FakeAlpaca:
    def __init__(
        self,
        opening_bars,
        atrs,
        minute_bars,
    ):
        self.opening_bars = opening_bars
        self.atrs = atrs
        self.minute_bars = minute_bars

        self.opening_calls = []
        self.atr_calls = []
        self.minute_calls = []

    def get_opening_15min_bars(
        self,
        **kwargs,
    ):
        self.opening_calls.append(
            kwargs
        )
        return self.opening_bars

    def get_previous_day_ranges_all(
        self,
        **kwargs,
    ):
        self.atr_calls.append(
            kwargs
        )
        return self.atrs

    def get_historical_1min_bars(
        self,
        **kwargs,
    ):
        self.minute_calls.append(
            kwargs
        )
        return self.minute_bars


def five_minute_group(
    start_minute,
    *,
    open_price,
    high,
    low,
    close,
):
    """
    Build five one-minute bars whose aggregate exactly
    matches the desired 5-minute candle.
    """
    bars = []

    for offset in range(5):
        minute = (
            start_minute + offset
        )

        if offset == 0:
            minute_open = open_price
        else:
            minute_open = (
                open_price + close
            ) / 2

        if offset == 4:
            minute_close = close
        else:
            minute_close = (
                open_price + close
            ) / 2

        bars.append(
            {
                "t": (
                    "2026-08-11T13:"
                    f"{minute:02d}:00Z"
                ),
                "o": minute_open,
                "h": (
                    high
                    if offset == 2
                    else max(
                        minute_open,
                        minute_close,
                    )
                ),
                "l": (
                    low
                    if offset == 2
                    else min(
                        minute_open,
                        minute_close,
                    )
                ),
                "c": minute_close,
                "v": 100,
            }
        )

    return bars


def build_bot(
    *,
    minute_bars,
    atr=1.00,
):
    bot = TradingBot.__new__(
        TradingBot
    )

    bot.stocks = {
        "TEST": Stock(
            symbol="TEST"
        )
    }

    bot.symbols_csv = "TEST"

    bot.strategy = (
        ManipulationStrategy()
    )

    bot.quick_flip_monitor = (
        QuickFlipMonitor()
    )

    bot.quick_flip_results = {}
    bot.quick_flip_status = {}

    opening = {
        "t": "2026-08-11T13:30:00Z",
        "o": 10.80,
        "h": 11.50,
        "l": 10.00,
        "c": 10.20,
        "v": 500_000,
    }

    bot.alpaca = FakeAlpaca(
        opening_bars={
            "TEST": opening,
        },
        atrs={
            "TEST": atr,
        },
        minute_bars={
            "TEST": minute_bars,
        },
    )

    return bot


def test_parallel_strategies_keep_results_separate():
    minute_bars = []

    minute_bars.extend(
        five_minute_group(
            45,
            open_price=9.95,
            high=10.00,
            low=9.50,
            close=9.60,
        )
    )

    minute_bars.extend(
        five_minute_group(
            50,
            open_price=9.55,
            high=9.60,
            low=8.90,
            close=9.58,
        )
    )

    minute_bars.extend(
        five_minute_group(
            55,
            open_price=9.58,
            high=9.75,
            low=9.50,
            close=9.70,
        )
    )

    bot = build_bot(
        minute_bars=minute_bars
    )

    eastern = ZoneInfo(
        "America/New_York"
    )

    result = (
        bot.calculate_parallel_strategies(
            date_str="2026-08-11",
            evaluation_end=datetime(
                2026,
                8,
                11,
                10,
                0,
                tzinfo=eastern,
            ),
            data_feed="iex",
        )
    )

    # Manipulation owns Stock.signal.
    stock = bot.stocks["TEST"]

    assert stock.signal == "INVEST"

    assert (
        stock.strategy_name
        == "MANIPULATION_OPENING_15M"
    )

    assert stock.stop_loss is not None
    assert (
        stock.trading_stop_loss
        is not None
    )

    # Quick Flip owns a separate result object.
    quick_flip = (
        bot.quick_flip_results[
            "TEST"
        ]
    )

    assert quick_flip is not None
    assert quick_flip.status == "INVEST"
    assert quick_flip.signal is not None

    assert (
        quick_flip.signal.pattern
        == "HAMMER"
    )

    assert (
        quick_flip.signal.entry_price
        == 9.60
    )

    assert (
        quick_flip.signal.take_profit_1
        == 10.00
    )

    assert (
        quick_flip.signal.take_profit_2
        == 11.50
    )

    # Quick Flip contains no automatic stop.
    assert not hasattr(
        quick_flip.signal,
        "stop_loss",
    )

    # Running Quick Flip did not overwrite
    # Manipulation's Stock signal fields.
    assert stock.signal == "INVEST"
    assert stock.limit_buy == 10.00

    assert result == {
        "manipulation": ["TEST"],
        "quick_flip": ["TEST"],
    }


def test_quick_flip_no_liquidity_does_not_change_manipulation():
    bot = build_bot(
        minute_bars=[],
        atr=2.00,
    )

    eastern = ZoneInfo(
        "America/New_York"
    )

    result = (
        bot.calculate_parallel_strategies(
            date_str="2026-08-11",
            evaluation_end=datetime(
                2026,
                8,
                11,
                10,
                0,
                tzinfo=eastern,
            ),
            data_feed="iex",
        )
    )

    # Opening range = 1.50.
    # Quick Flip threshold = 2.50.
    quick_flip = (
        bot.quick_flip_results[
            "TEST"
        ]
    )

    assert quick_flip is not None
    assert (
        quick_flip.status
        == "NO_LIQUIDITY"
    )

    # Manipulation has its own 25%-ATR rule and
    # remains independent.
    assert (
        bot.stocks["TEST"].signal
        == "INVEST"
    )

    assert result == {
        "manipulation": ["TEST"],
        "quick_flip": [],
    }


def test_missing_quick_flip_atr_is_recorded_safely():
    bot = build_bot(
        minute_bars=[]
    )

    bot.alpaca.atrs = {
        "TEST": None,
    }

    bot._calculate_quick_flip_strategy(
        date_str="2026-08-11",
        data_feed="iex",
    )

    assert (
        bot.quick_flip_results[
            "TEST"
        ]
        is None
    )

    assert (
        bot.quick_flip_status[
            "TEST"
        ]
        == "MISSING_ATR14"
    )


def test_quick_flip_uses_0945_to_1100_window():
    bot = build_bot(
        minute_bars=[]
    )

    bot._calculate_quick_flip_strategy(
        date_str="2026-08-11",
        data_feed="iex",
    )

    assert len(
        bot.alpaca.minute_calls
    ) == 1

    call = (
        bot.alpaca.minute_calls[0]
    )

    assert (
        call["start_iso"]
        == "2026-08-11T13:45:00Z"
    )

    assert (
        call["end_iso"]
        == "2026-08-11T15:00:00Z"
    )


def test_quick_flip_never_changes_stock_stop_fields():
    bot = build_bot(
        minute_bars=[]
    )

    stock = bot.stocks["TEST"]

    stock.stop_loss = 8.88
    stock.trading_stop_loss = 8.77

    bot._calculate_quick_flip_strategy(
        date_str="2026-08-11",
        data_feed="iex",
    )

    assert stock.stop_loss == 8.88

    assert (
        stock.trading_stop_loss
        == 8.77
    )
