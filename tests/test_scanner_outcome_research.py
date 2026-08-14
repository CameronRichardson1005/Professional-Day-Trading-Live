from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from trading_bot.models import Stock
from trading_bot.quick_flip_strategy import (
    QuickFlipSignal,
)
from trading_bot.scanner_outcome_research import (
    evaluate_manipulation_realized_outcome,
    evaluate_quick_flip_realized_outcome,
)


UTC = ZoneInfo("UTC")


def bar(
    timestamp,
    *,
    open_price,
    high,
    low,
    close,
):
    return {
        "t": timestamp,
        "o": open_price,
        "h": high,
        "l": low,
        "c": close,
        "v": 1000,
    }


def quick_flip_signal():
    return QuickFlipSignal(
        symbol="TEST",
        signal="INVEST",
        pattern="HAMMER",
        status="CONFIRMED",
        detail="test",
        entry_price=9.50,
        take_profit_1=10.00,
        take_profit_2=11.00,
        opening_range_high=11.00,
        opening_range_low=10.00,
        opening_range_size=1.00,
        atr_14=2.00,
        liquidity_threshold=0.50,
        reversal_time=datetime(
            2026,
            8,
            13,
            13,
            50,
            tzinfo=UTC,
        ),
        confirmation_time=datetime(
            2026,
            8,
            13,
            13,
            55,
            tzinfo=UTC,
        ),
    )


def test_manipulation_realized_outcome_reuses_preserved_trade():
    stock = Stock(
        symbol="TEST"
    )

    stock.signal = "INVEST"
    stock.limit_buy = 10.00
    stock.limit_sell = 10.50
    stock.trading_stop_loss = 9.75

    bars = [
        bar(
            "2026-08-13T13:45:00Z",
            open_price=10.20,
            high=10.25,
            low=9.95,
            close=10.10,
        ),
        bar(
            "2026-08-13T13:50:00Z",
            open_price=10.10,
            high=10.60,
            low=10.05,
            close=10.50,
        ),
    ]

    result = (
        evaluate_manipulation_realized_outcome(
            stock=stock,
            bars=bars,
        )
    )

    assert result is not None
    assert result.filled is True
    assert result.outcome == "TARGET"
    assert result.exit_price == pytest.approx(
        10.50
    )
    assert result.return_pct == pytest.approx(
        5.0
    )


def test_manipulation_non_signal_has_no_realized_trade():
    stock = Stock(
        symbol="TEST"
    )

    stock.signal = "NO INVEST"

    assert (
        evaluate_manipulation_realized_outcome(
            stock=stock,
            bars=[],
        )
        is None
    )


def test_quick_flip_records_targets_mfe_mae_and_endpoint():
    signal = quick_flip_signal()

    bars = [
        bar(
            "2026-08-13T13:54:00Z",
            open_price=9.00,
            high=20.00,
            low=1.00,
            close=9.00,
        ),
        bar(
            "2026-08-13T13:55:00Z",
            open_price=9.40,
            high=9.60,
            low=9.30,
            close=9.55,
        ),
        bar(
            "2026-08-13T14:00:00Z",
            open_price=9.55,
            high=10.20,
            low=9.45,
            close=10.10,
        ),
        bar(
            "2026-08-13T15:00:00Z",
            open_price=10.10,
            high=11.20,
            low=9.90,
            close=10.50,
        ),
    ]

    result = (
        evaluate_quick_flip_realized_outcome(
            signal=signal,
            minute_bars=bars,
        )
    )

    assert result is not None
    assert result.filled is True

    # The enormous pre-confirmation bar must be ignored.
    assert (
        result.maximum_favorable_excursion_pct
        == pytest.approx(
            (11.20 - 9.50)
            / 9.50
            * 100,
            abs=1e-4,
        )
    )

    assert (
        result.maximum_adverse_excursion_pct
        == pytest.approx(
            (9.30 - 9.50)
            / 9.50
            * 100,
            abs=1e-4,
        )
    )

    assert result.tp1_hit is True
    assert result.tp2_hit is True

    assert result.endpoint_price == pytest.approx(
        10.50
    )

    assert (
        result.endpoint_return_pct
        == pytest.approx(
            (10.50 - 9.50)
            / 9.50
            * 100,
            abs=1e-4,
        )
    )


def test_quick_flip_fill_waits_until_entry_is_reached():
    signal = quick_flip_signal()

    bars = [
        bar(
            "2026-08-13T13:55:00Z",
            open_price=9.20,
            high=9.40,
            low=9.10,
            close=9.30,
        ),
        bar(
            "2026-08-13T13:56:00Z",
            open_price=9.30,
            high=9.55,
            low=9.25,
            close=9.50,
        ),
    ]

    result = (
        evaluate_quick_flip_realized_outcome(
            signal=signal,
            minute_bars=bars,
        )
    )

    assert result is not None
    assert result.filled is True

    assert result.fill_time == datetime(
        2026,
        8,
        13,
        13,
        56,
        tzinfo=UTC,
    )


def test_quick_flip_reports_not_filled():
    signal = quick_flip_signal()

    bars = [
        bar(
            "2026-08-13T13:55:00Z",
            open_price=9.20,
            high=9.40,
            low=9.10,
            close=9.30,
        ),
        bar(
            "2026-08-13T14:00:00Z",
            open_price=9.30,
            high=9.49,
            low=9.20,
            close=9.45,
        ),
    ]

    result = (
        evaluate_quick_flip_realized_outcome(
            signal=signal,
            minute_bars=bars,
        )
    )

    assert result is not None
    assert result.filled is False
    assert result.fill_time is None
    assert result.tp1_hit is False
    assert result.tp2_hit is False
    assert (
        result.endpoint_return_pct
        is None
    )
