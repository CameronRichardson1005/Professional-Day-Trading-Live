import pytest

from trading_bot.manipulation_selling_pressure_backtest import (
    EntryOutcome,
)
from trading_bot.manipulation_selling_pressure_validation import (
    summarize_paired,
    summarize_side,
)


def outcome(
    *,
    filled,
    status,
    return_pct=None,
):
    return EntryOutcome(
        adjustment=0.0,
        entry=10.0,
        target=10.5,
        trading_stop=9.8,
        filled=filled,
        outcome=status,
        exit_price=(
            None
            if return_pct is None
            else 10.5
        ),
        return_pct=return_pct,
    )


def test_summary_counts_outcomes():
    result = summarize_side(
        [
            outcome(
                filled=True,
                status="TARGET",
                return_pct=2.0,
            ),
            outcome(
                filled=True,
                status="STOP",
                return_pct=-1.0,
            ),
            outcome(
                filled=False,
                status="NOT_FILLED",
            ),
            outcome(
                filled=True,
                status="OPEN",
            ),
        ]
    )

    assert result["signals"] == 4
    assert result["filled"] == 3
    assert result["targets"] == 1
    assert result["stops"] == 1
    assert result["not_filled"] == 1
    assert result["unresolved"] == 1

    assert (
        result["realized_return_sum"]
        == pytest.approx(1.0)
    )

    assert (
        result["realized_return_per_signal"]
        == pytest.approx(0.25)
    )


def test_average_closed_return_excludes_open_and_unfilled():
    result = summarize_side(
        [
            outcome(
                filled=True,
                status="TARGET",
                return_pct=3.0,
            ),
            outcome(
                filled=True,
                status="STOP",
                return_pct=-1.0,
            ),
            outcome(
                filled=False,
                status="NOT_FILLED",
            ),
        ]
    )

    assert (
        result["average_closed_return"]
        == pytest.approx(1.0)
    )
