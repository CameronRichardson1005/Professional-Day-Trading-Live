from __future__ import annotations

from .webull_execution import (
    WebullExecutionMode,
    WebullTradeIntent,
    require_safe_execution_mode,
)
from .webull_execution_ledger import (
    WebullExecutionLedger,
    WebullExecutionLedgerError,
    WebullExecutionRecord,
)
from .webull_safety import (
    WebullAccountState,
    WebullOrderProposal,
    WebullReplacementProposal,
    WebullSafetyGate,
)
from .webull_sandbox_broker import (
    WebullBrokerOrderState,
    WebullSandboxBroker,
    WebullSandboxBrokerError,
)


class WebullExecutionManagerError(RuntimeError):
    pass


def _ledger_status(
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


class WebullSandboxExecutionManager:
    """
    Coordinates safety, durable intent state, sandbox broker
    operations, reconciliation, and manual overrides.

    This class cannot operate in a live execution mode.
    """

    def __init__(
        self,
        *,
        broker: WebullSandboxBroker,
        ledger: WebullExecutionLedger,
        execution_mode: str = "SANDBOX",
    ) -> None:
        mode = require_safe_execution_mode(
            execution_mode
        )

        if mode is not WebullExecutionMode.SANDBOX:
            raise WebullExecutionManagerError(
                "SANDBOX_MODE_REQUIRED"
            )

        self.broker = broker
        self.ledger = ledger
        self.execution_mode = mode

    @staticmethod
    def _check_safety(
        *,
        intent: WebullTradeIntent,
        account: WebullAccountState,
    ) -> None:
        proposal = WebullOrderProposal(
            symbol=intent.symbol,
            side=intent.side,
            quantity=intent.quantity,
            limit_price=intent.limit_price,
            manually_approved=False,
        )

        decision = WebullSafetyGate.evaluate(
            account=account,
            proposal=proposal,
            require_manual_approval=False,
        )

        if not decision.allowed:
            raise WebullExecutionManagerError(
                "SAFETY_GATE_REJECTED:"
                f"{decision.reason}"
            )

    @staticmethod
    def _check_replacement_safety(
        *,
        current: WebullExecutionRecord,
        account: WebullAccountState,
        quantity: int,
        limit_price: float,
    ) -> None:
        proposal = WebullReplacementProposal(
            symbol=current.symbol,
            side=current.side,
            current_quantity=current.quantity,
            current_limit_price=current.limit_price,
            current_filled_quantity=(
                current.filled_quantity
            ),
            replacement_quantity=quantity,
            replacement_limit_price=limit_price,
        )

        decision = (
            WebullSafetyGate
            .evaluate_replacement(
                account=account,
                proposal=proposal,
            )
        )

        if not decision.allowed:
            raise WebullExecutionManagerError(
                "REPLACEMENT_SAFETY_GATE_REJECTED:"
                f"{decision.reason}"
            )

    def reconcile(
        self,
        *,
        client_order_id: str,
    ) -> WebullExecutionRecord:
        try:
            broker_state = (
                self.broker.get_order_detail(
                    client_order_id=(
                        client_order_id
                    ),
                )
            )
        except WebullSandboxBrokerError as error:
            self.ledger.mark_operation_state(
                client_order_id=client_order_id,
                status="BROKER_STATE_UNKNOWN",
                last_error=str(error),
            )

            raise WebullExecutionManagerError(
                f"RECONCILIATION_FAILED:{error}"
            ) from error

        return self._record_broker_state(
            broker_state
        )

    def _record_broker_state(
        self,
        state: WebullBrokerOrderState,
    ) -> WebullExecutionRecord:
        return self.ledger.record_broker_state(
            client_order_id=(
                state.client_order_id
            ),
            broker_status=(
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
            quantity=state.quantity,
            limit_price=state.limit_price,
            status=_ledger_status(
                state.broker_status
            ),
        )

    def submit(
        self,
        *,
        intent: WebullTradeIntent,
        account: WebullAccountState,
    ) -> WebullExecutionRecord:
        self._check_safety(
            intent=intent,
            account=account,
        )

        try:
            self.ledger.add_intent(
                intent=intent,
                execution_mode=(
                    self.execution_mode
                ),
            )
        except WebullExecutionLedgerError as error:
            raise WebullExecutionManagerError(
                f"INTENT_NOT_ACCEPTED:{error}"
            ) from error

        self.ledger.mark_operation_state(
            client_order_id=(
                intent.client_order_id
            ),
            status="SUBMITTING",
        )

        try:
            self.broker.place_order(
                intent
            )

        except WebullSandboxBrokerError as error:
            status = (
                "SUBMISSION_UNKNOWN"
                if error.ambiguous
                else "REJECTED"
            )

            self.ledger.mark_operation_state(
                client_order_id=(
                    intent.client_order_id
                ),
                status=status,
                last_error=str(error),
            )

            raise WebullExecutionManagerError(
                f"SUBMISSION_FAILED:{error}"
            ) from error

        # Never infer success from the placement response alone.
        # Read the order back by client_order_id.
        return self.reconcile(
            client_order_id=(
                intent.client_order_id
            )
        )

    def replace_manual(
        self,
        *,
        client_order_id: str,
        quantity: int,
        limit_price: float,
        reason: str,
        account: WebullAccountState,
        management_armed: bool,
    ) -> WebullExecutionRecord:
        if not management_armed:
            raise WebullExecutionManagerError(
                "ORDER_MANAGEMENT_NOT_ARMED"
            )

        # Establish authoritative broker state before deciding
        # whether replacement is permitted.
        current = self.reconcile(
            client_order_id=client_order_id
        )

        if current.status not in {
            "SUBMITTED",
            "PARTIALLY_FILLED",
        }:
            raise WebullExecutionManagerError(
                "ORDER_NOT_REPLACEABLE:"
                f"{current.status}"
            )

        if current.cancel_requested:
            raise WebullExecutionManagerError(
                "ORDER_CANCEL_ALREADY_REQUESTED"
            )

        # Safety is checked BEFORE creating a manual override or
        # durable replacement request, so rejected modifications
        # do not pollute the execution state.
        self._check_replacement_safety(
            current=current,
            account=account,
            quantity=quantity,
            limit_price=limit_price,
        )

        self.ledger.mark_manual_override(
            client_order_id=client_order_id,
            reason=reason,
        )

        # Persist exactly what we intend to change before the
        # broker mutation. Ambiguous transport failures therefore
        # remain recoverable without a blind retry.
        self.ledger.mark_replace_requested(
            client_order_id=client_order_id,
            quantity=quantity,
            limit_price=limit_price,
        )

        try:
            self.broker.replace_order(
                client_order_id=(
                    client_order_id
                ),
                quantity=quantity,
                limit_price=limit_price,
                management_enabled=(
                    management_armed
                ),
            )

        except WebullSandboxBrokerError as error:
            self.ledger.mark_operation_state(
                client_order_id=(
                    client_order_id
                ),
                status=(
                    "BROKER_STATE_UNKNOWN"
                    if error.ambiguous
                    else "ERROR"
                ),
                last_error=str(error),
            )

            raise WebullExecutionManagerError(
                f"REPLACEMENT_FAILED:{error}"
            ) from error

        return self.reconcile_replacement(
            client_order_id=client_order_id,
            quantity=quantity,
            limit_price=limit_price,
        )

    def reconcile_replacement(
        self,
        *,
        client_order_id: str,
        quantity: int,
        limit_price: float,
    ) -> WebullExecutionRecord:
        result = self.reconcile(
            client_order_id=client_order_id
        )

        if result.status in {
            "FILLED",
            "CANCELLED",
            "REJECTED",
        }:
            return self.ledger.clear_replace_request(
                client_order_id=client_order_id
            )

        quantity_matches = (
            result.quantity == quantity
        )

        price_matches = (
            abs(
                float(result.limit_price)
                - float(limit_price)
            )
            <= 0.000001
        )

        if (
            quantity_matches
            and price_matches
        ):
            return self.ledger.clear_replace_request(
                client_order_id=client_order_id
            )

        return self.ledger.mark_operation_state(
            client_order_id=client_order_id,
            status="REPLACE_PENDING",
            last_error=None,
        )

    def cancel_manual(
        self,
        *,
        client_order_id: str,
        reason: str,
    ) -> WebullExecutionRecord:
        self.ledger.mark_manual_override(
            client_order_id=client_order_id,
            reason=reason,
        )

        self.ledger.mark_cancel_requested(
            client_order_id=client_order_id
        )

        try:
            self.broker.cancel_order(
                client_order_id=(
                    client_order_id
                )
            )

        except WebullSandboxBrokerError as error:
            self.ledger.mark_operation_state(
                client_order_id=(
                    client_order_id
                ),
                status=(
                    "BROKER_STATE_UNKNOWN"
                    if error.ambiguous
                    else "ERROR"
                ),
                last_error=str(error),
            )

            raise WebullExecutionManagerError(
                f"CANCELLATION_FAILED:{error}"
            ) from error

        result = self.reconcile(
            client_order_id=client_order_id
        )

        if result.status in {
            "SUBMITTED",
            "PARTIALLY_FILLED",
            "REPLACE_PENDING",
            "CANCEL_PENDING",
        }:
            return self.mark_cancel_pending(
                client_order_id=client_order_id
            )

        return result

    def mark_cancel_pending(
        self,
        *,
        client_order_id: str,
    ) -> WebullExecutionRecord:
        """
        Preserve the fact that cancellation has been requested
        while Webull still reports the order as active.
        """

        return self.ledger.mark_operation_state(
            client_order_id=client_order_id,
            status="CANCEL_PENDING",
            last_error=None,
        )
