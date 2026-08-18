from __future__ import annotations

import math

from datetime import UTC, datetime
from typing import Any, Callable

from .config import (
    MANIPULATION_STRATEGY_NAME,
)
from .webull_execution import (
    WebullTradeIntent,
    generate_client_order_id,
)


class WebullShadowIntentAdapterError(
    RuntimeError
):
    pass


def _positive_finite_float(
    value: Any,
    *,
    reason: str,
) -> float:
    try:
        result = float(
            value
        )
    except (
        TypeError,
        ValueError,
    ) as error:
        raise WebullShadowIntentAdapterError(
            reason
        ) from error

    if (
        not math.isfinite(
            result
        )
        or result <= 0
    ):
        raise WebullShadowIntentAdapterError(
            reason
        )

    return result


def manipulation_preview_to_trade_intent(
    preview: dict[str, Any],
    *,
    clock: (
        Callable[
            [],
            datetime,
        ]
        | None
    ) = None,
    client_order_id_factory: (
        Callable[
            [],
            str,
        ]
        | None
    ) = None,
) -> WebullTradeIntent:
    """
    Convert one existing Manipulation PREVIEW READY result into
    the normalized WebullTradeIntent used by the shadow execution
    boundary.

    This function:
    - performs no Webull call;
    - performs no broker mutation;
    - does not write either execution journal;
    - does not reuse or infer a preview request ID;
    - accepts only a safety-approved, non-submitted preview.

    The existing preview payload does not expose its internal
    preview client_order_id, so a fresh globally unique intent ID
    is generated here.
    """

    if not isinstance(
        preview,
        dict,
    ):
        raise WebullShadowIntentAdapterError(
            "MANIPULATION_PREVIEW_INVALID"
        )

    if (
        preview.get("status")
        != "PREVIEW READY"
    ):
        raise WebullShadowIntentAdapterError(
            "MANIPULATION_PREVIEW_NOT_READY"
        )

    if (
        preview.get("submitted")
        is not False
    ):
        raise WebullShadowIntentAdapterError(
            "MANIPULATION_PREVIEW_SUBMISSION_STATE_INVALID"
        )

    if (
        preview.get("safetyAllowed")
        is not True
    ):
        raise WebullShadowIntentAdapterError(
            "MANIPULATION_PREVIEW_SAFETY_NOT_ALLOWED"
        )

    expected_strategy = str(
        MANIPULATION_STRATEGY_NAME
    ).strip()

    if not expected_strategy:
        raise WebullShadowIntentAdapterError(
            "MANIPULATION_STRATEGY_NAME_INVALID"
        )

    supplied_strategy = (
        preview.get(
            "strategyName"
        )
    )

    if supplied_strategy not in {
        None,
        "",
    }:
        normalized_strategy = str(
            supplied_strategy
        ).strip()

        if (
            normalized_strategy.upper()
            != expected_strategy.upper()
        ):
            raise WebullShadowIntentAdapterError(
                "MANIPULATION_PREVIEW_STRATEGY_MISMATCH"
            )

    symbol = str(
        preview.get(
            "symbol",
            "",
        )
    ).strip().upper()

    if not symbol:
        raise WebullShadowIntentAdapterError(
            "MANIPULATION_PREVIEW_SYMBOL_REQUIRED"
        )

    quantity = preview.get(
        "quantity"
    )

    if (
        isinstance(
            quantity,
            bool,
        )
        or not isinstance(
            quantity,
            int,
        )
        or quantity <= 0
    ):
        raise WebullShadowIntentAdapterError(
            "MANIPULATION_PREVIEW_QUANTITY_INVALID"
        )

    limit_price = (
        _positive_finite_float(
            preview.get(
                "limitBuy"
            ),
            reason=(
                "MANIPULATION_PREVIEW_LIMIT_PRICE_INVALID"
            ),
        )
    )

    # These fields are not part of WebullTradeIntent itself, but
    # requiring them prevents a different strategy's PREVIEW READY
    # payload from silently crossing the Manipulation adapter.
    _positive_finite_float(
        preview.get(
            "target"
        ),
        reason=(
            "MANIPULATION_PREVIEW_TARGET_INVALID"
        ),
    )

    _positive_finite_float(
        preview.get(
            "tradingStopLoss"
        ),
        reason=(
            "MANIPULATION_PREVIEW_TRADING_STOP_INVALID"
        ),
    )

    proposed_exposure = (
        _positive_finite_float(
            preview.get(
                "proposedExposure"
            ),
            reason=(
                "MANIPULATION_PREVIEW_EXPOSURE_INVALID"
            ),
        )
    )

    calculated_exposure = round(
        quantity
        * limit_price,
        2,
    )

    if (
        abs(
            round(
                proposed_exposure,
                2,
            )
            - calculated_exposure
        )
        > 0.01
    ):
        raise WebullShadowIntentAdapterError(
            "MANIPULATION_PREVIEW_EXPOSURE_MISMATCH"
        )

    selected_clock = (
        clock
        if clock is not None
        else lambda: datetime.now(
            UTC
        )
    )

    if not callable(
        selected_clock
    ):
        raise WebullShadowIntentAdapterError(
            "MANIPULATION_INTENT_CLOCK_INVALID"
        )

    created_at = (
        selected_clock()
    )

    if (
        not isinstance(
            created_at,
            datetime,
        )
        or created_at.tzinfo
        is None
    ):
        raise WebullShadowIntentAdapterError(
            "MANIPULATION_INTENT_TIMESTAMP_INVALID"
        )

    selected_id_factory = (
        client_order_id_factory
        if client_order_id_factory
        is not None
        else generate_client_order_id
    )

    if not callable(
        selected_id_factory
    ):
        raise WebullShadowIntentAdapterError(
            "MANIPULATION_CLIENT_ORDER_ID_FACTORY_INVALID"
        )

    client_order_id = str(
        selected_id_factory()
    ).strip()

    if not client_order_id:
        raise WebullShadowIntentAdapterError(
            "MANIPULATION_CLIENT_ORDER_ID_REQUIRED"
        )

    return WebullTradeIntent(
        client_order_id=(
            client_order_id
        ),
        strategy_name=(
            expected_strategy
        ),
        symbol=symbol,
        side="BUY",
        quantity=quantity,
        limit_price=(
            limit_price
        ),
        created_at=(
            created_at
        ),
    )
