from __future__ import annotations

import math

from datetime import UTC, datetime
from typing import Any, Callable

from .webull_execution import (
    WebullTradeIntent,
    generate_client_order_id,
)


QUICK_FLIP_STRATEGY_NAME = "QUICK_FLIP"


class WebullQuickFlipShadowIntentAdapterError(
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
        raise WebullQuickFlipShadowIntentAdapterError(
            reason
        ) from error

    if (
        not math.isfinite(
            result
        )
        or result <= 0
    ):
        raise WebullQuickFlipShadowIntentAdapterError(
            reason
        )

    return result


def quick_flip_preview_to_trade_intent(
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
    Convert one existing Quick Flip PREVIEW READY result into
    the normalized WebullTradeIntent used by shadow execution.

    Quick Flip remains:
    - BUY only;
    - LIMIT / DAY / CORE through WebullTradeIntent;
    - stop-loss free;
    - not submitted.

    No Webull API call or durable journal write occurs here.

    The existing Quick Flip preview payload does not expose its
    preview client_order_id, so a fresh execution-intent ID is
    generated.
    """

    if not isinstance(
        preview,
        dict,
    ):
        raise WebullQuickFlipShadowIntentAdapterError(
            "QUICK_FLIP_PREVIEW_INVALID"
        )

    if (
        preview.get("status")
        != "PREVIEW READY"
    ):
        raise WebullQuickFlipShadowIntentAdapterError(
            "QUICK_FLIP_PREVIEW_NOT_READY"
        )

    if (
        preview.get("submitted")
        is not False
    ):
        raise WebullQuickFlipShadowIntentAdapterError(
            "QUICK_FLIP_PREVIEW_SUBMISSION_STATE_INVALID"
        )

    if (
        preview.get("safetyAllowed")
        is not True
    ):
        raise WebullQuickFlipShadowIntentAdapterError(
            "QUICK_FLIP_PREVIEW_SAFETY_NOT_ALLOWED"
        )

    strategy_name = str(
        preview.get(
            "strategyName",
            "",
        )
    ).strip().upper()

    if (
        strategy_name
        != QUICK_FLIP_STRATEGY_NAME
    ):
        raise WebullQuickFlipShadowIntentAdapterError(
            "QUICK_FLIP_PREVIEW_STRATEGY_MISMATCH"
        )

    side = str(
        preview.get(
            "side",
            "",
        )
    ).strip().upper()

    if side != "BUY":
        raise WebullQuickFlipShadowIntentAdapterError(
            "QUICK_FLIP_PREVIEW_SIDE_INVALID"
        )

    if (
        preview.get(
            "automaticStopLoss"
        )
        is not False
    ):
        raise WebullQuickFlipShadowIntentAdapterError(
            "QUICK_FLIP_AUTOMATIC_STOP_STATE_INVALID"
        )

    # Quick Flip deliberately has no trading stop. Fail closed if
    # a Manipulation-style stop field crosses this boundary.
    if "tradingStopLoss" in preview:
        raise WebullQuickFlipShadowIntentAdapterError(
            "QUICK_FLIP_TRADING_STOP_FORBIDDEN"
        )

    symbol = str(
        preview.get(
            "symbol",
            "",
        )
    ).strip().upper()

    if not symbol:
        raise WebullQuickFlipShadowIntentAdapterError(
            "QUICK_FLIP_PREVIEW_SYMBOL_REQUIRED"
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
        raise WebullQuickFlipShadowIntentAdapterError(
            "QUICK_FLIP_PREVIEW_QUANTITY_INVALID"
        )

    limit_price = (
        _positive_finite_float(
            preview.get(
                "limitBuy"
            ),
            reason=(
                "QUICK_FLIP_PREVIEW_LIMIT_PRICE_INVALID"
            ),
        )
    )

    _positive_finite_float(
        preview.get(
            "takeProfit1"
        ),
        reason=(
            "QUICK_FLIP_PREVIEW_TAKE_PROFIT_1_INVALID"
        ),
    )

    _positive_finite_float(
        preview.get(
            "takeProfit2"
        ),
        reason=(
            "QUICK_FLIP_PREVIEW_TAKE_PROFIT_2_INVALID"
        ),
    )

    proposed_exposure = (
        _positive_finite_float(
            preview.get(
                "proposedExposure"
            ),
            reason=(
                "QUICK_FLIP_PREVIEW_EXPOSURE_INVALID"
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
        raise WebullQuickFlipShadowIntentAdapterError(
            "QUICK_FLIP_PREVIEW_EXPOSURE_MISMATCH"
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
        raise WebullQuickFlipShadowIntentAdapterError(
            "QUICK_FLIP_INTENT_CLOCK_INVALID"
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
        raise WebullQuickFlipShadowIntentAdapterError(
            "QUICK_FLIP_INTENT_TIMESTAMP_INVALID"
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
        raise WebullQuickFlipShadowIntentAdapterError(
            "QUICK_FLIP_CLIENT_ORDER_ID_FACTORY_INVALID"
        )

    client_order_id = str(
        selected_id_factory()
    ).strip()

    if not client_order_id:
        raise WebullQuickFlipShadowIntentAdapterError(
            "QUICK_FLIP_CLIENT_ORDER_ID_REQUIRED"
        )

    return WebullTradeIntent(
        client_order_id=(
            client_order_id
        ),
        strategy_name=(
            QUICK_FLIP_STRATEGY_NAME
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
