from datetime import datetime

from trading_bot.quick_flip_strategy import (
    QuickFlipCandle,
    QuickFlipStrategy,
)


def make_candle(
    open_price: float,
    high: float,
    low: float,
    close: float,
    minute: int = 0,
) -> QuickFlipCandle:
    return QuickFlipCandle(
        timestamp=datetime(
            2026,
            8,
            11,
            10,
            minute,
        ),
        open=open_price,
        high=high,
        low=low,
        close=close,
    )


def test_opening_15m_candle_creates_box():
    strategy = QuickFlipStrategy()

    opening = make_candle(
        10.00,
        10.80,
        9.40,
        9.70,
    )

    box = strategy.build_opening_range(
        opening
    )

    assert box.high == 10.80
    assert box.low == 9.40
    assert round(box.range, 2) == 1.40


def test_opening_candle_is_liquidity_at_25_percent_atr():
    strategy = QuickFlipStrategy()

    opening = make_candle(
        10.00,
        11.25,
        10.00,
        10.50,
    )

    box = strategy.build_opening_range(
        opening
    )

    assert strategy.is_liquidity_opening_candle(
        box,
        atr_14=1.00,
    )


def test_opening_candle_below_threshold_is_not_liquidity():
    strategy = QuickFlipStrategy()

    opening = make_candle(
        10.00,
        10.20,
        10.00,
        10.10,
    )

    box = strategy.build_opening_range(
        opening
    )

    assert not strategy.is_liquidity_opening_candle(
        box,
        atr_14=1.00,
    )


def test_five_minute_candle_does_not_determine_liquidity():
    strategy = QuickFlipStrategy()

    opening = make_candle(
        10.00,
        10.20,
        10.00,
        10.10,
    )

    box = strategy.build_opening_range(
        opening
    )

    huge_five_minute_move = make_candle(
        10.00,
        12.00,
        8.00,
        11.00,
        minute=5,
    )

    assert huge_five_minute_move.range == 4.00

    assert not strategy.is_liquidity_opening_candle(
        box,
        atr_14=1.00,
    )


def test_outside_lower_box_requires_trade_below_box_low():
    strategy = QuickFlipStrategy()

    opening = make_candle(
        10.00,
        11.50,
        10.00,
        10.50,
    )

    box = strategy.build_opening_range(
        opening
    )

    inside = make_candle(
        10.20,
        10.80,
        10.05,
        10.40,
    )

    outside = make_candle(
        10.20,
        10.40,
        9.80,
        10.10,
    )

    assert not strategy.is_outside_lower_box(
        inside,
        box,
    )

    assert strategy.is_outside_lower_box(
        outside,
        box,
    )


def test_hammer_detection():
    strategy = QuickFlipStrategy()

    hammer = make_candle(
        9.80,
        9.82,
        9.10,
        9.75,
    )

    assert strategy.is_hammer(
        hammer
    )


def test_inverted_hammer_detection():
    strategy = QuickFlipStrategy()

    inverted_hammer = make_candle(
        9.30,
        10.10,
        9.28,
        9.35,
    )

    assert strategy.is_inverted_hammer(
        inverted_hammer
    )


def test_bullish_engulfing_requires_full_candle_engulf():
    strategy = QuickFlipStrategy()

    red = make_candle(
        9.80,
        9.90,
        9.30,
        9.40,
    )

    green = make_candle(
        9.35,
        10.00,
        9.20,
        9.90,
        minute=5,
    )

    assert strategy.is_bullish_engulfing(
        red,
        green,
    )


def test_partial_engulfing_is_rejected():
    strategy = QuickFlipStrategy()

    red = make_candle(
        9.80,
        9.90,
        9.30,
        9.40,
    )

    green = make_candle(
        9.35,
        9.85,
        9.35,
        9.80,
        minute=5,
    )

    assert not strategy.is_bullish_engulfing(
        red,
        green,
    )


def test_confirmed_hammer_entry_is_reversal_high():
    strategy = QuickFlipStrategy()

    opening = make_candle(
        10.50,
        11.50,
        10.00,
        10.20,
    )

    box = strategy.build_opening_range(
        opening
    )

    red = make_candle(
        9.95,
        10.00,
        9.50,
        9.60,
    )

    hammer = make_candle(
        9.55,
        9.60,
        8.90,
        9.58,
        minute=5,
    )

    confirmation = make_candle(
        9.60,
        9.80,
        9.55,
        9.75,
        minute=10,
    )

    result = strategy.evaluate_hammer_setup(
        symbol="TEST",
        atr_14=1.00,
        opening_range=box,
        previous=red,
        reversal=hammer,
        confirmation=confirmation,
    )

    assert result.signal == "INVEST"
    assert result.pattern == "HAMMER"

    assert result.entry_price == 9.60

    assert result.take_profit_1 == 10.00
    assert result.take_profit_2 == 11.50


def test_hammer_requires_following_break():
    strategy = QuickFlipStrategy()

    opening = make_candle(
        10.50,
        11.50,
        10.00,
        10.20,
    )

    box = strategy.build_opening_range(
        opening
    )

    red = make_candle(
        9.95,
        10.00,
        9.50,
        9.60,
    )

    hammer = make_candle(
        9.55,
        9.60,
        8.90,
        9.58,
        minute=5,
    )

    no_break = make_candle(
        9.58,
        9.59,
        9.50,
        9.57,
        minute=10,
    )

    result = strategy.evaluate_hammer_setup(
        symbol="TEST",
        atr_14=1.00,
        opening_range=box,
        previous=red,
        reversal=hammer,
        confirmation=no_break,
    )

    assert result.signal == "NO INVEST"
    assert result.status == "WAITING_FOR_BREAK"


def test_engulfing_entry_waits_for_break_of_engulfing_high():
    strategy = QuickFlipStrategy()

    opening = make_candle(
        10.50,
        11.50,
        10.00,
        10.20,
    )

    box = strategy.build_opening_range(
        opening
    )

    red = make_candle(
        9.80,
        9.90,
        9.30,
        9.40,
    )

    engulfing = make_candle(
        9.35,
        9.95,
        9.20,
        9.90,
        minute=5,
    )

    confirmation = make_candle(
        9.90,
        9.98,
        9.85,
        9.96,
        minute=10,
    )

    result = strategy.evaluate_engulfing_setup(
        symbol="TEST",
        atr_14=1.00,
        opening_range=box,
        previous=red,
        engulfing=engulfing,
        confirmation=confirmation,
    )

    assert result.signal == "INVEST"

    assert (
        result.pattern
        == "BULLISH_ENGULFING"
    )

    assert result.entry_price == 9.95

    assert (
        result.confirmation_time
        == confirmation.timestamp
    )

    assert result.take_profit_1 == 10.00
    assert result.take_profit_2 == 11.50


def test_engulfing_requires_following_break():
    strategy = QuickFlipStrategy()

    opening = make_candle(
        10.50,
        11.50,
        10.00,
        10.20,
    )

    box = strategy.build_opening_range(
        opening
    )

    red = make_candle(
        9.80,
        9.90,
        9.30,
        9.40,
    )

    engulfing = make_candle(
        9.35,
        9.95,
        9.20,
        9.90,
        minute=5,
    )

    no_break = make_candle(
        9.90,
        9.95,
        9.80,
        9.90,
        minute=10,
    )

    result = strategy.evaluate_engulfing_setup(
        symbol="TEST",
        atr_14=1.00,
        opening_range=box,
        previous=red,
        engulfing=engulfing,
        confirmation=no_break,
    )

    assert result.signal == "NO INVEST"

    assert (
        result.status
        == "WAITING_FOR_BREAK"
    )


def test_quick_flip_signal_contains_no_stop_loss():
    strategy = QuickFlipStrategy()

    opening = make_candle(
        10.50,
        11.50,
        10.00,
        10.20,
    )

    box = strategy.build_opening_range(
        opening
    )

    red = make_candle(
        9.80,
        9.90,
        9.30,
        9.40,
    )

    engulfing = make_candle(
        9.35,
        9.95,
        9.20,
        9.90,
        minute=5,
    )

    confirmation = make_candle(
        9.90,
        9.98,
        9.85,
        9.96,
        minute=10,
    )

    result = strategy.evaluate_engulfing_setup(
        symbol="TEST",
        atr_14=1.00,
        opening_range=box,
        previous=red,
        engulfing=engulfing,
        confirmation=confirmation,
    )

    assert result.signal == "INVEST"

    assert not hasattr(
        result,
        "stop_loss",
    )


def test_hammer_entry_inside_box_is_rejected():
    strategy = QuickFlipStrategy()

    opening = make_candle(
        10.00,
        11.00,
        10.00,
        10.50,
    )

    box = strategy.build_opening_range(
        opening
    )

    previous = make_candle(
        9.90,
        9.95,
        9.70,
        9.75,
        minute=45,
    )

    reversal = make_candle(
        9.40,
        10.10,
        9.38,
        9.45,
        minute=50,
    )

    confirmation = make_candle(
        9.50,
        10.20,
        9.45,
        10.00,
        minute=55,
    )

    result = strategy.evaluate_hammer_setup(
        symbol="TEST",
        atr_14=1.0,
        opening_range=box,
        previous=previous,
        reversal=reversal,
        confirmation=confirmation,
    )

    assert result.signal == "NO INVEST"
    assert result.status == "ENTRY_INSIDE_BOX"


def test_engulfing_entry_inside_box_is_rejected():
    strategy = QuickFlipStrategy()

    opening = make_candle(
        10.00,
        11.00,
        10.00,
        10.50,
    )

    box = strategy.build_opening_range(
        opening
    )

    previous = make_candle(
        10.05,
        10.10,
        9.70,
        9.80,
        minute=45,
    )

    engulfing = make_candle(
        9.75,
        10.20,
        9.60,
        10.15,
        minute=50,
    )

    confirmation = make_candle(
        10.15,
        10.30,
        10.10,
        10.25,
        minute=55,
    )

    result = strategy.evaluate_engulfing_setup(
        symbol="TEST",
        atr_14=1.0,
        opening_range=box,
        previous=previous,
        engulfing=engulfing,
        confirmation=confirmation,
    )

    assert result.signal == "NO INVEST"

    assert (
        result.status
        == "ENTRY_INSIDE_BOX"
    )
