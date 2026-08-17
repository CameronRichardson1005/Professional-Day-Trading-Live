from __future__ import annotations

import math

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Callable

from .webull_execution import generate_client_order_id
from .webull_reduce_only_close import (
    WebullReduceOnlyCloseRecord,
    build_reduce_only_close_intent,
)
from .webull_reduce_only_close_manager import (
    WebullSandboxReduceOnlyCloseManager,
)
from .webull_sandbox_preflight import (
    WebullSandboxAccountSnapshotClient,
)


CLOSE_CONFIRMATION_PHRASE = "CONFIRM_SANDBOX_CLOSE"
CLOSE_CANCEL_CONFIRMATION_PHRASE = (
    "CONFIRM_SANDBOX_CLOSE_CANCEL"
)


class WebullSandboxManualCloseError(RuntimeError):
    pass


@dataclass(frozen=True)
class WebullSandboxManualCloseRequest:
    symbol: str
    quantity: int
    limit_price: float
    confirmation: str

    def __post_init__(self) -> None:
        symbol = self.symbol.strip().upper()

        if not symbol:
            raise WebullSandboxManualCloseError(
                "SYMBOL_REQUIRED"
            )

        if (
            isinstance(self.quantity, bool)
            or not isinstance(self.quantity, int)
            or self.quantity <= 0
        ):
            raise WebullSandboxManualCloseError(
                "INVALID_CLOSE_QUANTITY"
            )

        try:
            price = float(self.limit_price)
        except (TypeError, ValueError) as error:
            raise WebullSandboxManualCloseError(
                "INVALID_CLOSE_LIMIT_PRICE"
            ) from error

        if not math.isfinite(price) or price <= 0:
            raise WebullSandboxManualCloseError(
                "INVALID_CLOSE_LIMIT_PRICE"
            )

        if (
            self.confirmation.strip()
            != CLOSE_CONFIRMATION_PHRASE
        ):
            raise WebullSandboxManualCloseError(
                "SANDBOX_CLOSE_CONFIRMATION_REQUIRED"
            )

        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(
            self,
            "limit_price",
            round(price, 4),
        )
        object.__setattr__(
            self,
            "confirmation",
            CLOSE_CONFIRMATION_PHRASE,
        )


class WebullSandboxManualCloseService:
    """
    Explicit manual sandbox reduce-only close preparation.

    This service:
    - requires the independent management arm;
    - reads fresh Webull positions;
    - refuses a second open SELL for the same symbol;
    - creates only a reduce-only SELL intent;
    - does not use the BUY-entry submission arm.
    """

    def __init__(
        self,
        *,
        snapshot_client: WebullSandboxAccountSnapshotClient,
        close_manager: WebullSandboxReduceOnlyCloseManager,
        management_armed: bool,
        clock: Callable[[], datetime] | None = None,
        client_order_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self.snapshot_client = snapshot_client
        self.close_manager = close_manager
        self.management_armed = bool(management_armed)

        self.clock = (
            clock
            if clock is not None
            else lambda: datetime.now(UTC)
        )

        self.client_order_id_factory = (
            client_order_id_factory
            if client_order_id_factory is not None
            else generate_client_order_id
        )

    @staticmethod
    def _has_open_sell(
        *,
        snapshot,
        symbol: str,
    ) -> bool:
        for order in getattr(snapshot, "open_orders", ()):
            if (
                order.symbol.strip().upper() == symbol
                and order.side.strip().upper() == "SELL"
                and float(order.remaining_quantity) > 0
            ):
                return True

        return False

    def close(
        self,
        request: WebullSandboxManualCloseRequest,
    ) -> WebullReduceOnlyCloseRecord:
        if not self.management_armed:
            raise WebullSandboxManualCloseError(
                "SANDBOX_ORDER_MANAGEMENT_NOT_ARMED"
            )

        if request.confirmation != CLOSE_CONFIRMATION_PHRASE:
            raise WebullSandboxManualCloseError(
                "SANDBOX_CLOSE_CONFIRMATION_REQUIRED"
            )

        snapshot = self.snapshot_client.get_snapshot()

        if self._has_open_sell(
            snapshot=snapshot,
            symbol=request.symbol,
        ):
            raise WebullSandboxManualCloseError(
                "OPEN_SELL_ORDER_ALREADY_EXISTS"
            )

        now = self.clock()

        if now.tzinfo is None:
            raise WebullSandboxManualCloseError(
                "SANDBOX_CLOCK_MUST_BE_TIMEZONE_AWARE"
            )

        client_order_id = (
            self.client_order_id_factory().strip()
        )

        if not client_order_id:
            raise WebullSandboxManualCloseError(
                "CLIENT_ORDER_ID_REQUIRED"
            )

        try:
            intent = build_reduce_only_close_intent(
                client_order_id=client_order_id,
                positions=snapshot.positions,
                symbol=request.symbol,
                quantity=request.quantity,
                limit_price=request.limit_price,
                created_at=now,
            )

            return self.close_manager.submit(
                intent=intent,
                management_armed=True,
            )

        except Exception as error:
            raise WebullSandboxManualCloseError(
                "SANDBOX_CLOSE_SUBMISSION_FAILED:"
                f"{error}"
            ) from error


    def cancel(
        self,
        *,
        client_order_id: str,
        confirmation: str,
    ) -> WebullReduceOnlyCloseRecord:
        """
        Rescue-cancel an existing reduce-only sandbox close.

        Cancellation deliberately does not require either
        submission arm. It delegates to the close manager,
        which performs broker-state reconciliation and
        does not blindly retry ambiguous mutations.
        """

        key = client_order_id.strip()

        if not key:
            raise WebullSandboxManualCloseError(
                "CLIENT_ORDER_ID_REQUIRED"
            )

        if (
            confirmation.strip()
            != CLOSE_CANCEL_CONFIRMATION_PHRASE
        ):
            raise WebullSandboxManualCloseError(
                "SANDBOX_CLOSE_CANCEL_CONFIRMATION_REQUIRED"
            )

        try:
            return self.close_manager.cancel(
                client_order_id=key
            )

        except Exception as error:
            raise WebullSandboxManualCloseError(
                "SANDBOX_CLOSE_CANCEL_FAILED:"
                f"{error}"
            ) from error
