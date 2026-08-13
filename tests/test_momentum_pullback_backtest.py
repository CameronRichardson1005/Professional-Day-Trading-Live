from datetime import datetime, timezone

import pytest

from trading_bot.momentum_pullback_backtest import (
    build_snapshot,
    evaluate_trade_outcome,
)
from trading_bot.momentum_pullback_strategy import (
    MomentumCandle,
    MomentumPullbackSignal,
)


def candle(
    minute,
    *,
    high,
    low,
    close,
    volume=100_000,
):
    return MomentumCandle(
        timestamp=datetime(
            2026,
            8,
            13,
            10,
            minute,
            tzinfo=timezone.utc,
        ),
        open=close,
        high=high,
        low=low,
        close=close,
        volume=volume,
    )


def signal():
    return MomentumPullbackSignal(
        symbol="TEST",
        signal="INVEST",
        pattern="MICRO_PULLBACK",
        status="CONFIRMED",
        detail="test",
        entry_price=10.00,
        stop_price=9.50,
        target_price=11.00,
        risk_per_share=0.50,
        reward_risk=2.0,
        pullback_candles=2,
        retracement_fraction=0.25,
        trigger_time=candle(
            0,
            high=10.10,
            low=9.90,
            close=10.05,
        ).timestamp,
    )


def test_snapshot_calculates_gain_and_literal_rvol():
    snapshot = build_snapshot(
        symbol="TEST",
        candle=candle(
            0,
            high=11.1,
            low=10.9,
            close=11.0,
        ),
        cumulative_volume=5_000_000,
        previous_close=10.0,
        average_volume_30d=1_000_000,
    )

    assert snapshot.percent_gain == pytest.approx(
        10.0
    )

    assert snapshot.relative_volume == pytest.approx(
        5.0
    )


def test_target_exit_returns_two_r():
    candles = [
        candle(
            0,
            high=10.1,
            low=9.9,
            close=10.05,
        ),
        candle(
            1,
            high=11.1,
            low=9.8,
            close=10.9,
        ),
    ]

    result = evaluate_trade_outcome(
        candles=candles,
        trigger_index=0,
        signal=signal(),
    )

    assert result[0] == "TARGET"
    assert result[1] == 11.0
    assert result[4] == pytest.approx(
        2.0
    )


def test_stop_exit_returns_minus_one_r():
    candles = [
        candle(
            0,
            high=10.1,
            low=9.9,
            close=10.05,
        ),
        candle(
            1,
            high=10.2,
            low=9.4,
            close=9.6,
        ),
    ]

    result = evaluate_trade_outcome(
        candles=candles,
        trigger_index=0,
        signal=signal(),
    )

    assert result[0] == "STOP"
    assert result[1] == 9.5
    assert result[4] == pytest.approx(
        -1.0
    )


def test_same_bar_target_and_stop_is_conservative_stop():
    candles = [
        candle(
            0,
            high=10.1,
            low=9.9,
            close=10.05,
        ),
        candle(
            1,
            high=11.2,
            low=9.4,
            close=10.5,
        ),
    ]

    result = evaluate_trade_outcome(
        candles=candles,
        trigger_index=0,
        signal=signal(),
    )

    assert result[0] == "STOP"


def test_unresolved_trade_exits_at_final_bar():
    candles = [
        candle(
            0,
            high=10.1,
            low=9.9,
            close=10.05,
        ),
        candle(
            1,
            high=10.4,
            low=9.8,
            close=10.25,
        ),
        candle(
            2,
            high=10.5,
            low=9.8,
            close=10.30,
        ),
    ]

    result = evaluate_trade_outcome(
        candles=candles,
        trigger_index=0,
        signal=signal(),
    )

    assert result[0] == "TIME_EXIT"
    assert result[1] == 10.30

    assert result[4] == pytest.approx(
        0.60
    )
