import pytest

from trading_bot.models import Stock
from trading_bot.manipulation_selling_pressure_shadow import (
    build_selling_pressure_shadow,
)


def make_stock(
    *,
    close=10.02,
    volume=3000,
):
    stock = Stock(symbol="TEST")

    stock.signal = "INVEST"

    stock.opening_bar = {
        "o": 10.50,
        "h": 10.50,
        "l": 10.00,
        "c": close,
        "v": volume,
    }

    stock.limit_buy = 10.00
    stock.limit_sell = 10.191

    stock.stop_loss = 9.85
    stock.trading_stop_loss = 9.80

    return stock


def test_trigger_builds_two_shadow_variants():
    stock = make_stock()

    result = build_selling_pressure_shadow(
        stock=stock,
        average_opening_volume=1000,
    )

    assert result is not None

    assert result.symbol == "TEST"

    assert result.close_location == pytest.approx(
        0.04
    )

    assert result.relative_volume == pytest.approx(
        3.0
    )

    assert result.normal_entry == pytest.approx(
        10.00
    )

    # 5% of a $0.50 opening range = $0.025 lower.
    assert result.adaptive_entry == pytest.approx(
        9.975
    )

    assert (
        result.variant_b_stop
        < result.variant_a_stop
        < result.adaptive_entry
    )

    assert result.target == pytest.approx(
        10.191
    )

    assert result.variant_a_outcome == "PENDING"
    assert result.variant_b_outcome == "PENDING"


def test_shadow_does_not_change_live_stock_values():
    stock = make_stock()

    original = (
        stock.limit_buy,
        stock.limit_sell,
        stock.stop_loss,
        stock.trading_stop_loss,
        stock.signal,
    )

    build_selling_pressure_shadow(
        stock=stock,
        average_opening_volume=1000,
    )

    assert (
        stock.limit_buy,
        stock.limit_sell,
        stock.stop_loss,
        stock.trading_stop_loss,
        stock.signal,
    ) == original


def test_non_trigger_returns_none_when_relative_volume_is_low():
    stock = make_stock(
        volume=1500,
    )

    result = build_selling_pressure_shadow(
        stock=stock,
        average_opening_volume=1000,
    )

    assert result is None


def test_non_trigger_returns_none_when_close_location_is_too_high():
    stock = make_stock(
        close=10.25,
    )

    result = build_selling_pressure_shadow(
        stock=stock,
        average_opening_volume=1000,
    )

    assert result is None


def test_no_invest_signal_is_never_shadow_tracked():
    stock = make_stock()
    stock.signal = "NO INVEST"

    result = build_selling_pressure_shadow(
        stock=stock,
        average_opening_volume=1000,
    )

    assert result is None
