from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from .config import (
    WEBULL_PREVIEW_MAX_POSITION_VALUE,
    WEBULL_PREVIEW_MAX_SHARES,
)
from .quick_flip_strategy import QuickFlipSignal
from .webull_preview_client import WebullPreviewClient


@dataclass(frozen=True)
class QuickFlipWebullPreviewRequest:
    """
    Preview-only Quick Flip BUY proposal.

    Quick Flip intentionally has no automatic stop loss.
    Quantity therefore uses exposure limits rather than
    stop-based risk sizing.
    """

    symbol: str
    quantity: int
    limit_price: float
    take_profit_1: float
    take_profit_2: float
    estimated_position_value: float
    max_position_value: float
    sizing_constraint: str
    client_order_id: str


def build_quick_flip_preview_request(
    *,
    symbol: str,
    signal: QuickFlipSignal,
    max_position_value: float | None = None,
) -> QuickFlipWebullPreviewRequest:
    if signal.signal != "INVEST":
        raise ValueError(
            f"{symbol} is not a Quick Flip INVEST signal."
        )

    entry_price = float(signal.entry_price)

    if entry_price <= 0:
        raise ValueError(
            f"{symbol} has an invalid Quick Flip entry price."
        )

    effective_max_position_value = (
        WEBULL_PREVIEW_MAX_POSITION_VALUE
        if max_position_value is None
        else min(
            WEBULL_PREVIEW_MAX_POSITION_VALUE,
            float(max_position_value),
        )
    )

    if effective_max_position_value <= 0:
        raise ValueError(
            f"{symbol} has no remaining "
            "account exposure allowance."
        )

    position_value_quantity = math.floor(
        effective_max_position_value
        / entry_price
    )

    quantity_limits = {
        "MAX_SHARES": WEBULL_PREVIEW_MAX_SHARES,
        "POSITION_VALUE": position_value_quantity,
    }

    quantity = min(
        quantity_limits.values()
    )

    if quantity < 1:
        raise ValueError(
            f"{symbol} has insufficient remaining "
            "account exposure allowance for one share."
        )

    limiting_constraints = [
        name
        for name, value
        in quantity_limits.items()
        if value == quantity
    ]

    return QuickFlipWebullPreviewRequest(
        symbol=symbol,
        quantity=quantity,
        limit_price=round(
            entry_price,
            4,
        ),
        take_profit_1=round(
            float(signal.take_profit_1),
            4,
        ),
        take_profit_2=round(
            float(signal.take_profit_2),
            4,
        ),
        estimated_position_value=round(
            quantity * entry_price,
            2,
        ),
        max_position_value=round(
            effective_max_position_value,
            2,
        ),
        sizing_constraint="+".join(
            limiting_constraints
        ),
        client_order_id=(
            WebullPreviewClient
            ._client_order_id(symbol)
        ),
    )


def quick_flip_preview_payload(
    *,
    request: QuickFlipWebullPreviewRequest,
    webull_result: dict[str, Any],
) -> dict[str, Any]:
    """
    Convert Webull's preview response into the bot's
    Quick Flip preview representation.

    No stop-loss field is created.
    """
    return {
        "status": "PREVIEW READY",
        "submitted": False,
        "symbol": request.symbol,
        "strategyName": "QUICK_FLIP",
        "side": "BUY",
        "quantity": request.quantity,
        "limitBuy": request.limit_price,
        "takeProfit1": request.take_profit_1,
        "takeProfit2": request.take_profit_2,
        "automaticStopLoss": False,
        "estimatedPositionValue": (
            request.estimated_position_value
        ),
        "maxPositionValue": (
            request.max_position_value
        ),
        "sizingConstraint": (
            request.sizing_constraint
        ),
        "estimatedCost": float(
            webull_result.get(
                "estimated_cost",
                0,
            )
        ),
        "estimatedTransactionFee": float(
            webull_result.get(
                "estimated_transaction_fee",
                0,
            )
        ),
        "currency": webull_result.get(
            "currency",
            "USD",
        ),
    }


class QuickFlipWebullPreviewClient(
    WebullPreviewClient
):
    """
    Webull preview-only client for Quick Flip.

    This class calls Webull's preview_order endpoint only.
    It exposes no order submission method.
    """

    def preview(
        self,
        request: QuickFlipWebullPreviewRequest,
    ) -> dict[str, Any]:
        account_id = self._get_account_id()

        preview_orders = [
            {
                "client_order_id": (
                    request.client_order_id
                ),
                "combo_type": "NORMAL",
                "symbol": request.symbol,
                "instrument_type": "EQUITY",
                "market": "US",
                "order_type": "LIMIT",
                "limit_price": (
                    f"{request.limit_price:.4f}"
                ),
                "quantity": str(
                    request.quantity
                ),
                "side": "BUY",
                "time_in_force": "DAY",
                "support_trading_session": "CORE",
                "entrust_type": "QTY",
            }
        ]

        response = (
            self._trade_client.order_v2
            .preview_order(
                account_id,
                preview_orders,
            )
        )

        if response.status_code != 200:
            raise RuntimeError(
                "Webull Quick Flip preview failed "
                f"with HTTP {response.status_code}: "
                f"{response.text}"
            )

        result = response.json()

        if not isinstance(result, dict):
            raise RuntimeError(
                "Webull Quick Flip preview returned "
                "invalid data."
            )

        return quick_flip_preview_payload(
            request=request,
            webull_result=result,
        )
