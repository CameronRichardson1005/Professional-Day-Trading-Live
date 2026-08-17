from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .config import (
    WEBULL_EXECUTION_MODE,
    WEBULL_SANDBOX_ACCOUNT_ID,
    WEBULL_SANDBOX_APP_KEY,
    WEBULL_SANDBOX_APP_SECRET,
    WEBULL_SANDBOX_ORDER_SUBMISSION_ENABLED,
)
from .webull_sdk_safety import (
    build_quiet_trade_client,
)
from .webull_execution import (
    WebullExecutionMode,
    WebullTradeIntent,
    require_safe_execution_mode,
)


SANDBOX_ENDPOINT = "api.sandbox.webull.com"


class WebullSandboxBrokerError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        ambiguous: bool = False,
    ) -> None:
        super().__init__(message)
        self.ambiguous = ambiguous


@dataclass(frozen=True)
class WebullBrokerOrderState:
    client_order_id: str
    broker_order_id: str | None
    broker_status: str
    quantity: int | None
    limit_price: float | None
    filled_quantity: float
    average_fill_price: float | None
    symbol: str | None = None
    side: str | None = None


def _walk_dicts(value: Any):
    if isinstance(value, dict):
        yield value

        for child in value.values():
            yield from _walk_dicts(child)

    elif isinstance(value, list):
        for child in value:
            yield from _walk_dicts(child)


def _float_or_none(value: Any) -> float | None:
    if value in {None, ""}:
        return None

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value: Any) -> int | None:
    number = _float_or_none(value)

    if number is None:
        return None

    if number <= 0:
        return None

    if not number.is_integer():
        return None

    return int(number)


def parse_order_detail(
    payload: Any,
    *,
    client_order_id: str,
) -> WebullBrokerOrderState:
    key = client_order_id.strip()

    if not key:
        raise WebullSandboxBrokerError(
            "CLIENT_ORDER_ID_REQUIRED"
        )

    candidates = [
        item
        for item in _walk_dicts(payload)
        if str(
            item.get(
                "client_order_id",
                "",
            )
        ).strip() == key
    ]

    if not candidates:
        raise WebullSandboxBrokerError(
            "ORDER_DETAIL_NOT_FOUND"
        )

    # Prefer the object carrying broker status information.
    item = next(
        (
            candidate
            for candidate in candidates
            if (
                candidate.get("status") is not None
                or candidate.get(
                    "order_status"
                ) is not None
            )
        ),
        candidates[0],
    )

    status = str(
        item.get(
            "status",
            item.get(
                "order_status",
                "",
            ),
        )
    ).strip().upper()

    if not status:
        raise WebullSandboxBrokerError(
            "ORDER_DETAIL_STATUS_MISSING"
        )

    filled_quantity = _float_or_none(
        item.get(
            "filled_quantity",
            item.get(
                "filled_qty",
                0,
            ),
        )
    )

    if filled_quantity is None:
        filled_quantity = 0.0

    if filled_quantity < 0:
        raise WebullSandboxBrokerError(
            "ORDER_DETAIL_FILLED_QUANTITY_INVALID"
        )

    return WebullBrokerOrderState(
        client_order_id=key,
        broker_order_id=(
            None
            if not item.get("order_id")
            else str(
                item["order_id"]
            ).strip()
        ),
        broker_status=status,
        quantity=_int_or_none(
            item.get(
                "total_quantity",
                item.get(
                    "quantity",
                    item.get("qty"),
                ),
            )
        ),
        limit_price=_float_or_none(
            item.get("limit_price")
        ),
        filled_quantity=filled_quantity,
        average_fill_price=_float_or_none(
            item.get(
                "filled_price",
                item.get(
                    "average_fill_price"
                ),
            )
        ),
        symbol=(
            None
            if not item.get("symbol")
            else str(
                item["symbol"]
            ).strip().upper()
        ),
        side=(
            None
            if not item.get("side")
            else str(
                item["side"]
            ).strip().upper()
        ),
    )


class WebullSandboxBroker:
    """
    Webull Trading API sandbox adapter.

    Broker-mutating methods require BOTH:
    - WEBULL_EXECUTION_MODE=SANDBOX
    - WEBULL_SANDBOX_ORDER_SUBMISSION_ENABLED=true

    The endpoint cannot be redirected by an environment variable.
    """

    def __init__(
        self,
        *,
        trade_client: Any | None = None,
        account_id: str | None = None,
        execution_mode: str = WEBULL_EXECUTION_MODE,
        submission_enabled: bool = (
            WEBULL_SANDBOX_ORDER_SUBMISSION_ENABLED
        ),
    ) -> None:
        mode = require_safe_execution_mode(
            execution_mode
        )

        if mode is not WebullExecutionMode.SANDBOX:
            raise WebullSandboxBrokerError(
                "SANDBOX_MODE_REQUIRED"
            )

        self.execution_mode = mode
        self.submission_enabled = bool(
            submission_enabled
        )

        selected_account = (
            account_id
            if account_id is not None
            else WEBULL_SANDBOX_ACCOUNT_ID
        ).strip()

        if not selected_account:
            raise WebullSandboxBrokerError(
                "SANDBOX_ACCOUNT_ID_REQUIRED"
            )

        self.account_id = selected_account

        if trade_client is not None:
            self._trade_client = trade_client
            return

        if not WEBULL_SANDBOX_APP_KEY:
            raise WebullSandboxBrokerError(
                "SANDBOX_APP_KEY_REQUIRED"
            )

        if not WEBULL_SANDBOX_APP_SECRET:
            raise WebullSandboxBrokerError(
                "SANDBOX_APP_SECRET_REQUIRED"
            )

        self._trade_client = (
            build_quiet_trade_client(
                app_key=WEBULL_SANDBOX_APP_KEY,
                app_secret=WEBULL_SANDBOX_APP_SECRET,
                endpoint=SANDBOX_ENDPOINT,
            )
        )

    def _require_submission_enabled(
        self,
    ) -> None:
        if not self.submission_enabled:
            raise WebullSandboxBrokerError(
                "SANDBOX_SUBMISSION_NOT_ARMED"
            )

    @staticmethod
    def _check_response(
        response: Any,
        *,
        operation: str,
    ) -> None:
        status_code = getattr(
            response,
            "status_code",
            None,
        )

        if status_code != 200:
            raise WebullSandboxBrokerError(
                f"{operation}_HTTP_{status_code!r}",
                ambiguous=False,
            )

    def place_order(
        self,
        intent: WebullTradeIntent,
    ) -> None:
        self._require_submission_enabled()

        try:
            response = (
                self._trade_client.order_v3
                .place_order(
                    self.account_id,
                    [
                        intent.broker_payload()
                    ],
                )
            )
        except Exception as error:
            raise WebullSandboxBrokerError(
                "PLACE_ORDER_TRANSPORT_ERROR",
                ambiguous=True,
            ) from error

        self._check_response(
            response,
            operation="PLACE_ORDER",
        )

    def replace_order(
        self,
        *,
        client_order_id: str,
        quantity: int,
        limit_price: float,
    ) -> None:
        self._require_submission_enabled()

        key = client_order_id.strip()

        if not key:
            raise WebullSandboxBrokerError(
                "CLIENT_ORDER_ID_REQUIRED"
            )

        if quantity <= 0:
            raise WebullSandboxBrokerError(
                "INVALID_REPLACEMENT_QUANTITY"
            )

        if limit_price <= 0:
            raise WebullSandboxBrokerError(
                "INVALID_REPLACEMENT_PRICE"
            )

        modify_orders = [
            {
                "client_order_id": key,
                "quantity": str(quantity),
                "limit_price": (
                    f"{float(limit_price):.4f}"
                ),
            }
        ]

        try:
            response = (
                self._trade_client.order_v3
                .replace_order(
                    self.account_id,
                    modify_orders,
                )
            )
        except Exception as error:
            raise WebullSandboxBrokerError(
                "REPLACE_ORDER_TRANSPORT_ERROR",
                ambiguous=True,
            ) from error

        self._check_response(
            response,
            operation="REPLACE_ORDER",
        )

    def cancel_order(
        self,
        *,
        client_order_id: str,
    ) -> None:
        # Cancellation intentionally remains available when
        # new-order submission is disarmed. Disarming entries
        # must never trap an already-open order.
        key = client_order_id.strip()

        if not key:
            raise WebullSandboxBrokerError(
                "CLIENT_ORDER_ID_REQUIRED"
            )

        try:
            response = (
                self._trade_client.order_v3
                .cancel_order(
                    self.account_id,
                    key,
                )
            )
        except Exception as error:
            raise WebullSandboxBrokerError(
                "CANCEL_ORDER_TRANSPORT_ERROR",
                ambiguous=True,
            ) from error

        self._check_response(
            response,
            operation="CANCEL_ORDER",
        )

    def get_order_detail(
        self,
        *,
        client_order_id: str,
    ) -> WebullBrokerOrderState:
        key = client_order_id.strip()

        if not key:
            raise WebullSandboxBrokerError(
                "CLIENT_ORDER_ID_REQUIRED"
            )

        try:
            response = (
                self._trade_client.order_v3
                .get_order_detail(
                    self.account_id,
                    key,
                )
            )
        except Exception as error:
            raise WebullSandboxBrokerError(
                "ORDER_DETAIL_TRANSPORT_ERROR",
                ambiguous=True,
            ) from error

        self._check_response(
            response,
            operation="ORDER_DETAIL",
        )

        try:
            payload = response.json()
        except Exception as error:
            raise WebullSandboxBrokerError(
                "ORDER_DETAIL_INVALID_JSON",
                ambiguous=True,
            ) from error

        return parse_order_detail(
            payload,
            client_order_id=key,
        )
