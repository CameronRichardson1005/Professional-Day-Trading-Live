import pytest

from trading_bot.manipulation_selling_pressure_no_stop import (
    evaluate_no_stop_outcome,
)


def bar(
    minute,
    *,
    open_price,
    high,
    low,
    close,
):
    return {
        "t": (
            f"2026-08-12T"
            f"13:{minute:02d}:00Z"
        ),
        "o": open_price,
        "h": high,
        "l": low,
        "c": close,
        "v": 1000,
    }


def test_no_stop_target_after_entry():
    result = evaluate_no_stop_outcome(
        bars=[
            bar(
                45,
                open_price=10.10,
                high=10.20,
                low=9.95,
                close=10.05,
            ),
            bar(
                50,
                open_price=10.05,
                high=10.60,
                low=9.90,
                close=10.50,
            ),
        ],
        adjustment=0.0,
        entry=10.00,
        target=10.50,
    )

    assert result.filled is True
    assert result.outcome == "TARGET"
    assert result.exit_price == 10.50
    assert result.return_pct == pytest.approx(
        5.0
    )


def test_no_stop_exits_at_end_of_day():
    result = evaluate_no_stop_outcome(
        bars=[
            bar(
                45,
                open_price=10.10,
                high=10.20,
                low=9.95,
                close=10.05,
            ),
            bar(
                50,
                open_price=10.05,
                high=10.20,
                low=9.70,
                close=9.80,
            ),
            bar(
                55,
                open_price=9.80,
                high=10.10,
                low=9.75,
                close=9.90,
            ),
        ],
        adjustment=0.0,
        entry=10.00,
        target=10.50,
    )

    assert result.filled is True
    assert result.outcome == "EOD_EXIT"
    assert result.exit_price == 9.90
    assert result.return_pct == pytest.approx(
        -1.0
    )


def test_no_stop_records_adverse_excursion():
    result = evaluate_no_stop_outcome(
        bars=[
            bar(
                45,
                open_price=10.10,
                high=10.20,
                low=9.90,
                close=10.00,
            ),
            bar(
                50,
                open_price=10.00,
                high=10.60,
                low=9.50,
                close=10.55,
            ),
        ],
        adjustment=0.0,
        entry=10.00,
        target=10.50,
    )

    assert result.outcome == "TARGET"

    assert (
        result.maximum_adverse_excursion_pct
        == pytest.approx(-5.0)
    )


def test_ambiguous_entry_bar_target_is_not_assumed():
    result = evaluate_no_stop_outcome(
        bars=[
            bar(
                45,
                open_price=10.20,
                high=10.60,
                low=9.90,
                close=10.10,
            ),
            bar(
                50,
                open_price=10.10,
                high=10.20,
                low=9.80,
                close=9.90,
            ),
        ],
        adjustment=0.0,
        entry=10.00,
        target=10.50,
    )

    assert result.filled is True
    assert result.outcome == "EOD_EXIT"


def test_open_below_entry_allows_same_bar_target():
    result = evaluate_no_stop_outcome(
        bars=[
            bar(
                45,
                open_price=9.95,
                high=10.60,
                low=9.80,
                close=10.55,
            ),
        ],
        adjustment=0.0,
        entry=10.00,
        target=10.50,
    )

    assert result.filled is True
    assert result.outcome == "TARGET"


def test_never_reaches_entry():
    result = evaluate_no_stop_outcome(
        bars=[
            bar(
                45,
                open_price=10.30,
                high=10.40,
                low=10.10,
                close=10.20,
            ),
        ],
        adjustment=0.05,
        entry=10.00,
        target=10.50,
    )

    assert result.filled is False
    assert result.outcome == "NOT_FILLED"
