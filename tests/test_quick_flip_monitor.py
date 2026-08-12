from datetime import datetime, timezone

from trading_bot.quick_flip_monitor import (
    QuickFlipMonitor,
    aggregate_completed_5m_candles,
)
from trading_bot.quick_flip_strategy import (
    QuickFlipCandle,
)


UTC = timezone.utc


def candle(
    minute: int,
    open_price: float,
    high: float,
    low: float,
    close: float,
) -> QuickFlipCandle:
    return QuickFlipCandle(
        timestamp=datetime(
            2026,
            8,
            11,
            14,
            minute,
            tzinfo=UTC,
        ),
        open=open_price,
        high=high,
        low=low,
        close=close,
    )


def opening_candle(
    *,
    high: float = 11.50,
    low: float = 10.00,
) -> QuickFlipCandle:
    return QuickFlipCandle(
        timestamp=datetime(
            2026,
            8,
            11,
            13,
            30,
            tzinfo=UTC,
        ),
        open=10.80,
        high=high,
        low=low,
        close=10.20,
    )


def minute_bar(
    minute: int,
    *,
    open_price: float,
    high: float,
    low: float,
    close: float,
    volume: float = 100,
) -> dict:
    return {
        "t": (
            f"2026-08-11T13:{minute:02d}:00Z"
        ),
        "o": open_price,
        "h": high,
        "l": low,
        "c": close,
        "v": volume,
    }


def test_aggregates_complete_five_minute_candle():
    bars = [
        minute_bar(
            45,
            open_price=10.00,
            high=10.20,
            low=9.90,
            close=10.10,
        ),
        minute_bar(
            46,
            open_price=10.10,
            high=10.30,
            low=10.00,
            close=10.20,
        ),
        minute_bar(
            47,
            open_price=10.20,
            high=10.40,
            low=10.10,
            close=10.30,
        ),
        minute_bar(
            48,
            open_price=10.30,
            high=10.50,
            low=10.20,
            close=10.40,
        ),
        minute_bar(
            49,
            open_price=10.40,
            high=10.60,
            low=10.30,
            close=10.50,
        ),
    ]

    result = aggregate_completed_5m_candles(
        bars
    )

    assert len(result) == 1

    five = result[0]

    assert five.open == 10.00
    assert five.high == 10.60
    assert five.low == 9.90
    assert five.close == 10.50
    assert five.volume == 500


def test_incomplete_five_minute_bucket_is_not_emitted():
    bars = [
        minute_bar(
            minute,
            open_price=10.00,
            high=10.20,
            low=9.90,
            close=10.10,
        )
        for minute in range(45, 49)
    ]

    result = aggregate_completed_5m_candles(
        bars
    )

    assert result == []


def test_opening_bar_controls_liquidity_not_5m_bars():
    monitor = QuickFlipMonitor()

    result = monitor.evaluate_five_minute_candles(
        symbol="TEST",
        opening_bar=opening_candle(
            high=10.20,
            low=10.00,
        ),
        atr_14=1.00,
        candles=[
            candle(
                0,
                10.00,
                15.00,
                5.00,
                12.00,
            ),
        ],
    )

    assert result.status == "NO_LIQUIDITY"
    assert result.liquidity_confirmed is False


def test_liquidity_confirmed_enters_watching_state():
    monitor = QuickFlipMonitor()

    result = monitor.evaluate_five_minute_candles(
        symbol="TEST",
        opening_bar=opening_candle(),
        atr_14=1.00,
        candles=[],
    )

    assert result.status == "WATCHING"
    assert result.liquidity_confirmed is True


def test_inside_box_reversal_does_not_invest():
    monitor = QuickFlipMonitor()

    candles = [
        candle(
            0,
            10.60,
            10.70,
            10.30,
            10.40,
        ),
        candle(
            5,
            10.40,
            10.45,
            10.10,
            10.42,
        ),
        candle(
            10,
            10.42,
            10.60,
            10.35,
            10.55,
        ),
    ]

    result = monitor.evaluate_five_minute_candles(
        symbol="TEST",
        opening_bar=opening_candle(),
        atr_14=1.00,
        candles=candles,
    )

    assert result.status == "WATCHING"
    assert result.signal is None


def test_hammer_waits_for_next_completed_candle():
    monitor = QuickFlipMonitor()

    candles = [
        candle(
            0,
            9.95,
            10.00,
            9.50,
            9.60,
        ),
        candle(
            5,
            9.55,
            9.60,
            8.90,
            9.58,
        ),
    ]

    result = monitor.evaluate_five_minute_candles(
        symbol="TEST",
        opening_bar=opening_candle(),
        atr_14=1.00,
        candles=candles,
    )

    assert (
        result.status
        == "WAITING_FOR_CONFIRMATION"
    )
    assert result.pending_pattern == "HAMMER"
    assert result.signal is None


def test_hammer_invests_when_next_candle_breaks_high():
    monitor = QuickFlipMonitor()

    candles = [
        candle(
            0,
            9.95,
            10.00,
            9.50,
            9.60,
        ),
        candle(
            5,
            9.55,
            9.60,
            8.90,
            9.58,
        ),
        candle(
            10,
            9.58,
            9.75,
            9.50,
            9.70,
        ),
    ]

    result = monitor.evaluate_five_minute_candles(
        symbol="TEST",
        opening_bar=opening_candle(),
        atr_14=1.00,
        candles=candles,
    )

    assert result.status == "INVEST"
    assert result.signal is not None

    assert result.signal.pattern == "HAMMER"
    assert result.signal.entry_price == 9.60

    assert (
        result.signal.take_profit_1
        == 10.00
    )
    assert (
        result.signal.take_profit_2
        == 11.50
    )


def test_inverted_hammer_can_invest():
    monitor = QuickFlipMonitor()

    candles = [
        candle(
            0,
            9.90,
            9.95,
            9.40,
            9.50,
        ),
        candle(
            5,
            9.40,
            10.10,
            9.38,
            9.45,
        ),
        candle(
            10,
            9.50,
            10.20,
            9.45,
            10.00,
        ),
    ]

    result = monitor.evaluate_five_minute_candles(
        symbol="TEST",
        opening_bar=opening_candle(),
        atr_14=1.00,
        candles=candles,
    )

    assert result.status == "INVEST"
    assert result.signal is not None

    assert (
        result.signal.pattern
        == "INVERTED_HAMMER"
    )

    assert result.signal.entry_price == 10.10


def test_bullish_engulfing_can_invest():
    monitor = QuickFlipMonitor()

    candles = [
        candle(
            0,
            9.80,
            9.90,
            9.30,
            9.40,
        ),
        candle(
            5,
            9.35,
            10.00,
            9.20,
            9.95,
        ),
    ]

    result = monitor.evaluate_five_minute_candles(
        symbol="TEST",
        opening_bar=opening_candle(),
        atr_14=1.00,
        candles=candles,
    )

    assert result.status == "INVEST"
    assert result.signal is not None

    assert (
        result.signal.pattern
        == "BULLISH_ENGULFING"
    )

    # User-defined engulfing entry:
    # previous red candle high.
    assert result.signal.entry_price == 9.90

    assert (
        result.signal.take_profit_1
        == 10.00
    )
    assert (
        result.signal.take_profit_2
        == 11.50
    )


def test_one_engulfing_candle_must_trade_outside_box():
    monitor = QuickFlipMonitor()

    candles = [
        candle(
            0,
            10.50,
            10.60,
            10.20,
            10.30,
        ),
        candle(
            5,
            10.25,
            10.70,
            10.10,
            10.65,
        ),
    ]

    result = monitor.evaluate_five_minute_candles(
        symbol="TEST",
        opening_bar=opening_candle(),
        atr_14=1.00,
        candles=candles,
    )

    assert result.status == "WATCHING"
    assert result.signal is None


def test_failed_hammer_confirmation_continues_watching():
    monitor = QuickFlipMonitor()

    candles = [
        candle(
            0,
            9.95,
            10.00,
            9.50,
            9.60,
        ),
        candle(
            5,
            9.55,
            9.60,
            8.90,
            9.58,
        ),
        candle(
            10,
            9.58,
            9.59,
            9.40,
            9.50,
        ),
    ]

    result = monitor.evaluate_five_minute_candles(
        symbol="TEST",
        opening_bar=opening_candle(),
        atr_14=1.00,
        candles=candles,
    )

    assert result.status == "WATCHING"
    assert result.signal is None


def test_no_setup_expires_at_cutoff():
    monitor = QuickFlipMonitor()

    result = monitor.evaluate_five_minute_candles(
        symbol="TEST",
        opening_bar=opening_candle(),
        atr_14=1.00,
        candles=[],
        cutoff_reached=True,
    )

    assert result.status == "EXPIRED"
    assert result.signal is None


def test_monitor_has_no_stop_loss_behavior():
    monitor = QuickFlipMonitor()

    candles = [
        candle(
            0,
            9.80,
            9.90,
            9.30,
            9.40,
        ),
        candle(
            5,
            9.35,
            10.00,
            9.20,
            9.95,
        ),
    ]

    result = monitor.evaluate_five_minute_candles(
        symbol="TEST",
        opening_bar=opening_candle(),
        atr_14=1.00,
        candles=candles,
    )

    assert result.signal is not None
    assert not hasattr(
        result.signal,
        "stop_loss",
    )


def test_reconciliation_deduplicates_timestamp():
    from trading_bot.quick_flip_monitor import (
        reconcile_minute_bars,
    )

    original = {
        "t": "2026-08-11T13:45:00Z",
        "o": 10.00,
        "h": 10.20,
        "l": 9.90,
        "c": 10.10,
        "v": 100,
    }

    result = reconcile_minute_bars(
        [original],
        [dict(original)],
    )

    assert len(result) == 1


def test_reconciliation_later_fetch_replaces_old_bar():
    from trading_bot.quick_flip_monitor import (
        reconcile_minute_bars,
    )

    earlier = {
        "t": "2026-08-11T13:45:00Z",
        "o": 10.00,
        "h": 10.20,
        "l": 9.90,
        "c": 10.10,
        "v": 100,
    }

    corrected = {
        "t": "2026-08-11T13:45:00Z",
        "o": 10.00,
        "h": 10.35,
        "l": 9.88,
        "c": 10.30,
        "v": 175,
    }

    result = reconcile_minute_bars(
        [earlier],
        [corrected],
    )

    assert len(result) == 1
    assert result[0]["h"] == 10.35
    assert result[0]["l"] == 9.88
    assert result[0]["c"] == 10.30
    assert result[0]["v"] == 175


def test_reconciliation_adds_late_missing_minute():
    from trading_bot.quick_flip_monitor import (
        reconcile_minute_bars,
    )

    minute_45 = {
        "t": "2026-08-11T13:45:00Z",
        "o": 10.00,
        "h": 10.20,
        "l": 9.90,
        "c": 10.10,
    }

    minute_47 = {
        "t": "2026-08-11T13:47:00Z",
        "o": 10.20,
        "h": 10.30,
        "l": 10.10,
        "c": 10.25,
    }

    late_minute_46 = {
        "t": "2026-08-11T13:46:00Z",
        "o": 10.10,
        "h": 10.25,
        "l": 10.05,
        "c": 10.20,
    }

    result = reconcile_minute_bars(
        [
            minute_45,
            minute_47,
        ],
        [
            late_minute_46,
        ],
    )

    assert [
        bar["t"]
        for bar in result
    ] == [
        "2026-08-11T13:45:00Z",
        "2026-08-11T13:46:00Z",
        "2026-08-11T13:47:00Z",
    ]


def test_reconciliation_does_not_fabricate_missing_minute():
    from trading_bot.quick_flip_monitor import (
        reconcile_minute_bars,
    )

    result = reconcile_minute_bars(
        [
            {
                "t": "2026-08-11T13:45:00Z",
                "o": 10,
                "h": 11,
                "l": 9,
                "c": 10,
            }
        ],
        [
            {
                "t": "2026-08-11T13:47:00Z",
                "o": 10,
                "h": 11,
                "l": 9,
                "c": 10,
            }
        ],
    )

    assert len(result) == 2

    assert all(
        bar["t"]
        != "2026-08-11T13:46:00Z"
        for bar in result
    )


def test_five_minute_candle_requires_reconciled_complete_set():
    from trading_bot.quick_flip_monitor import (
        aggregate_completed_5m_candles,
        reconcile_minute_bars,
    )

    existing = [
        minute_bar(
            45,
            open_price=10.00,
            high=10.20,
            low=9.90,
            close=10.10,
        ),
        minute_bar(
            46,
            open_price=10.10,
            high=10.25,
            low=10.05,
            close=10.20,
        ),
        minute_bar(
            48,
            open_price=10.20,
            high=10.35,
            low=10.15,
            close=10.30,
        ),
        minute_bar(
            49,
            open_price=10.30,
            high=10.40,
            low=10.25,
            close=10.35,
        ),
    ]

    # Missing 13:47 means no 5-minute candle yet.
    assert (
        aggregate_completed_5m_candles(
            existing
        )
        == []
    )

    late_47 = minute_bar(
        47,
        open_price=10.20,
        high=10.30,
        low=10.10,
        close=10.25,
    )

    reconciled = reconcile_minute_bars(
        existing,
        [late_47],
    )

    candles = (
        aggregate_completed_5m_candles(
            reconciled
        )
    )

    assert len(candles) == 1
