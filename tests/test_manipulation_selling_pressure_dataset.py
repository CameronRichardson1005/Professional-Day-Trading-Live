import pytest

from trading_bot.manipulation_selling_pressure_dataset import (
    build_atr_by_date,
)


def daily_bar(
    date,
    *,
    high,
    low,
    close,
):
    return {
        "t": f"{date}T20:00:00Z",
        "o": close,
        "h": high,
        "l": low,
        "c": close,
        "v": 1000,
    }


def test_atr_uses_only_prior_daily_bars():
    bars = []

    for day in range(1, 20):
        date = (
            f"2026-07-{day:02d}"
        )

        bars.append(
            daily_bar(
                date,
                high=10.0 + day,
                low=9.0 + day,
                close=9.5 + day,
            )
        )

    # Extreme future bar that must not affect the test date.
    bars.append(
        daily_bar(
            "2026-07-25",
            high=1000.0,
            low=1.0,
            close=500.0,
        )
    )

    results = build_atr_by_date(
        daily_bars=bars,
        test_dates=[
            "2026-07-20",
        ],
        period=14,
    )

    assert "2026-07-20" in results
    assert results[
        "2026-07-20"
    ] < 100.0


def test_atr_requires_enough_prior_history():
    bars = [
        daily_bar(
            f"2026-07-{day:02d}",
            high=10.0,
            low=9.0,
            close=9.5,
        )
        for day in range(
            1,
            10,
        )
    ]

    results = build_atr_by_date(
        daily_bars=bars,
        test_dates=[
            "2026-07-10",
        ],
        period=14,
    )

    assert results == {}
