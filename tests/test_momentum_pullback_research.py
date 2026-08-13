from datetime import datetime

from trading_bot.momentum_pullback_research import (
    find_momentum_signal,
    rank_snapshots,
)
from trading_bot.momentum_pullback_scanner import (
    MomentumPullbackScanner,
    MomentumStockSnapshot,
)
from trading_bot.momentum_pullback_strategy import (
    MomentumCandle,
    MomentumPullbackStrategy,
)


def snapshot(
    symbol,
    gain,
    rvol,
):
    return MomentumStockSnapshot(
        symbol=symbol,
        price=8.0,
        percent_gain=gain,
        relative_volume=rvol,
        current_volume=1_000_000,
        average_volume_30d=100_000,
    )


def candle(
    minute,
    o,
    h,
    l,
    c,
    v,
):
    return MomentumCandle(
        timestamp=datetime(
            2026,
            8,
            13,
            10,
            minute,
        ),
        open=o,
        high=h,
        low=l,
        close=c,
        volume=v,
    )


def test_rank_snapshots_uses_top_three_percentage_gainers():
    scanner = MomentumPullbackScanner()

    ranked = rank_snapshots(
        snapshots=[
            snapshot("AAA", 15, 8),
            snapshot("BBB", 30, 5),
            snapshot("CCC", 20, 10),
            snapshot("DDD", 12, 20),
        ],
        scanner=scanner,
    )

    assert [
        item.snapshot.symbol
        for item in ranked
    ] == [
        "BBB",
        "CCC",
        "AAA",
    ]


def test_rank_snapshots_excludes_sub_five_rvol():
    scanner = MomentumPullbackScanner()

    ranked = rank_snapshots(
        snapshots=[
            snapshot("PASS", 20, 6),
            snapshot("FAIL", 40, 4.99),
        ],
        scanner=scanner,
    )

    assert [
        item.snapshot.symbol
        for item in ranked
    ] == ["PASS"]


def test_find_signal_detects_micro_pullback():
    strategy = MomentumPullbackStrategy()

    candles = [
        candle(
            0,
            10.00,
            11.10,
            9.90,
            11.00,
            100_000,
        ),
        candle(
            5,
            11.00,
            11.00,
            10.65,
            10.80,
            60_000,
        ),
        candle(
            10,
            10.80,
            10.90,
            10.55,
            10.75,
            50_000,
        ),
        candle(
            15,
            10.75,
            10.95,
            10.70,
            10.92,
            75_000,
        ),
    ]

    signal = find_momentum_signal(
        symbol="TEST",
        candles=candles,
        trigger_index=3,
        strategy=strategy,
    )

    assert signal is not None
    assert signal.signal == "INVEST"
    assert signal.pattern == (
        "MICRO_PULLBACK"
    )


def test_find_signal_detects_flat_top():
    strategy = MomentumPullbackStrategy(
        flat_top_tolerance=0.003,
    )

    candles = [
        candle(
            0,
            9.75,
            10.00,
            9.70,
            9.90,
            50_000,
        ),
        candle(
            5,
            9.88,
            10.01,
            9.75,
            9.95,
            45_000,
        ),
        candle(
            10,
            9.92,
            10.00,
            9.80,
            9.96,
            40_000,
        ),
        candle(
            15,
            9.97,
            10.15,
            9.95,
            10.12,
            90_000,
        ),
    ]

    signal = find_momentum_signal(
        symbol="TEST",
        candles=candles,
        trigger_index=3,
        strategy=strategy,
    )

    assert signal is not None
    assert signal.signal == "INVEST"
    assert signal.pattern == "FLAT_TOP"
