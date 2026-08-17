from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import math
import re
import time
from typing import Callable

from .webull_execution import (
    WebullTradeIntent,
    generate_client_order_id,
)
from .webull_execution_ledger import (
    WebullExecutionRecord,
)
from .webull_execution_manager import (
    WebullSandboxExecutionManager,
)
from .webull_sandbox_preflight import (
    WebullSandboxAccountSnapshotClient,
    WebullSandboxPreflight,
)


CONFIRMATION_PHRASE = "CONFIRM_SANDBOX_ORDER"
CANCEL_CONFIRMATION_PHRASE = "CONFIRM_SANDBOX_CANCEL"
REPLACE_CONFIRMATION_PHRASE = "CONFIRM_SANDBOX_REPLACE"

_SYMBOL_PATTERN = re.compile(
    r"^[A-Z][A-Z0-9.-]{0,14}$"
)


class WebullSandboxManualOrderError(
    RuntimeError
):
    pass


@dataclass(frozen=True)
class WebullSandboxManualOrderRequest:
    symbol: str
    quantity: int
    limit_price: float
    confirmation: str

    def __post_init__(self) -> None:
        symbol = self.symbol.strip().upper()

        if not _SYMBOL_PATTERN.fullmatch(
            symbol
        ):
            raise WebullSandboxManualOrderError(
                "INVALID_SANDBOX_SYMBOL"
            )

        if (
            isinstance(self.quantity, bool)
            or not isinstance(
                self.quantity,
                int,
            )
            or self.quantity <= 0
        ):
            raise WebullSandboxManualOrderError(
                "INVALID_SANDBOX_QUANTITY"
            )

        price = float(
            self.limit_price
        )

        if (
            not math.isfinite(price)
            or price <= 0
        ):
            raise WebullSandboxManualOrderError(
                "INVALID_SANDBOX_LIMIT_PRICE"
            )

        if (
            self.confirmation.strip()
            != CONFIRMATION_PHRASE
        ):
            raise WebullSandboxManualOrderError(
                "SANDBOX_CONFIRMATION_REQUIRED"
            )

        object.__setattr__(
            self,
            "symbol",
            symbol,
        )

        object.__setattr__(
            self,
            "limit_price",
            round(price, 4),
        )


class WebullSandboxManualOrderService:
    """
    Deliberately manual sandbox-only order entry.

    This service does not connect to either trading strategy.
    Every invocation requires:
      1. sandbox execution mode,
      2. sandbox submission arming,
      3. explicit confirmation phrase,
      4. successful fail-closed preflight,
      5. normal execution safety gate.
    """

    def __init__(
        self,
        *,
        preflight: WebullSandboxPreflight,
        snapshot_client: (
            WebullSandboxAccountSnapshotClient
        ),
        execution_manager: (
            WebullSandboxExecutionManager
        ),
        submission_armed: bool,
        management_armed: bool = False,
        clock: Callable[
            [],
            datetime,
        ] | None = None,
        client_order_id_factory: (
            Callable[[], str] | None
        ) = None,
        sleeper: Callable[[float], None] | None = None,
        cancel_poll_attempts: int = 4,
        cancel_poll_interval_seconds: float = 1.1,
        cancel_stabilization_seconds: float = 2.1,
        replace_poll_attempts: int = 4,
        replace_poll_interval_seconds: float = 1.1,
        replace_stabilization_seconds: float = 2.1,
    ) -> None:
        self.preflight = preflight
        self.snapshot_client = (
            snapshot_client
        )
        self.execution_manager = (
            execution_manager
        )
        self.submission_armed = bool(
            submission_armed
        )

        self.management_armed = bool(
            management_armed
        )

        self.clock = (
            clock
            if clock is not None
            else lambda: datetime.now(UTC)
        )

        self.client_order_id_factory = (
            client_order_id_factory
            if client_order_id_factory
            is not None
            else generate_client_order_id
        )

        self.sleeper = (
            sleeper
            if sleeper is not None
            else time.sleep
        )

        if cancel_poll_attempts <= 0:
            raise WebullSandboxManualOrderError(
                "INVALID_CANCEL_POLL_ATTEMPTS"
            )

        if cancel_poll_interval_seconds <= 0:
            raise WebullSandboxManualOrderError(
                "INVALID_CANCEL_POLL_INTERVAL"
            )

        self.cancel_poll_attempts = int(
            cancel_poll_attempts
        )

        self.cancel_poll_interval_seconds = float(
            cancel_poll_interval_seconds
        )

        if cancel_stabilization_seconds < 0:
            raise WebullSandboxManualOrderError(
                "INVALID_CANCEL_STABILIZATION_INTERVAL"
            )

        self.cancel_stabilization_seconds = float(
            cancel_stabilization_seconds
        )

        if replace_poll_attempts <= 0:
            raise WebullSandboxManualOrderError(
                "INVALID_REPLACE_POLL_ATTEMPTS"
            )

        if replace_poll_interval_seconds <= 0:
            raise WebullSandboxManualOrderError(
                "INVALID_REPLACE_POLL_INTERVAL"
            )

        if replace_stabilization_seconds < 0:
            raise WebullSandboxManualOrderError(
                "INVALID_REPLACE_STABILIZATION_INTERVAL"
            )

        self.replace_poll_attempts = int(
            replace_poll_attempts
        )

        self.replace_poll_interval_seconds = float(
            replace_poll_interval_seconds
        )

        self.replace_stabilization_seconds = float(
            replace_stabilization_seconds
        )

    def place(
        self,
        request: WebullSandboxManualOrderRequest,
    ) -> WebullExecutionRecord:
        # Fail before creating any ledger record.
        if not self.submission_armed:
            raise WebullSandboxManualOrderError(
                "SANDBOX_ORDER_SUBMISSION_NOT_ARMED"
            )

        # Request construction already enforced the
        # confirmation phrase.
        if (
            request.confirmation
            != CONFIRMATION_PHRASE
        ):
            raise WebullSandboxManualOrderError(
                "SANDBOX_CONFIRMATION_REQUIRED"
            )

        # Full fail-closed account / broker / ledger
        # reconciliation immediately before the order.
        report = self.preflight.run()

        if not report.allowed:
            raise WebullSandboxManualOrderError(
                "SANDBOX_PREFLIGHT_NOT_ALLOWED"
            )

        # Refresh the actual account state used by the safety
        # gate immediately before submission.
        snapshot = (
            self.snapshot_client
            .get_snapshot()
        )

        now = self.clock()

        if now.tzinfo is None:
            raise WebullSandboxManualOrderError(
                "SANDBOX_CLOCK_MUST_BE_TIMEZONE_AWARE"
            )

        client_order_id = (
            self.client_order_id_factory()
            .strip()
        )

        if not client_order_id:
            raise WebullSandboxManualOrderError(
                "CLIENT_ORDER_ID_REQUIRED"
            )

        intent = WebullTradeIntent(
            client_order_id=(
                client_order_id
            ),
            strategy_name=(
                "MANUAL_SANDBOX_TEST"
            ),
            symbol=request.symbol,
            side="BUY",
            quantity=request.quantity,
            limit_price=(
                request.limit_price
            ),
            created_at=now,
        )

        return (
            self.execution_manager.submit(
                intent=intent,
                account=(
                    snapshot.account_state
                ),
            )
        )


    def cancel(
        self,
        *,
        client_order_id: str,
        confirmation: str,
    ) -> WebullExecutionRecord:
        """
        Cancel one locally tracked sandbox order and wait for
        Webull Order Detail to confirm the final result.

        This is deliberately a rescue operation:
        - it does not require new-order arming;
        - it does not run normal entry preflight;
        - it never equates "cancel request sent" with
          "order confirmed cancelled".
        """

        key = client_order_id.strip()

        if not key:
            raise WebullSandboxManualOrderError(
                "CLIENT_ORDER_ID_REQUIRED"
            )

        if (
            confirmation.strip()
            != CANCEL_CONFIRMATION_PHRASE
        ):
            raise WebullSandboxManualOrderError(
                "SANDBOX_CANCEL_CONFIRMATION_REQUIRED"
            )

        # First establish the broker's current state. This is
        # deliberately read-only and prevents us from issuing a
        # cancel against an already terminal order.
        try:
            current = (
                self.execution_manager
                .reconcile(
                    client_order_id=key
                )
            )

        except Exception as error:
            raise WebullSandboxManualOrderError(
                "SANDBOX_PRE_CANCEL_RECONCILIATION_FAILED:"
                f"{error}"
            ) from error

        if current.status == "CANCELLED":
            return current

        if current.status == "FILLED":
            raise WebullSandboxManualOrderError(
                "SANDBOX_CANCEL_ORDER_FILLED"
            )

        if current.status not in {
            "SUBMITTED",
            "PARTIALLY_FILLED",
            "CANCEL_PENDING",
            "REPLACE_PENDING",
        }:
            raise WebullSandboxManualOrderError(
                "SANDBOX_CANCEL_UNRESOLVED:"
                f"{current.status}"
            )

        # Real sandbox testing showed that cancellation in the
        # same instant as order acceptance can race Webull's
        # internal order propagation. Give the accepted order a
        # short bounded stabilization window before sending the
        # cancellation request.
        if self.cancel_stabilization_seconds:
            self.sleeper(
                self.cancel_stabilization_seconds
            )

        # Re-read after the stabilization window. The order may
        # have filled or been cancelled meanwhile.
        try:
            current = (
                self.execution_manager
                .reconcile(
                    client_order_id=key
                )
            )

        except Exception as error:
            raise WebullSandboxManualOrderError(
                "SANDBOX_PRE_CANCEL_RECONCILIATION_FAILED:"
                f"{error}"
            ) from error

        if current.status == "CANCELLED":
            return current

        if current.status == "FILLED":
            raise WebullSandboxManualOrderError(
                "SANDBOX_CANCEL_ORDER_FILLED"
            )

        if current.status not in {
            "SUBMITTED",
            "PARTIALLY_FILLED",
            "CANCEL_PENDING",
            "REPLACE_PENDING",
        }:
            raise WebullSandboxManualOrderError(
                "SANDBOX_CANCEL_UNRESOLVED:"
                f"{current.status}"
            )

        try:
            result = (
                self.execution_manager
                .cancel_manual(
                    client_order_id=key,
                    reason=(
                        "MANUAL_SANDBOX_TEST_CANCEL"
                    ),
                )
            )

        except Exception as error:
            raise WebullSandboxManualOrderError(
                "SANDBOX_CANCEL_REQUEST_FAILED:"
                f"{error}"
            ) from error

        if result.status == "CANCELLED":
            return result

        if result.status == "FILLED":
            raise WebullSandboxManualOrderError(
                "SANDBOX_CANCEL_ORDER_FILLED"
            )

        if result.status in {
            "REJECTED",
            "BROKER_STATE_UNKNOWN",
            "ERROR",
        }:
            raise WebullSandboxManualOrderError(
                "SANDBOX_CANCEL_UNRESOLVED:"
                f"{result.status}"
            )

        # Order Detail is deliberately polled at a bounded
        # interval. Never busy-loop against the broker.
        for _ in range(
            self.cancel_poll_attempts
        ):
            self.sleeper(
                self.cancel_poll_interval_seconds
            )

            try:
                result = (
                    self.execution_manager
                    .reconcile(
                        client_order_id=key
                    )
                )

            except Exception as error:
                raise WebullSandboxManualOrderError(
                    "SANDBOX_CANCEL_RECONCILIATION_FAILED:"
                    f"{error}"
                ) from error

            if result.status == "CANCELLED":
                return result

            if result.status == "FILLED":
                raise WebullSandboxManualOrderError(
                    "SANDBOX_CANCEL_ORDER_FILLED"
                )

            if result.status in {
                "REJECTED",
                "BROKER_STATE_UNKNOWN",
                "ERROR",
            }:
                raise WebullSandboxManualOrderError(
                    "SANDBOX_CANCEL_UNRESOLVED:"
                    f"{result.status}"
                )

        # Webull still has not confirmed a terminal result.
        # Persist CANCEL_PENDING and fail closed.
        self.execution_manager.mark_cancel_pending(
            client_order_id=key
        )

        raise WebullSandboxManualOrderError(
            "SANDBOX_CANCEL_PENDING"
        )


    def replace(
        self,
        *,
        client_order_id: str,
        quantity: int,
        limit_price: float,
        confirmation: str,
    ) -> WebullExecutionRecord:
        key = client_order_id.strip()

        if not key:
            raise WebullSandboxManualOrderError(
                "CLIENT_ORDER_ID_REQUIRED"
            )

        if (
            isinstance(quantity, bool)
            or not isinstance(quantity, int)
            or quantity <= 0
        ):
            raise WebullSandboxManualOrderError(
                "INVALID_SANDBOX_REPLACE_QUANTITY"
            )

        try:
            price = round(
                float(limit_price),
                4,
            )
        except (
            TypeError,
            ValueError,
        ) as error:
            raise WebullSandboxManualOrderError(
                "INVALID_SANDBOX_REPLACE_PRICE"
            ) from error

        if (
            not math.isfinite(price)
            or price <= 0
        ):
            raise WebullSandboxManualOrderError(
                "INVALID_SANDBOX_REPLACE_PRICE"
            )

        if (
            confirmation.strip()
            != REPLACE_CONFIRMATION_PHRASE
        ):
            raise WebullSandboxManualOrderError(
                "SANDBOX_REPLACE_CONFIRMATION_REQUIRED"
            )

        if not self.management_armed:
            raise WebullSandboxManualOrderError(
                "SANDBOX_ORDER_MANAGEMENT_NOT_ARMED"
            )

        report = self.preflight.run()

        if not report.allowed:
            raise WebullSandboxManualOrderError(
                "SANDBOX_PREFLIGHT_NOT_ALLOWED"
            )

        if self.replace_stabilization_seconds:
            self.sleeper(
                self.replace_stabilization_seconds
            )

        snapshot = (
            self.snapshot_client
            .get_snapshot()
        )

        try:
            result = (
                self.execution_manager
                .replace_manual(
                    client_order_id=key,
                    quantity=quantity,
                    limit_price=price,
                    reason=(
                        "MANUAL_SANDBOX_TEST_REPLACE"
                    ),
                    account=(
                        snapshot.account_state
                    ),
                    management_armed=True,
                )
            )

        except Exception as error:
            raise WebullSandboxManualOrderError(
                "SANDBOX_REPLACE_REQUEST_FAILED:"
                f"{error}"
            ) from error

        def confirmed(record) -> bool:
            return (
                record.status == "SUBMITTED"
                and record.quantity == quantity
                and abs(
                    float(record.limit_price)
                    - price
                )
                <= 0.000001
            )

        if confirmed(result):
            return result

        if result.status == "FILLED":
            raise WebullSandboxManualOrderError(
                "SANDBOX_REPLACE_ORDER_FILLED"
            )

        if result.status == "CANCELLED":
            raise WebullSandboxManualOrderError(
                "SANDBOX_REPLACE_ORDER_CANCELLED"
            )

        if result.status in {
            "REJECTED",
            "BROKER_STATE_UNKNOWN",
            "ERROR",
        }:
            raise WebullSandboxManualOrderError(
                "SANDBOX_REPLACE_UNRESOLVED:"
                f"{result.status}"
            )

        for _ in range(
            self.replace_poll_attempts
        ):
            self.sleeper(
                self.replace_poll_interval_seconds
            )

            try:
                result = (
                    self.execution_manager
                    .reconcile_replacement(
                        client_order_id=key,
                        quantity=quantity,
                        limit_price=price,
                    )
                )

            except Exception as error:
                raise WebullSandboxManualOrderError(
                    "SANDBOX_REPLACE_RECONCILIATION_FAILED:"
                    f"{error}"
                ) from error

            if confirmed(result):
                return result

            if result.status == "FILLED":
                raise WebullSandboxManualOrderError(
                    "SANDBOX_REPLACE_ORDER_FILLED"
                )

            if result.status == "CANCELLED":
                raise WebullSandboxManualOrderError(
                    "SANDBOX_REPLACE_ORDER_CANCELLED"
                )

            if result.status in {
                "REJECTED",
                "BROKER_STATE_UNKNOWN",
                "ERROR",
            }:
                raise WebullSandboxManualOrderError(
                    "SANDBOX_REPLACE_UNRESOLVED:"
                    f"{result.status}"
                )

        raise WebullSandboxManualOrderError(
            "SANDBOX_REPLACE_PENDING"
        )
