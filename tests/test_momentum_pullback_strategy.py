from datetime import datetime

import pytest

from trading_bot.momentum_pullback_strategy import (
    MomentumCandle,
    MomentumPullbackStrategy,
)


def candle(
    minute,
    open_price,
    high,
    low,
    close,
    volume,
    *,
    hour=10,
):
    return MomentumCandle(
        timestamp=datetime(
            2026,
            8,
            13,
            hour,
            minute,
        ),
        open=open_price,
        high=high,
        low=low,
        close=close,
        volume=volume,
    )


def valid_micro_pullback():
    impulse = candle(
        0,
        10.00,
        11.10,
        9.90,
        11.00,
        100_000,
    )

    pullback = [
        candle(
            1,
            11.00,
            11.00,
            10.65,
            10.80,
            60_000,
        ),
        candle(
            2,
            10.80,
            10.90,
            10.55,
            10.75,
            50_000,
        ),
    ]

    trigger = candle(
        3,
        10.75,
        10.95,
        10.70,
        10.92,
        75_000,
    )

    return impulse, pullback, trigger


def test_micro_pullback_confirms_break_of_prior_high():
    strategy = MomentumPullbackStrategy()

    impulse, pullback, trigger = (
        valid_micro_pullback()
    )

    signal = strategy.evaluate_micro_pullback(
        symbol="TEST",
        impulse=impulse,
        pullback=pullback,
        trigger=trigger,
    )

    assert signal.signal == "INVEST"
    assert signal.pattern == "MICRO_PULLBACK"
    assert signal.entry_price == 10.90
    assert signal.stop_price == 10.55

    assert signal.risk_per_share == pytest.approx(
        0.35
    )

    assert signal.target_price == pytest.approx(
        11.60
    )

    assert signal.reward_risk == 2.0


def test_micro_pullback_rejects_more_than_three_candles():
    strategy = MomentumPullbackStrategy()

    impulse, pullback, trigger = (
        valid_micro_pullback()
    )

    pullback = pullback * 2

    signal = strategy.evaluate_micro_pullback(
        symbol="TEST",
        impulse=impulse,
        pullback=pullback,
        trigger=trigger,
    )

    assert signal.signal == "NO INVEST"
    assert signal.status == (
        "INVALID_PULLBACK_LENGTH"
    )


def test_micro_pullback_rejects_deep_retracement():
    strategy = MomentumPullbackStrategy()

    impulse, pullback, trigger = (
        valid_micro_pullback()
    )

    deep = [
        candle(
            1,
            11.00,
            11.00,
            10.30,
            10.50,
            50_000,
        ),
    ]

    signal = strategy.evaluate_micro_pullback(
        symbol="TEST",
        impulse=impulse,
        pullback=deep,
        trigger=trigger,
    )

    assert signal.signal == "NO INVEST"
    assert signal.status == "PULLBACK_TOO_DEEP"


def test_micro_pullback_requires_volume_contraction():
    strategy = MomentumPullbackStrategy()

    impulse, pullback, trigger = (
        valid_micro_pullback()
    )

    loud_pullback = [
        candle(
            1,
            11.00,
            11.00,
            10.65,
            10.80,
            120_000,
        ),
    ]

    signal = strategy.evaluate_micro_pullback(
        symbol="TEST",
        impulse=impulse,
        pullback=loud_pullback,
        trigger=trigger,
    )

    assert signal.signal == "NO INVEST"
    assert signal.status == (
        "NO_VOLUME_CONTRACTION"
    )


def test_micro_pullback_requires_new_high_break():
    strategy = MomentumPullbackStrategy()

    impulse, pullback, _ = (
        valid_micro_pullback()
    )

    weak_trigger = candle(
        3,
        10.75,
        10.89,
        10.70,
        10.85,
        70_000,
    )

    signal = strategy.evaluate_micro_pullback(
        symbol="TEST",
        impulse=impulse,
        pullback=pullback,
        trigger=weak_trigger,
    )

    assert signal.signal == "NO INVEST"
    assert signal.status == "NO_NEW_HIGH_BREAK"


def test_entry_after_1100_is_rejected():
    strategy = MomentumPullbackStrategy()

    impulse, pullback, _ = (
        valid_micro_pullback()
    )

    late = candle(
        1,
        10.75,
        10.95,
        10.70,
        10.92,
        70_000,
        hour=11,
    )

    signal = strategy.evaluate_micro_pullback(
        symbol="TEST",
        impulse=impulse,
        pullback=pullback,
        trigger=late,
    )

    assert signal.signal == "NO INVEST"
    assert signal.status == "AFTER_CUTOFF"


def test_flat_top_breakout_confirms_at_resistance():
    strategy = MomentumPullbackStrategy(
        flat_top_tolerance=0.003,
    )

    base = [
        candle(
            0,
            9.75,
            10.00,
            9.70,
            9.90,
            50_000,
        ),
        candle(
            1,
            9.88,
            10.01,
            9.75,
            9.95,
            45_000,
        ),
        candle(
            2,
            9.92,
            10.00,
            9.80,
            9.96,
            40_000,
        ),
    ]

    breakout = candle(
        3,
        9.97,
        10.15,
        9.95,
        10.12,
        90_000,
    )

    signal = strategy.evaluate_flat_top(
        symbol="TEST",
        base=base,
        breakout=breakout,
    )

    assert signal.signal == "INVEST"
    assert signal.pattern == "FLAT_TOP"
    assert signal.entry_price == 10.01
    assert signal.stop_price == 9.70

    assert signal.target_price == pytest.approx(
        10.63
    )


def test_flat_top_rejects_uneven_resistance():
    strategy = MomentumPullbackStrategy(
        flat_top_tolerance=0.002,
    )

    base = [
        candle(
            0,
            9.70,
            10.00,
            9.60,
            9.90,
            50_000,
        ),
        candle(
            1,
            9.90,
            10.10,
            9.70,
            10.00,
            45_000,
        ),
    ]

    breakout = candle(
        2,
        10.00,
        10.20,
        9.95,
        10.15,
        80_000,
    )

    signal = strategy.evaluate_flat_top(
        symbol="TEST",
        base=base,
        breakout=breakout,
    )

    assert signal.signal == "NO INVEST"
    assert signal.status == "NOT_FLAT_TOP"
