import pytest

from trading_bot.manipulation_selling_pressure_runner import (
    prior_opening_average,
    qualifies_manipulation,
)


def opening_bar(
    date,
    *,
    volume,
    open_price=10.0,
    high=10.5,
    low=9.5,
    close=9.6,
):
    return {
        "t": (
            f"{date}T13:30:00Z"
        ),
        "o": open_price,
        "h": high,
        "l": low,
        "c": close,
        "v": volume,
    }


def test_prior_opening_average_excludes_current_and_future():
    bars = [
        opening_bar(
            "2026-08-03",
            volume=100,
        ),
        opening_bar(
            "2026-08-04",
            volume=200,
        ),
        opening_bar(
            "2026-08-05",
            volume=300,
        ),
        opening_bar(
            "2026-08-06",
            volume=400,
        ),
        opening_bar(
            "2026-08-07",
            volume=500,
        ),
        opening_bar(
            "2026-08-10",
            volume=10_000,
        ),
        opening_bar(
            "2026-08-11",
            volume=20_000,
        ),
    ]

    average = prior_opening_average(
        opening_bars=bars,
        current_date="2026-08-10",
        lookback_sessions=20,
        minimum_sessions=5,
    )

    assert average == pytest.approx(
        300.0
    )


def test_manipulation_requires_red_candle():
    bar = opening_bar(
        "2026-08-10",
        volume=1000,
        open_price=10.0,
        high=10.5,
        low=9.5,
        close=10.2,
    )

    assert qualifies_manipulation(
        opening_bar=bar,
        atr=1.0,
        atr_multiplier=0.25,
    ) is False


def test_large_red_candle_qualifies():
    bar = opening_bar(
        "2026-08-10",
        volume=1000,
        open_price=10.4,
        high=10.5,
        low=9.5,
        close=9.6,
    )

    assert qualifies_manipulation(
        opening_bar=bar,
        atr=1.0,
        atr_multiplier=0.25,
    ) is True
