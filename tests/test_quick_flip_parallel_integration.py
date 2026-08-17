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


class FakeWebullStrategyMarketData:
    def __init__(
        self,
        opening_bars,
        atrs,
        five_minute_bars,
    ):
        self.opening_bars = opening_bars
        self.atrs = atrs
        self.five_minute_bars = five_minute_bars

        self.opening_calls = []
        self.atr_calls = []
        self.five_minute_calls = []

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

    def get_historical_5min_bars(
        self,
        **kwargs,
    ):
        self.five_minute_calls.append(
            kwargs
        )
        return self.five_minute_bars


class FakeAlpaca:
    pass


def five_minute_bar(
    start_minute,
    *,
    open_price,
    high,
    low,
    close,
):
    """
    Build one native Webull 5-minute OHLC bar.

    Webull timestamps the candle at the beginning of
    its five-minute interval.
    """
    return {
        "t": (
            "2026-08-11T13:"
            f"{start_minute:02d}:00Z"
        ),
        "o": open_price,
        "h": high,
        "l": low,
        "c": close,
        "v": 500,
    }


def build_bot(
    *,
    five_minute_bars,
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

    bot.webull_strategy_market_data = (
        FakeWebullStrategyMarketData(
            opening_bars={
                "TEST": opening,
            },
            atrs={
                "TEST": atr,
            },
            five_minute_bars={
                "TEST": five_minute_bars,
            },
        )
    )

    bot.alpaca = FakeAlpaca()

    return bot


def test_parallel_strategies_keep_results_separate():
    five_minute_bars = [
        five_minute_bar(
            45,
            open_price=9.95,
            high=10.00,
            low=9.50,
            close=9.60,
        ),
        five_minute_bar(
            50,
            open_price=9.55,
            high=9.60,
            low=8.90,
            close=9.58,
        ),
        five_minute_bar(
            55,
            open_price=9.58,
            high=9.75,
            low=9.50,
            close=9.70,
        ),
    ]

    bot = build_bot(
        five_minute_bars=five_minute_bars
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


def test_shared_opening_gate_keeps_strategies_independent():
    bot = build_bot(
        five_minute_bars=[],
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
    # Shared 25%-ATR threshold = 0.50.
    # Therefore the opening candle qualifies for
    # both Manipulation and Quick Flip.
    quick_flip = (
        bot.quick_flip_results[
            "TEST"
        ]
    )

    assert quick_flip is not None
    assert (
        quick_flip.status
        == "WATCHING"
    )
    assert (
        quick_flip.liquidity_confirmed
        is True
    )

    # Manipulation still owns Stock.signal and
    # remains independent of Quick Flip's later setup.
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
        five_minute_bars=[]
    )

    bot.webull_strategy_market_data.atrs = {
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
        five_minute_bars=[]
    )

    bot._calculate_quick_flip_strategy(
        date_str="2026-08-11",
        data_feed="iex",
    )

    assert len(
        bot.webull_strategy_market_data.five_minute_calls
    ) == 1

    call = (
        bot.webull_strategy_market_data.five_minute_calls[0]
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
        five_minute_bars=[]
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
