from __future__ import annotations

from .webull_account_parser import (
    ParsedWebullPosition,
)
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
from .webull_sandbox_preflight import (
    WebullSandboxAccountSnapshotClient,
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
        "CANCEL_PENDING",
        "PENDING_CANCEL",
    }:
        return "CANCEL_PENDING"

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
        snapshot_client: WebullSandboxAccountSnapshotClient,
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
        self.snapshot_client = snapshot_client
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

    def _reject_other_active_close(
        self,
        *,
        intent: WebullReduceOnlyCloseIntent,
    ) -> None:
        active_statuses = {
            "PREPARED",
            "SUBMITTING",
            "SUBMITTED",
            "SUBMISSION_UNKNOWN",
            "BROKER_STATE_UNKNOWN",
            "PARTIALLY_FILLED",
            "CANCEL_PENDING",
            "POSITION_STATE_UNKNOWN",
        }

        for record in self.ledger.load().values():
            if (
                record.client_order_id
                != intent.client_order_id
                and record.symbol == intent.symbol
                and record.status in active_statuses
            ):
                raise WebullReduceOnlyCloseManagerError(
                    "ACTIVE_CLOSE_ALREADY_EXISTS"
                )

    def _reject_pre_submit(
        self,
        *,
        client_order_id: str,
        reason: str,
    ) -> None:
        self.ledger.mark_state(
            client_order_id=client_order_id,
            status="REJECTED",
            last_error=reason,
        )

        raise WebullReduceOnlyCloseManagerError(
            reason
        )

    def _validate_pre_submit_snapshot(
        self,
        *,
        intent: WebullReduceOnlyCloseIntent,
        snapshot,
    ) -> None:
        account = snapshot.account_state

        if (
            account.account_type
            .strip()
            .upper()
            != "CASH"
        ):
            self._reject_pre_submit(
                client_order_id=(
                    intent.client_order_id
                ),
                reason=(
                    "CLOSE_REQUIRES_CASH_ACCOUNT"
                ),
            )

        if not account.data_is_current:
            self._reject_pre_submit(
                client_order_id=(
                    intent.client_order_id
                ),
                reason=(
                    "CLOSE_ACCOUNT_DATA_STALE"
                ),
            )

        matches = [
            position
            for position in snapshot.positions
            if (
                position.symbol
                .strip()
                .upper()
                == intent.symbol
            )
        ]

        if len(matches) != 1:
            self._reject_pre_submit(
                client_order_id=(
                    intent.client_order_id
                ),
                reason=(
                    "CLOSE_POSITION_NOT_EXACTLY_ONE"
                ),
            )

        fresh_quantity = float(
            matches[0].quantity
        )

        if (
            abs(
                fresh_quantity
                - float(
                    intent.confirmed_position_quantity
                )
            )
            > 0.00001
        ):
            self._reject_pre_submit(
                client_order_id=(
                    intent.client_order_id
                ),
                reason=(
                    "CLOSE_POSITION_CHANGED_BEFORE_SUBMIT"
                ),
            )

        if fresh_quantity < intent.quantity:
            self._reject_pre_submit(
                client_order_id=(
                    intent.client_order_id
                ),
                reason=(
                    "CLOSE_QUANTITY_EXCEEDS_FRESH_POSITION"
                ),
            )

        for order in snapshot.open_orders:
            if (
                order.symbol
                .strip()
                .upper()
                == intent.symbol
                and order.side
                .strip()
                .upper()
                == "SELL"
                and float(
                    order.remaining_quantity
                )
                > 0
            ):
                self._reject_pre_submit(
                    client_order_id=(
                        intent.client_order_id
                    ),
                    reason=(
                        "OPEN_SELL_ORDER_ALREADY_EXISTS"
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

    def reconcile_position(
        self,
        *,
        client_order_id: str,
        positions: tuple[
            ParsedWebullPosition,
            ...
        ] | list[ParsedWebullPosition],
    ) -> WebullReduceOnlyCloseRecord:
        """
        Confirm Webull position quantity reflects the fills
        already reported by Order Detail.

        Exact expected quantity:
            original confirmed position
            - broker-confirmed SELL fills

        Any unexplained difference fails closed because it may
        represent a manual trade, stale account data, or another
        process changing the position.
        """

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

        if local.filled_quantity <= 0:
            raise WebullReduceOnlyCloseManagerError(
                "CLOSE_HAS_NO_FILL_TO_RECONCILE"
            )

        expected = round(
            float(
                local.confirmed_position_quantity
            )
            - float(local.filled_quantity),
            5,
        )

        if expected < -0.00001:
            self.ledger.mark_state(
                client_order_id=key,
                status="POSITION_STATE_UNKNOWN",
                last_error=(
                    "CLOSE_EXPECTED_POSITION_NEGATIVE"
                ),
            )

            raise WebullReduceOnlyCloseManagerError(
                "CLOSE_EXPECTED_POSITION_NEGATIVE"
            )

        matches = [
            item
            for item in positions
            if item.symbol.strip().upper()
            == local.symbol
        ]

        if len(matches) > 1:
            self.ledger.mark_state(
                client_order_id=key,
                status="POSITION_STATE_UNKNOWN",
                last_error=(
                    "CLOSE_DUPLICATE_POSITION_RECORD"
                ),
            )

            raise WebullReduceOnlyCloseManagerError(
                "CLOSE_DUPLICATE_POSITION_RECORD"
            )

        observed = (
            0.0
            if not matches
            else float(
                matches[0].quantity
            )
        )

        if abs(
            observed - expected
        ) > 0.00001:
            reason = (
                "CLOSE_POSITION_QUANTITY_MISMATCH:"
                f"expected={expected}:"
                f"observed={observed}"
            )

            self.ledger.mark_state(
                client_order_id=key,
                status="POSITION_STATE_UNKNOWN",
                last_error=reason,
            )

            raise WebullReduceOnlyCloseManagerError(
                reason
            )

        return (
            self.ledger
            .mark_position_reconciled(
                client_order_id=key
            )
        )

    def cancel(
        self,
        *,
        client_order_id: str,
    ) -> WebullReduceOnlyCloseRecord:
        """
        Rescue-cancel an outstanding reduce-only close order.

        Like normal order cancellation, this deliberately does
        not require either entry or management arming. Disarming
        trading must never trap an outstanding broker order.
        """

        key = client_order_id.strip()

        if not key:
            raise WebullReduceOnlyCloseManagerError(
                "CLIENT_ORDER_ID_REQUIRED"
            )

        current = self.reconcile(
            client_order_id=key
        )

        if current.status in {
            "CANCELLED",
            "FILLED",
        }:
            return current

        if current.status not in {
            "SUBMITTED",
            "PARTIALLY_FILLED",
            "CANCEL_PENDING",
        }:
            raise WebullReduceOnlyCloseManagerError(
                "CLOSE_ORDER_NOT_CANCELLABLE:"
                f"{current.status}"
            )

        self.ledger.mark_state(
            client_order_id=key,
            status="CANCEL_PENDING",
            last_error=None,
        )

        try:
            self.broker.cancel_order(
                client_order_id=key
            )

        except WebullSandboxBrokerError as error:
            self.ledger.mark_state(
                client_order_id=key,
                status=(
                    "BROKER_STATE_UNKNOWN"
                    if error.ambiguous
                    else "ERROR"
                ),
                last_error=str(error),
            )

            raise WebullReduceOnlyCloseManagerError(
                "CLOSE_CANCELLATION_FAILED:"
                f"{error}"
            ) from error

        result = self.reconcile(
            client_order_id=key
        )

        if result.status in {
            "SUBMITTED",
            "PARTIALLY_FILLED",
            "CANCEL_PENDING",
        }:
            return self.ledger.mark_state(
                client_order_id=key,
                status="CANCEL_PENDING",
                last_error=None,
            )

        return result

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

        self._reject_other_active_close(
            intent=intent
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
            snapshot = (
                self.snapshot_client
                .get_snapshot()
            )

        except Exception as error:
            self.ledger.mark_state(
                client_order_id=(
                    intent.client_order_id
                ),
                status="REJECTED",
                last_error=(
                    "CLOSE_PRE_SUBMIT_SNAPSHOT_FAILED"
                ),
            )

            raise WebullReduceOnlyCloseManagerError(
                "CLOSE_PRE_SUBMIT_SNAPSHOT_FAILED"
            ) from error

        self._validate_pre_submit_snapshot(
            intent=intent,
            snapshot=snapshot,
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
