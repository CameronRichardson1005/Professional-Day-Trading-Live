from copy import deepcopy
from datetime import UTC, datetime

import pytest

from trading_bot.config import (
    MANIPULATION_STRATEGY_NAME,
)
from trading_bot.webull_shadow_intent_adapter import (
    WebullShadowIntentAdapterError,
    manipulation_preview_to_trade_intent,
)


NOW = datetime(
    2026,
    8,
    18,
    18,
    30,
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
        "symbol": "OPEN",
        "strategyName": (
            MANIPULATION_STRATEGY_NAME
        ),
        "quantity": 10,
        "limitBuy": 10.0,
        "target": 10.5,
        "tradingStopLoss": 9.5,
        "proposedExposure": 100.0,
    }


def build(
    preview=None,
    *,
    clock=lambda: NOW,
    id_factory=lambda: (
        "manipulation-shadow-1"
    ),
):
    return (
        manipulation_preview_to_trade_intent(
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


def test_ready_manipulation_preview_builds_intent():
    intent = build()

    assert (
        intent.client_order_id
        == "manipulation-shadow-1"
    )

    assert (
        intent.strategy_name
        == MANIPULATION_STRATEGY_NAME
    )

    assert intent.symbol == "OPEN"
    assert intent.side == "BUY"
    assert intent.quantity == 10
    assert intent.limit_price == 10.0
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


def test_missing_strategy_name_uses_manipulation_identity():
    preview = ready_preview()

    preview[
        "strategyName"
    ] = None

    intent = build(
        preview
    )

    assert (
        intent.strategy_name
        == MANIPULATION_STRATEGY_NAME
    )


def test_different_strategy_is_rejected():
    preview = ready_preview()

    preview[
        "strategyName"
    ] = "QUICK_FLIP"

    with pytest.raises(
        WebullShadowIntentAdapterError,
        match=(
            "^MANIPULATION_PREVIEW_"
            "STRATEGY_MISMATCH$"
        ),
    ):
        build(
            preview
        )


def test_non_ready_preview_is_rejected():
    preview = ready_preview()

    preview["status"] = (
        "PREVIEW FAILED"
    )

    with pytest.raises(
        WebullShadowIntentAdapterError,
        match=(
            "^MANIPULATION_PREVIEW_"
            "NOT_READY$"
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
        WebullShadowIntentAdapterError,
        match=(
            "^MANIPULATION_PREVIEW_"
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
        WebullShadowIntentAdapterError,
        match=(
            "^MANIPULATION_PREVIEW_"
            "SAFETY_NOT_ALLOWED$"
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
        WebullShadowIntentAdapterError,
        match=(
            "^MANIPULATION_PREVIEW_"
            "QUANTITY_INVALID$"
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
        WebullShadowIntentAdapterError,
        match=(
            "^MANIPULATION_PREVIEW_"
            "LIMIT_PRICE_INVALID$"
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
        WebullShadowIntentAdapterError,
        match=(
            "^MANIPULATION_PREVIEW_"
            "EXPOSURE_MISMATCH$"
        ),
    ):
        build(
            preview
        )


def test_manipulation_target_is_required():
    preview = ready_preview()

    preview["target"] = None

    with pytest.raises(
        WebullShadowIntentAdapterError,
        match=(
            "^MANIPULATION_PREVIEW_"
            "TARGET_INVALID$"
        ),
    ):
        build(
            preview
        )


def test_manipulation_trading_stop_is_required():
    preview = ready_preview()

    preview[
        "tradingStopLoss"
    ] = None

    with pytest.raises(
        WebullShadowIntentAdapterError,
        match=(
            "^MANIPULATION_PREVIEW_"
            "TRADING_STOP_INVALID$"
        ),
    ):
        build(
            preview
        )


def test_naive_intent_timestamp_is_rejected():
    with pytest.raises(
        WebullShadowIntentAdapterError,
        match=(
            "^MANIPULATION_INTENT_"
            "TIMESTAMP_INVALID$"
        ),
    ):
        build(
            clock=lambda: datetime(
                2026,
                8,
                18,
                14,
                30,
            )
        )


def test_empty_generated_client_order_id_is_rejected():
    with pytest.raises(
        WebullShadowIntentAdapterError,
        match=(
            "^MANIPULATION_CLIENT_"
            "ORDER_ID_REQUIRED$"
        ),
    ):
        build(
            id_factory=lambda: " "
        )
