from __future__ import annotations

from .webull_execution import (
    WebullExecutionMode,
    require_safe_execution_mode,
)
from .webull_reduce_only_close import (
    WebullReduceOnlyCloseIntent,
    WebullReduceOnlyCloseLedger,
    WebullReduceOnlyCloseRecord,
)
from .webull_sandbox_broker import (
    WebullBrokerOrderState,
    WebullSandboxBroker,
    WebullSandboxBrokerError,
)


class WebullReduceOnlyCloseManagerError(
    RuntimeError
):
    pass


def _close_status(
    broker_status: str,
) -> str:
    status = broker_status.strip().upper()

    if status in {
        "FILLED",
        "FINAL_FILLED",
    }:
        return "FILLED"

    if status in {
        "PARTIAL_FILLED",
        "PARTIALLY_FILLED",
        "PARTIAL",
    }:
        return "PARTIALLY_FILLED"

    if status in {
        "CANCELLED",
        "CANCELED",
        "EXPIRED",
    }:
        return "CANCELLED"

    if status in {
        "FAILED",
        "REJECTED",
        "PLACE_FAILED",
    }:
        return "REJECTED"

    if status in {
        "SUBMITTED",
        "NEW",
        "PENDING_NEW",
        "WORKING",
    }:
        return "SUBMITTED"

    return "BROKER_STATE_UNKNOWN"


class WebullSandboxReduceOnlyCloseManager:
    """
    Sandbox-only coordinator for reduce-only SELL orders.

    The normal Webull execution manager remains BUY-only.
    """

    def __init__(
        self,
        *,
        broker: WebullSandboxBroker,
        ledger: WebullReduceOnlyCloseLedger,
        execution_mode: str = "SANDBOX",
    ) -> None:
        mode = require_safe_execution_mode(
            execution_mode
        )

        if mode is not WebullExecutionMode.SANDBOX:
            raise WebullReduceOnlyCloseManagerError(
                "SANDBOX_MODE_REQUIRED"
            )

        self.broker = broker
        self.ledger = ledger
        self.execution_mode = mode

    def _fail_broker_mismatch(
        self,
        *,
        client_order_id: str,
        reason: str,
    ) -> None:
        self.ledger.mark_state(
            client_order_id=client_order_id,
            status="BROKER_STATE_UNKNOWN",
            last_error=reason,
        )

        raise WebullReduceOnlyCloseManagerError(
            reason
        )

    def _validate_broker_state(
        self,
        *,
        local: WebullReduceOnlyCloseRecord,
        state: WebullBrokerOrderState,
    ) -> None:
        if state.symbol != local.symbol:
            self._fail_broker_mismatch(
                client_order_id=(
                    local.client_order_id
                ),
                reason=(
                    "CLOSE_BROKER_SYMBOL_MISMATCH"
                ),
            )

        if state.side != "SELL":
            self._fail_broker_mismatch(
                client_order_id=(
                    local.client_order_id
                ),
                reason=(
                    "CLOSE_BROKER_SIDE_NOT_SELL"
                ),
            )

        if state.quantity != local.quantity:
            self._fail_broker_mismatch(
                client_order_id=(
                    local.client_order_id
                ),
                reason=(
                    "CLOSE_BROKER_QUANTITY_MISMATCH"
                ),
            )

        if (
            state.limit_price is None
            or abs(
                float(state.limit_price)
                - float(local.limit_price)
            )
            > 0.000001
        ):
            self._fail_broker_mismatch(
                client_order_id=(
                    local.client_order_id
                ),
                reason=(
                    "CLOSE_BROKER_PRICE_MISMATCH"
                ),
            )

        if state.filled_quantity > local.quantity:
            self._fail_broker_mismatch(
                client_order_id=(
                    local.client_order_id
                ),
                reason=(
                    "CLOSE_FILLED_QUANTITY_EXCEEDS_ORDER"
                ),
            )

    def reconcile(
        self,
        *,
        client_order_id: str,
    ) -> WebullReduceOnlyCloseRecord:
        key = client_order_id.strip()

        if not key:
            raise WebullReduceOnlyCloseManagerError(
                "CLIENT_ORDER_ID_REQUIRED"
            )

        local = self.ledger.load().get(key)

        if local is None:
            raise WebullReduceOnlyCloseManagerError(
                "CLOSE_ORDER_NOT_FOUND"
            )

        try:
            state = self.broker.get_order_detail(
                client_order_id=key
            )
        except WebullSandboxBrokerError as error:
            self.ledger.mark_state(
                client_order_id=key,
                status="BROKER_STATE_UNKNOWN",
                last_error=str(error),
            )

            raise WebullReduceOnlyCloseManagerError(
                "CLOSE_RECONCILIATION_FAILED:"
                f"{error}"
            ) from error

        self._validate_broker_state(
            local=local,
            state=state,
        )

        return self.ledger.record_broker_state(
            client_order_id=key,
            broker_status=(
                state.broker_status
            ),
            status=_close_status(
                state.broker_status
            ),
            broker_order_id=(
                state.broker_order_id
            ),
            filled_quantity=(
                state.filled_quantity
            ),
            average_fill_price=(
                state.average_fill_price
            ),
        )

    def submit(
        self,
        *,
        intent: WebullReduceOnlyCloseIntent,
        management_armed: bool,
    ) -> WebullReduceOnlyCloseRecord:
        if not management_armed:
            raise WebullReduceOnlyCloseManagerError(
                "ORDER_MANAGEMENT_NOT_ARMED"
            )

        if intent.side != "SELL":
            raise WebullReduceOnlyCloseManagerError(
                "REDUCE_ONLY_CLOSE_MUST_BE_SELL"
            )

        try:
            self.ledger.add_intent(intent)
        except Exception as error:
            raise WebullReduceOnlyCloseManagerError(
                "CLOSE_INTENT_NOT_ACCEPTED:"
                f"{error}"
            ) from error

        self.ledger.mark_state(
            client_order_id=(
                intent.client_order_id
            ),
            status="SUBMITTING",
            last_error=None,
        )

        try:
            self.broker.place_reduce_only_close(
                intent,
                management_enabled=True,
            )
        except WebullSandboxBrokerError as error:
            self.ledger.mark_state(
                client_order_id=(
                    intent.client_order_id
                ),
                status=(
                    "SUBMISSION_UNKNOWN"
                    if error.ambiguous
                    else "REJECTED"
                ),
                last_error=str(error),
            )

            raise WebullReduceOnlyCloseManagerError(
                "CLOSE_SUBMISSION_FAILED:"
                f"{error}"
            ) from error

        return self.reconcile(
            client_order_id=(
                intent.client_order_id
            )
        )
