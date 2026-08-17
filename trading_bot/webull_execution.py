from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum


class WebullExecutionError(RuntimeError):
    pass


class WebullExecutionMode(StrEnum):
    DISABLED = "DISABLED"
    SANDBOX = "SANDBOX"
    LIVE_APPROVAL = "LIVE_APPROVAL"
    LIVE_AUTO = "LIVE_AUTO"

    @property
    def broker_submission_allowed(self) -> bool:
        # Only the Webull sandbox may receive broker API
        # submissions at this stage of development.
        return self is WebullExecutionMode.SANDBOX

    @property
    def is_live(self) -> bool:
        return self in {
            WebullExecutionMode.LIVE_APPROVAL,
            WebullExecutionMode.LIVE_AUTO,
        }


def parse_execution_mode(
    value: str | WebullExecutionMode,
) -> WebullExecutionMode:
    if isinstance(value, WebullExecutionMode):
        return value

    try:
        return WebullExecutionMode(
            str(value).strip().upper()
        )
    except ValueError as error:
        raise WebullExecutionError(
            "UNSUPPORTED_EXECUTION_MODE"
        ) from error


def require_safe_execution_mode(
    value: str | WebullExecutionMode,
) -> WebullExecutionMode:
    mode = parse_execution_mode(value)

    if mode.is_live:
        raise WebullExecutionError(
            "LIVE_EXECUTION_LOCKED"
        )

    return mode


def generate_client_order_id() -> str:
    """
    Generate a globally unique broker order identifier.

    Webull requires every client_order_id to be unique and
    recommends UUID-based identifiers.
    """
    return uuid.uuid4().hex


@dataclass(frozen=True)
class WebullTradeIntent:
    client_order_id: str
    strategy_name: str
    symbol: str
    side: str
    quantity: int
    limit_price: float
    created_at: datetime

    order_type: str = "LIMIT"
    time_in_force: str = "DAY"
    support_trading_session: str = "CORE"

    def __post_init__(self) -> None:
        client_order_id = (
            self.client_order_id.strip()
        )

        strategy_name = (
            self.strategy_name.strip()
        )

        symbol = self.symbol.strip().upper()
        side = self.side.strip().upper()
        order_type = (
            self.order_type.strip().upper()
        )
        time_in_force = (
            self.time_in_force.strip().upper()
        )
        session = (
            self.support_trading_session
            .strip()
            .upper()
        )

        if not client_order_id:
            raise WebullExecutionError(
                "CLIENT_ORDER_ID_REQUIRED"
            )

        if not strategy_name:
            raise WebullExecutionError(
                "STRATEGY_NAME_REQUIRED"
            )

        if not symbol:
            raise WebullExecutionError(
                "SYMBOL_REQUIRED"
            )

        # First execution stage is intentionally long-only.
        if side != "BUY":
            raise WebullExecutionError(
                "ONLY_BUY_INTENTS_SUPPORTED"
            )

        if self.quantity <= 0:
            raise WebullExecutionError(
                "INVALID_QUANTITY"
            )

        if self.limit_price <= 0:
            raise WebullExecutionError(
                "INVALID_LIMIT_PRICE"
            )

        if order_type != "LIMIT":
            raise WebullExecutionError(
                "ONLY_LIMIT_ORDERS_SUPPORTED"
            )

        if time_in_force != "DAY":
            raise WebullExecutionError(
                "ONLY_DAY_ORDERS_SUPPORTED"
            )

        if session != "CORE":
            raise WebullExecutionError(
                "ONLY_CORE_SESSION_SUPPORTED"
            )

        if self.created_at.tzinfo is None:
            raise WebullExecutionError(
                "INTENT_TIMESTAMP_MUST_BE_TIMEZONE_AWARE"
            )

        object.__setattr__(
            self,
            "client_order_id",
            client_order_id,
        )
        object.__setattr__(
            self,
            "strategy_name",
            strategy_name,
        )
        object.__setattr__(
            self,
            "symbol",
            symbol,
        )
        object.__setattr__(
            self,
            "side",
            side,
        )
        object.__setattr__(
            self,
            "limit_price",
            round(
                float(self.limit_price),
                4,
            ),
        )
        object.__setattr__(
            self,
            "created_at",
            self.created_at.astimezone(UTC),
        )
        object.__setattr__(
            self,
            "order_type",
            order_type,
        )
        object.__setattr__(
            self,
            "time_in_force",
            time_in_force,
        )
        object.__setattr__(
            self,
            "support_trading_session",
            session,
        )

    @property
    def proposed_exposure(self) -> float:
        return round(
            self.quantity * self.limit_price,
            2,
        )

    def broker_payload(self) -> dict[str, str]:
        """
        Return the exact simple-stock order shape expected by
        Webull's unified stock order interface.
        """
        return {
            "combo_type": "NORMAL",
            "client_order_id": (
                self.client_order_id
            ),
            "symbol": self.symbol,
            "instrument_type": "EQUITY",
            "market": "US",
            "order_type": self.order_type,
            "limit_price": (
                f"{self.limit_price:.4f}"
            ),
            "quantity": str(
                self.quantity
            ),
            "support_trading_session": (
                self.support_trading_session
            ),
            "side": self.side,
            "time_in_force": (
                self.time_in_force
            ),
            "entrust_type": "QTY",
        }
