from __future__ import annotations

import math

from dataclasses import dataclass

from .webull_safety import (
    WebullAccountState,
    WebullOrderProposal,
)
from .config import (
    WEBULL_EXECUTION_MAX_DAILY_LOSS_DOLLARS,
    WEBULL_EXECUTION_MAX_OPEN_ORDERS,
    WEBULL_EXECUTION_MAX_OPEN_POSITIONS,
)


class WebullAccountRiskError(RuntimeError):
    pass


@dataclass(frozen=True)
class WebullExecutionRiskLimits:
    """
    Account-wide limits for future automatic execution.

    No production defaults are defined here deliberately.
    Callers must provide explicit limits.
    """

    max_daily_loss: float
    max_open_positions: int
    max_open_orders: int

    def __post_init__(self) -> None:
        try:
            daily_loss = float(
                self.max_daily_loss
            )
        except (TypeError, ValueError) as error:
            raise WebullAccountRiskError(
                "INVALID_MAX_DAILY_LOSS"
            ) from error

        if (
            not math.isfinite(daily_loss)
            or daily_loss <= 0
        ):
            raise WebullAccountRiskError(
                "INVALID_MAX_DAILY_LOSS"
            )

        for value, reason in (
            (
                self.max_open_positions,
                "INVALID_MAX_OPEN_POSITIONS",
            ),
            (
                self.max_open_orders,
                "INVALID_MAX_OPEN_ORDERS",
            ),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value <= 0
            ):
                raise WebullAccountRiskError(
                    reason
                )

        object.__setattr__(
            self,
            "max_daily_loss",
            round(daily_loss, 2),
        )


@dataclass(frozen=True)
class WebullExecutionRiskState:
    """
    Read-only account-wide execution state.

    Position symbols are unique held long positions.
    Open-order symbols contain one item per active order, so the
    tuple length is the active order count.

    The kill switch and daily P&L are supplied explicitly rather
    than imported from paper-trading code.
    """

    daily_realized_pnl: float
    open_position_symbols: tuple[str, ...]
    open_order_symbols: tuple[str, ...]
    kill_switch_active: bool
    data_is_current: bool = True

    def __post_init__(self) -> None:
        try:
            daily_pnl = float(
                self.daily_realized_pnl
            )
        except (TypeError, ValueError) as error:
            raise WebullAccountRiskError(
                "INVALID_DAILY_REALIZED_PNL"
            ) from error

        if not math.isfinite(
            daily_pnl
        ):
            raise WebullAccountRiskError(
                "INVALID_DAILY_REALIZED_PNL"
            )

        positions = tuple(
            str(symbol)
            .strip()
            .upper()
            for symbol
            in self.open_position_symbols
        )

        orders = tuple(
            str(symbol)
            .strip()
            .upper()
            for symbol
            in self.open_order_symbols
        )

        if any(
            not symbol
            for symbol in positions
        ):
            raise WebullAccountRiskError(
                "INVALID_POSITION_SYMBOL"
            )

        if any(
            not symbol
            for symbol in orders
        ):
            raise WebullAccountRiskError(
                "INVALID_OPEN_ORDER_SYMBOL"
            )

        if (
            len(set(positions))
            != len(positions)
        ):
            raise WebullAccountRiskError(
                "DUPLICATE_POSITION_SYMBOL"
            )

        object.__setattr__(
            self,
            "daily_realized_pnl",
            round(daily_pnl, 6),
        )

        object.__setattr__(
            self,
            "open_position_symbols",
            positions,
        )

        object.__setattr__(
            self,
            "open_order_symbols",
            orders,
        )


@dataclass(frozen=True)
class WebullAccountRiskDecision:
    allowed: bool
    reason: str

    daily_realized_pnl: float
    max_daily_loss: float

    current_open_positions: int
    projected_open_positions: int
    max_open_positions: int

    current_open_orders: int
    projected_open_orders: int
    max_open_orders: int

    safe_execution_capital: float
    proposed_exposure: float


def configured_execution_risk_limits(
) -> WebullExecutionRiskLimits:
    return WebullExecutionRiskLimits(
        max_daily_loss=(
            WEBULL_EXECUTION_MAX_DAILY_LOSS_DOLLARS
        ),
        max_open_positions=(
            WEBULL_EXECUTION_MAX_OPEN_POSITIONS
        ),
        max_open_orders=(
            WEBULL_EXECUTION_MAX_OPEN_ORDERS
        ),
    )


class WebullAccountRiskGate:
    """
    Pure account-wide risk overlay for a NEW long BUY.

    This does not submit, replace, cancel, or close an order.
    It is intentionally not wired into execution yet.
    """

    @staticmethod
    def evaluate_new_buy(
        *,
        account: WebullAccountState,
        proposal: WebullOrderProposal,
        risk_state: WebullExecutionRiskState,
        limits: WebullExecutionRiskLimits,
    ) -> WebullAccountRiskDecision:
        symbol = (
            proposal.symbol
            .strip()
            .upper()
        )

        if not symbol:
            raise WebullAccountRiskError(
                "PROPOSAL_SYMBOL_REQUIRED"
            )

        current_positions = len(
            risk_state.open_position_symbols
        )

        current_orders = len(
            risk_state.open_order_symbols
        )

        position_already_exists = (
            symbol
            in risk_state.open_position_symbols
        )

        projected_positions = (
            current_positions
            if position_already_exists
            else current_positions + 1
        )

        projected_orders = (
            current_orders + 1
        )

        available_cash = max(
            0.0,
            float(account.available_cash),
        )

        if account.buying_power is None:
            safe_capital = available_cash
        else:
            safe_capital = min(
                available_cash,
                max(
                    0.0,
                    float(account.buying_power),
                ),
            )

        proposed_exposure = float(
            proposal.proposed_exposure
        )

        def decision(
            *,
            allowed: bool,
            reason: str,
        ) -> WebullAccountRiskDecision:
            return WebullAccountRiskDecision(
                allowed=allowed,
                reason=reason,
                daily_realized_pnl=(
                    risk_state.daily_realized_pnl
                ),
                max_daily_loss=(
                    limits.max_daily_loss
                ),
                current_open_positions=(
                    current_positions
                ),
                projected_open_positions=(
                    projected_positions
                ),
                max_open_positions=(
                    limits.max_open_positions
                ),
                current_open_orders=(
                    current_orders
                ),
                projected_open_orders=(
                    projected_orders
                ),
                max_open_orders=(
                    limits.max_open_orders
                ),
                safe_execution_capital=round(
                    safe_capital,
                    2,
                ),
                proposed_exposure=round(
                    proposed_exposure,
                    2,
                ),
            )

        if not account.data_is_current:
            return decision(
                allowed=False,
                reason=(
                    "ACCOUNT_DATA_STALE_OR_UNKNOWN"
                ),
            )

        if not risk_state.data_is_current:
            return decision(
                allowed=False,
                reason=(
                    "ACCOUNT_RISK_DATA_STALE_OR_UNKNOWN"
                ),
            )

        if risk_state.kill_switch_active:
            return decision(
                allowed=False,
                reason="TRADING_KILL_SWITCH_ACTIVE",
            )

        if (
            risk_state.daily_realized_pnl
            <= -limits.max_daily_loss
        ):
            return decision(
                allowed=False,
                reason=(
                    "DAILY_LOSS_LIMIT_REACHED"
                ),
            )

        if (
            symbol
            in risk_state.open_order_symbols
        ):
            return decision(
                allowed=False,
                reason=(
                    "OPEN_ORDER_ALREADY_EXISTS_FOR_SYMBOL"
                ),
            )

        if (
            projected_orders
            > limits.max_open_orders
        ):
            return decision(
                allowed=False,
                reason=(
                    "MAX_OPEN_ORDERS_EXCEEDED"
                ),
            )

        if (
            projected_positions
            > limits.max_open_positions
        ):
            return decision(
                allowed=False,
                reason=(
                    "MAX_OPEN_POSITIONS_EXCEEDED"
                ),
            )

        if proposed_exposure <= 0:
            return decision(
                allowed=False,
                reason="INVALID_PROPOSED_EXPOSURE",
            )

        if (
            proposed_exposure
            > safe_capital
        ):
            return decision(
                allowed=False,
                reason=(
                    "INSUFFICIENT_SAFE_EXECUTION_CAPITAL"
                ),
            )

        return decision(
            allowed=True,
            reason="ACCOUNT_RISK_APPROVED",
        )
