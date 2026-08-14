from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from typing import Any

from webull.core.client import ApiClient
from webull.trade.trade_client import TradeClient

from .config import (
    WEBULL_APP_KEY,
    WEBULL_APP_SECRET,
    WEBULL_PREVIEW_MAX_POSITION_VALUE,
    WEBULL_PREVIEW_MAX_SHARES,
    WEBULL_PREVIEW_RISK_DOLLARS,
)
from .models import Stock


@dataclass(frozen=True)
class WebullPreviewRequest:
    symbol: str
    quantity: int
    limit_price: float
    target_price: float
    trading_stop_loss: float
    risk_per_share: float
    planned_risk: float
    estimated_position_value: float
    max_position_value: float
    sizing_constraint: str
    client_order_id: str


class WebullPreviewClient:
    """
    Preview-only Webull adapter.

    This class intentionally exposes no place, replace, or
    cancel-order functions.
    """

    def __init__(self) -> None:
        if not WEBULL_APP_KEY:
            raise RuntimeError(
                "WEBULL_APP_KEY is not configured."
            )

        if not WEBULL_APP_SECRET:
            raise RuntimeError(
                "WEBULL_APP_SECRET is not configured."
            )

        api_client = ApiClient(
            WEBULL_APP_KEY,
            WEBULL_APP_SECRET,
            "us",
        )

        api_client.add_endpoint(
            "us",
            "api.webull.com",
        )

        self._trade_client = TradeClient(api_client)
        self._account_id: str | None = None

    def _get_account_id(self) -> str:
        if self._account_id:
            return self._account_id

        response = (
            self._trade_client.account_v2
            .get_account_list()
        )

        if response.status_code != 200:
            raise RuntimeError(
                "Webull account lookup failed with "
                f"HTTP {response.status_code}."
            )

        accounts = response.json()

        if not isinstance(accounts, list) or not accounts:
            raise RuntimeError(
                "Webull returned no trading accounts."
            )

        account_id = accounts[0].get("account_id")

        if not account_id:
            raise RuntimeError(
                "Webull account response did not contain "
                "an account ID."
            )

        self._account_id = str(account_id)
        return self._account_id

    @staticmethod
    def _client_order_id(
            symbol: str,
    ) -> str:
        compact_symbol = (
            symbol.strip().upper()[:6]
        )

        # 3 + 6 + 16 = at most 25 characters.
        return (
            f"ctd{compact_symbol}"
            f"{uuid.uuid4().hex[:16]}"
        )

    @staticmethod
    def build_request(
            stock: Stock,
            *,
            max_position_value: float | None = None,
    ) -> WebullPreviewRequest:
        if stock.signal != "INVEST":
            raise ValueError(
                f"{stock.symbol} is not an INVEST signal."
            )

        if stock.limit_buy is None:
            raise ValueError(
                f"{stock.symbol} has no limit-buy price."
            )

        if stock.limit_sell is None:
            raise ValueError(
                f"{stock.symbol} has no target price."
            )

        if stock.trading_stop_loss is None:
            raise ValueError(
                f"{stock.symbol} has no trading stop loss."
            )

        limit_price = float(stock.limit_buy)
        target_price = float(stock.limit_sell)
        trading_stop = float(
            stock.trading_stop_loss
        )

        risk_per_share = (
            limit_price - trading_stop
        )

        if risk_per_share <= 0:
            raise ValueError(
                f"{stock.symbol} has invalid risk per share."
            )

        # $500 is only the fallback when no account-aware
        # allocation has been supplied.
        effective_max_position_value = (
            WEBULL_PREVIEW_MAX_POSITION_VALUE
            if max_position_value is None
            else float(max_position_value)
        )

        if effective_max_position_value <= 0:
            raise ValueError(
                f"{stock.symbol} has no remaining "
                "account exposure allowance."
            )

        risk_based_quantity = math.floor(
            WEBULL_PREVIEW_RISK_DOLLARS
            / risk_per_share
        )

        position_value_quantity = math.floor(
            effective_max_position_value
            / limit_price
        )

        quantity_limits = {
            "RISK_BUDGET": risk_based_quantity,
            "MAX_SHARES": WEBULL_PREVIEW_MAX_SHARES,
            "POSITION_VALUE": position_value_quantity,
        }

        quantity = min(quantity_limits.values())

        limiting_constraints = [
            name
            for name, value in quantity_limits.items()
            if value == quantity
        ]

        sizing_constraint = "+".join(
            limiting_constraints
        )

        if quantity < 1:
            if position_value_quantity < 1:
                if (
                    max_position_value is not None
                    and effective_max_position_value
                    < WEBULL_PREVIEW_MAX_POSITION_VALUE
                ):
                    raise ValueError(
                        f"{stock.symbol} has insufficient "
                        "remaining account exposure allowance "
                        "for one share."
                    )

                raise ValueError(
                    f"{stock.symbol} limit-buy price exceeds "
                    "the maximum position value."
                )

            raise ValueError(
                f"{stock.symbol} risk budget is too small "
                "for one share."
            )

        return WebullPreviewRequest(
            symbol=stock.symbol,
            quantity=quantity,
            limit_price=round(limit_price, 4),
            target_price=round(target_price, 4),
            trading_stop_loss=round(
                trading_stop,
                4,
            ),
            risk_per_share=round(
                risk_per_share,
                4,
            ),
            planned_risk=round(
                quantity * risk_per_share,
                2,
            ),
            estimated_position_value=round(
                quantity * limit_price,
                2,
            ),
            max_position_value=round(
                effective_max_position_value,
                2,
            ),
            sizing_constraint=sizing_constraint,
            client_order_id=(
                WebullPreviewClient
                ._client_order_id(stock.symbol)
            ),
        )

    def preview(
            self,
            request: WebullPreviewRequest,
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
                "quantity": str(request.quantity),
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
                "Webull preview failed with "
                f"HTTP {response.status_code}: "
                f"{response.text}"
            )

        result = response.json()

        if not isinstance(result, dict):
            raise RuntimeError(
                "Webull preview returned invalid data."
            )

        return {
            "status": "PREVIEW READY",
            "submitted": False,
            "symbol": request.symbol,
            "quantity": request.quantity,
            "limitBuy": request.limit_price,
            "target": request.target_price,
            "tradingStopLoss": (
                request.trading_stop_loss
            ),
            "riskPerShare": request.risk_per_share,
            "plannedRisk": request.planned_risk,
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
                result.get("estimated_cost", 0)
            ),
            "estimatedTransactionFee": float(
                result.get(
                    "estimated_transaction_fee",
                    0,
                )
            ),
            "currency": result.get(
                "currency",
                "USD",
            ),
        }
