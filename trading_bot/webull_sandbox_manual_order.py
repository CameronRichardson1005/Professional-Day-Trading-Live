from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import math
import re
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
        clock: Callable[
            [],
            datetime,
        ] | None = None,
        client_order_id_factory: (
            Callable[[], str] | None
        ) = None,
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
