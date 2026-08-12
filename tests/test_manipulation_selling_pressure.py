import pytest

from trading_bot.manipulation_selling_pressure import (
    calculate_adjusted_entries,
    calculate_close_location,
    calculate_relative_volume,
    evaluate_selling_pressure,
    has_strong_selling_pressure,
)


def test_close_at_low_is_zero():
    assert calculate_close_location(
        high=10.0,
        low=9.0,
        close=9.0,
    ) == 0.0


def test_close_at_high_is_one():
    assert calculate_close_location(
        high=10.0,
        low=9.0,
        close=10.0,
    ) == 1.0


def test_close_location_inside_range():
    assert calculate_close_location(
        high=10.0,
        low=9.0,
        close=9.2,
    ) == pytest.approx(0.2)


def test_flat_candle_returns_neutral_location():
    assert calculate_close_location(
        high=10.0,
        low=10.0,
        close=10.0,
    ) == 0.5


def test_relative_volume():
    assert calculate_relative_volume(
        current_volume=150_000,
        average_opening_volume=100_000,
    ) == pytest.approx(1.5)


def test_missing_average_volume_returns_none():
    assert calculate_relative_volume(
        current_volume=150_000,
        average_opening_volume=None,
    ) is None


def test_strong_selling_requires_low_close_and_high_volume():
    assert has_strong_selling_pressure(
        close_location=0.15,
        relative_volume=1.75,
    ) is True


def test_high_volume_without_low_close_is_not_strong_selling():
    assert has_strong_selling_pressure(
        close_location=0.50,
        relative_volume=2.0,
    ) is False


def test_low_close_without_high_volume_is_not_strong_selling():
    assert has_strong_selling_pressure(
        close_location=0.10,
        relative_volume=1.20,
    ) is False


def test_adjusted_entries_are_below_opening_low():
    levels = calculate_adjusted_entries(
        high=10.0,
        low=9.5,
    )

    assert levels[0.00] == 9.5
    assert levels[0.05] == 9.475
    assert levels[0.10] == 9.45
    assert levels[0.15] == 9.425
    assert levels[0.20] == 9.4
    assert levels[0.25] == 9.375


def test_evaluate_selling_pressure():
    result = evaluate_selling_pressure(
        opening_bar={
            "o": 10.0,
            "h": 10.0,
            "l": 9.5,
            "c": 9.55,
            "v": 180_000,
        },
        average_opening_volume=100_000,
    )

    assert result.close_location == pytest.approx(
        0.10
    )
    assert result.relative_volume == pytest.approx(
        1.80
    )
    assert result.strong_selling_pressure is True

    assert result.entry_levels[0.00] == 9.5
    assert result.entry_levels[0.15] == 9.425


def test_average_opening_volume():
    from trading_bot.manipulation_selling_pressure import (
        calculate_average_opening_volume,
    )

    bars = [
        {"v": 100_000},
        {"v": 120_000},
        {"v": 140_000},
        {"v": 160_000},
        {"v": 180_000},
    ]

    assert calculate_average_opening_volume(
        bars
    ) == pytest.approx(140_000)


def test_average_opening_volume_ignores_invalid_volume():
    from trading_bot.manipulation_selling_pressure import (
        calculate_average_opening_volume,
    )

    bars = [
        {"v": 100_000},
        {"v": 120_000},
        {"v": 0},
        {"v": None},
        {"v": 140_000},
        {"v": 160_000},
        {"v": 180_000},
    ]

    assert calculate_average_opening_volume(
        bars
    ) == pytest.approx(140_000)


def test_average_opening_volume_requires_history():
    from trading_bot.manipulation_selling_pressure import (
        calculate_average_opening_volume,
    )

    bars = [
        {"v": 100_000},
        {"v": 120_000},
        {"v": 140_000},
    ]

    assert (
        calculate_average_opening_volume(
            bars
        )
        is None
    )
