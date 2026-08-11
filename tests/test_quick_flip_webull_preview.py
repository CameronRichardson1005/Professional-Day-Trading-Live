from unittest.mock import patch

import pytest

from trading_bot.quick_flip_strategy import (
    QuickFlipSignal,
)
from trading_bot.quick_flip_webull_preview import (
    build_quick_flip_preview_request,
)


def invest_signal(
    *,
    entry=10.0,
    tp1=10.50,
    tp2=11.0,
):
    return QuickFlipSignal(
        symbol="TEST",
        signal="INVEST",
        pattern="HAMMER",
        status="CONFIRMED",
        detail="test",
        entry_price=entry,
        take_profit_1=tp1,
        take_profit_2=tp2,
        opening_range_high=tp2,
        opening_range_low=tp1,
        opening_range_size=(
            tp2 - tp1
        ),
        atr_14=1.0,
        liquidity_threshold=1.25,
        reversal_time=None,
        confirmation_time=None,
    )


def test_quick_flip_preview_has_no_stop_loss():
    request = build_quick_flip_preview_request(
        symbol="OPEN",
        signal=invest_signal(),
    )

    assert not hasattr(
        request,
        "trading_stop_loss",
    )

    assert not hasattr(
        request,
        "risk_per_share",
    )


def test_position_value_caps_quantity():
    with (
        patch(
            "trading_bot.quick_flip_webull_preview."
            "WEBULL_PREVIEW_MAX_POSITION_VALUE",
            500.0,
        ),
        patch(
            "trading_bot.quick_flip_webull_preview."
            "WEBULL_PREVIEW_MAX_SHARES",
            1000,
        ),
    ):
        request = (
            build_quick_flip_preview_request(
                symbol="OPEN",
                signal=invest_signal(
                    entry=10.0,
                ),
            )
        )

    assert request.quantity == 50
    assert (
        request.estimated_position_value
        == 500.0
    )

    assert (
        request.sizing_constraint
        == "POSITION_VALUE"
    )


def test_max_shares_caps_quantity():
    with (
        patch(
            "trading_bot.quick_flip_webull_preview."
            "WEBULL_PREVIEW_MAX_POSITION_VALUE",
            5000.0,
        ),
        patch(
            "trading_bot.quick_flip_webull_preview."
            "WEBULL_PREVIEW_MAX_SHARES",
            25,
        ),
    ):
        request = (
            build_quick_flip_preview_request(
                symbol="BBAI",
                signal=invest_signal(
                    entry=5.0,
                ),
            )
        )

    assert request.quantity == 25
    assert (
        request.sizing_constraint
        == "MAX_SHARES"
    )


def test_remaining_account_allowance_is_respected():
    request = build_quick_flip_preview_request(
        symbol="SOUN",
        signal=invest_signal(
            entry=10.0,
        ),
        max_position_value=25.0,
    )

    assert request.quantity == 2
    assert (
        request.estimated_position_value
        == 20.0
    )


def test_non_invest_signal_is_rejected():
    signal = invest_signal()

    non_invest = QuickFlipSignal(
        symbol=signal.symbol,
        signal="NO INVEST",
        pattern=signal.pattern,
        status=signal.status,
        detail=signal.detail,
        entry_price=signal.entry_price,
        take_profit_1=signal.take_profit_1,
        take_profit_2=signal.take_profit_2,
        opening_range_high=(
            signal.opening_range_high
        ),
        opening_range_low=(
            signal.opening_range_low
        ),
        opening_range_size=(
            signal.opening_range_size
        ),
        atr_14=signal.atr_14,
        liquidity_threshold=(
            signal.liquidity_threshold
        ),
        reversal_time=None,
        confirmation_time=None,
    )

    with pytest.raises(
        ValueError,
        match="not a Quick Flip INVEST",
    ):
        build_quick_flip_preview_request(
            symbol="OPEN",
            signal=non_invest,
        )


def test_price_above_allowance_is_rejected():
    with pytest.raises(
        ValueError,
        match="insufficient remaining",
    ):
        build_quick_flip_preview_request(
            symbol="OPEN",
            signal=invest_signal(
                entry=50.0,
            ),
            max_position_value=25.0,
        )
