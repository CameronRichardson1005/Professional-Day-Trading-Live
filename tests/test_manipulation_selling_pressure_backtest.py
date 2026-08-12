import pytest

from trading_bot.manipulation_selling_pressure_backtest import (
    calculate_research_trading_stop,
    evaluate_entry_outcome,
)


def bar(
    minute,
    *,
    high,
    low,
):
    return {
        "t": (
            f"2026-08-12T"
            f"13:{minute:02d}:00Z"
        ),
        "o": high,
        "h": high,
        "l": low,
        "c": low,
        "v": 1000,
    }


def test_not_filled_when_price_never_reaches_entry():
    result = evaluate_entry_outcome(
        bars=[
            bar(
                45,
                high=10.50,
                low=10.10,
            ),
            bar(
                50,
                high=10.40,
                low=10.05,
            ),
        ],
        adjustment=0.10,
        entry=10.00,
        target=10.50,
        trading_stop=9.80,
    )

    assert result.filled is False
    assert result.outcome == "NOT_FILLED"


def test_target_after_fill():
    result = evaluate_entry_outcome(
        bars=[
            bar(
                45,
                high=10.20,
                low=9.95,
            ),
            bar(
                50,
                high=10.60,
                low=10.05,
            ),
        ],
        adjustment=0.10,
        entry=10.00,
        target=10.50,
        trading_stop=9.80,
    )

    assert result.filled is True
    assert result.outcome == "TARGET"
    assert result.exit_price == 10.50


def test_stop_after_fill():
    result = evaluate_entry_outcome(
        bars=[
            bar(
                45,
                high=10.20,
                low=9.95,
            ),
            bar(
                50,
                high=10.10,
                low=9.70,
            ),
        ],
        adjustment=0.10,
        entry=10.00,
        target=10.50,
        trading_stop=9.80,
    )

    assert result.filled is True
    assert result.outcome == "STOP"
    assert result.exit_price == 9.80


def test_same_bar_stop_and_target_is_conservative_stop():
    result = evaluate_entry_outcome(
        bars=[
            bar(
                45,
                high=10.60,
                low=9.70,
            ),
        ],
        adjustment=0.10,
        entry=10.00,
        target=10.50,
        trading_stop=9.80,
    )

    assert result.outcome == "STOP"


def test_research_stop_is_below_entry():
    stop = calculate_research_trading_stop(
        entry=10.00,
        target=10.50,
    )

    assert stop < 10.00


def test_lower_entry_changes_stop():
    normal = calculate_research_trading_stop(
        entry=10.00,
        target=10.50,
    )

    lower = calculate_research_trading_stop(
        entry=9.90,
        target=10.50,
    )

    assert lower < normal


def test_after_hours_bar_does_not_resolve_trade():
    bars = [
        {
            "t": "2026-08-12T13:45:00Z",
            "o": 10.10,
            "h": 10.20,
            "l": 9.95,
            "c": 10.10,
            "v": 1000,
        },
        {
            # 16:00 ET during daylight saving time.
            "t": "2026-08-12T20:00:00Z",
            "o": 10.20,
            "h": 11.00,
            "l": 10.10,
            "c": 10.90,
            "v": 1000,
        },
    ]

    result = evaluate_entry_outcome(
        bars=bars,
        adjustment=0.0,
        entry=10.00,
        target=10.50,
        trading_stop=9.80,
    )

    assert result.filled is True
    assert result.outcome == "OPEN"
