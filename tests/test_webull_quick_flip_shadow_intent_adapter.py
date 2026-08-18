from copy import deepcopy
from datetime import UTC, datetime

import pytest

from trading_bot.webull_quick_flip_shadow_intent_adapter import (
    QUICK_FLIP_STRATEGY_NAME,
    WebullQuickFlipShadowIntentAdapterError,
    quick_flip_preview_to_trade_intent,
)


NOW = datetime(
    2026,
    8,
    18,
    18,
    35,
    tzinfo=UTC,
)


def ready_preview():
    return {
        "status": "PREVIEW READY",
        "submitted": False,
        "safetyAllowed": True,
        "safetyReason": (
            "PREVIEW_ELIGIBLE"
        ),
        "symbol": "SOUN",
        "strategyName": (
            "QUICK_FLIP"
        ),
        "side": "BUY",
        "quantity": 20,
        "limitBuy": 5.0,
        "takeProfit1": 5.25,
        "takeProfit2": 5.50,
        "automaticStopLoss": False,
        "proposedExposure": 100.0,
    }


def build(
    preview=None,
    *,
    clock=lambda: NOW,
    id_factory=lambda: (
        "quick-flip-shadow-1"
    ),
):
    return (
        quick_flip_preview_to_trade_intent(
            (
                ready_preview()
                if preview is None
                else preview
            ),
            clock=clock,
            client_order_id_factory=(
                id_factory
            ),
        )
    )


def test_ready_quick_flip_preview_builds_intent():
    intent = build()

    assert (
        intent.client_order_id
        == "quick-flip-shadow-1"
    )

    assert (
        intent.strategy_name
        == QUICK_FLIP_STRATEGY_NAME
    )

    assert intent.symbol == "SOUN"
    assert intent.side == "BUY"
    assert intent.quantity == 20
    assert intent.limit_price == 5.0
    assert intent.created_at == NOW

    assert intent.order_type == "LIMIT"
    assert intent.time_in_force == "DAY"

    assert (
        intent.support_trading_session
        == "CORE"
    )

    assert (
        intent.proposed_exposure
        == 100.0
    )


def test_adapter_does_not_mutate_preview():
    preview = ready_preview()

    before = deepcopy(
        preview
    )

    build(
        preview
    )

    assert preview == before


def test_different_strategy_is_rejected():
    preview = ready_preview()

    preview[
        "strategyName"
    ] = "MANIPULATION"

    with pytest.raises(
        WebullQuickFlipShadowIntentAdapterError,
        match=(
            "^QUICK_FLIP_PREVIEW_"
            "STRATEGY_MISMATCH$"
        ),
    ):
        build(
            preview
        )


def test_non_ready_preview_is_rejected():
    preview = ready_preview()

    preview[
        "status"
    ] = "PREVIEW FAILED"

    with pytest.raises(
        WebullQuickFlipShadowIntentAdapterError,
        match=(
            "^QUICK_FLIP_PREVIEW_NOT_READY$"
        ),
    ):
        build(
            preview
        )


def test_submitted_preview_is_rejected():
    preview = ready_preview()

    preview[
        "submitted"
    ] = True

    with pytest.raises(
        WebullQuickFlipShadowIntentAdapterError,
        match=(
            "^QUICK_FLIP_PREVIEW_"
            "SUBMISSION_STATE_INVALID$"
        ),
    ):
        build(
            preview
        )


def test_preview_must_be_safety_allowed():
    preview = ready_preview()

    preview[
        "safetyAllowed"
    ] = False

    with pytest.raises(
        WebullQuickFlipShadowIntentAdapterError,
        match=(
            "^QUICK_FLIP_PREVIEW_"
            "SAFETY_NOT_ALLOWED$"
        ),
    ):
        build(
            preview
        )


def test_quick_flip_must_remain_buy_only():
    preview = ready_preview()

    preview[
        "side"
    ] = "SELL"

    with pytest.raises(
        WebullQuickFlipShadowIntentAdapterError,
        match=(
            "^QUICK_FLIP_PREVIEW_SIDE_INVALID$"
        ),
    ):
        build(
            preview
        )


def test_automatic_stop_must_remain_disabled():
    preview = ready_preview()

    preview[
        "automaticStopLoss"
    ] = True

    with pytest.raises(
        WebullQuickFlipShadowIntentAdapterError,
        match=(
            "^QUICK_FLIP_AUTOMATIC_"
            "STOP_STATE_INVALID$"
        ),
    ):
        build(
            preview
        )


def test_trading_stop_field_is_forbidden():
    preview = ready_preview()

    preview[
        "tradingStopLoss"
    ] = 4.50

    with pytest.raises(
        WebullQuickFlipShadowIntentAdapterError,
        match=(
            "^QUICK_FLIP_TRADING_STOP_FORBIDDEN$"
        ),
    ):
        build(
            preview
        )


def test_invalid_quantity_is_rejected():
    preview = ready_preview()

    preview[
        "quantity"
    ] = 0

    with pytest.raises(
        WebullQuickFlipShadowIntentAdapterError,
        match=(
            "^QUICK_FLIP_PREVIEW_QUANTITY_INVALID$"
        ),
    ):
        build(
            preview
        )


def test_invalid_limit_price_is_rejected():
    preview = ready_preview()

    preview[
        "limitBuy"
    ] = float("nan")

    with pytest.raises(
        WebullQuickFlipShadowIntentAdapterError,
        match=(
            "^QUICK_FLIP_PREVIEW_"
            "LIMIT_PRICE_INVALID$"
        ),
    ):
        build(
            preview
        )


def test_take_profit_1_is_required():
    preview = ready_preview()

    preview[
        "takeProfit1"
    ] = None

    with pytest.raises(
        WebullQuickFlipShadowIntentAdapterError,
        match=(
            "^QUICK_FLIP_PREVIEW_"
            "TAKE_PROFIT_1_INVALID$"
        ),
    ):
        build(
            preview
        )


def test_take_profit_2_is_required():
    preview = ready_preview()

    preview[
        "takeProfit2"
    ] = None

    with pytest.raises(
        WebullQuickFlipShadowIntentAdapterError,
        match=(
            "^QUICK_FLIP_PREVIEW_"
            "TAKE_PROFIT_2_INVALID$"
        ),
    ):
        build(
            preview
        )


def test_exposure_mismatch_is_rejected():
    preview = ready_preview()

    preview[
        "proposedExposure"
    ] = 99.0

    with pytest.raises(
        WebullQuickFlipShadowIntentAdapterError,
        match=(
            "^QUICK_FLIP_PREVIEW_"
            "EXPOSURE_MISMATCH$"
        ),
    ):
        build(
            preview
        )


def test_naive_intent_timestamp_is_rejected():
    with pytest.raises(
        WebullQuickFlipShadowIntentAdapterError,
        match=(
            "^QUICK_FLIP_INTENT_"
            "TIMESTAMP_INVALID$"
        ),
    ):
        build(
            clock=lambda: datetime(
                2026,
                8,
                18,
                14,
                35,
            )
        )


def test_empty_generated_client_order_id_is_rejected():
    with pytest.raises(
        WebullQuickFlipShadowIntentAdapterError,
        match=(
            "^QUICK_FLIP_CLIENT_"
            "ORDER_ID_REQUIRED$"
        ),
    ):
        build(
            id_factory=lambda: " "
        )
