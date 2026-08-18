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
    WEBULL_EXECUTION_MAX_POSITION_EXPOSURE_DOLLARS,
)
from .webull_account_parser import (
    ParsedWebullOpenOrder,
    ParsedWebullPosition,
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
    max_position_exposure: float

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

        try:
            max_position_exposure = float(
                self.max_position_exposure
            )
        except (TypeError, ValueError) as error:
            raise WebullAccountRiskError(
                "INVALID_MAX_POSITION_EXPOSURE"
            ) from error

        if (
            not math.isfinite(
                max_position_exposure
            )
            or max_position_exposure <= 0
        ):
            raise WebullAccountRiskError(
                "INVALID_MAX_POSITION_EXPOSURE"
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

        object.__setattr__(
            self,
            "max_position_exposure",
            round(
                max_position_exposure,
                2,
            ),
        )


@dataclass(frozen=True)
class WebullExecutionRiskState:
    """
    Read-only account-wide execution state.

    Position symbols are unique held long positions.
    Open-order symbols contain one item per active order, so the
    tuple length is the active order count.

    pending_buy_symbols contains the unique symbols represented
    by active BUY entry orders. Each pending BUY reserves a
    future position slot so concurrent entries cannot exceed the
    configured position maximum after they fill.

    The kill switch and daily P&L are supplied explicitly rather
    than imported from paper-trading code.
    """

    daily_realized_pnl: float
    open_position_symbols: tuple[str, ...]
    open_order_symbols: tuple[str, ...]
    kill_switch_active: bool
    pending_buy_symbols: tuple[str, ...] = ()
    position_exposures: tuple[
        tuple[str, float],
        ...
    ] = ()
    pending_buy_exposures: tuple[
        tuple[str, float],
        ...
    ] = ()
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

        pending_buys = tuple(
            str(symbol)
            .strip()
            .upper()
            for symbol
            in self.pending_buy_symbols
        )

        def normalize_exposures(
            entries,
            *,
            invalid_reason,
            duplicate_reason,
        ):
            normalized = []

            for raw_symbol, raw_exposure in entries:
                symbol = (
                    str(raw_symbol)
                    .strip()
                    .upper()
                )

                try:
                    exposure = float(
                        raw_exposure
                    )
                except (
                    TypeError,
                    ValueError,
                ) as error:
                    raise WebullAccountRiskError(
                        invalid_reason
                    ) from error

                if (
                    not symbol
                    or not math.isfinite(
                        exposure
                    )
                    or exposure < 0
                ):
                    raise WebullAccountRiskError(
                        invalid_reason
                    )

                normalized.append(
                    (
                        symbol,
                        round(
                            exposure,
                            2,
                        ),
                    )
                )

            symbols = [
                symbol
                for symbol, _
                in normalized
            ]

            if len(
                set(symbols)
            ) != len(symbols):
                raise WebullAccountRiskError(
                    duplicate_reason
                )

            return tuple(
                normalized
            )

        position_exposures = (
            normalize_exposures(
                self.position_exposures,
                invalid_reason=(
                    "INVALID_POSITION_EXPOSURE"
                ),
                duplicate_reason=(
                    "DUPLICATE_POSITION_EXPOSURE_SYMBOL"
                ),
            )
        )

        pending_buy_exposures = (
            normalize_exposures(
                self.pending_buy_exposures,
                invalid_reason=(
                    "INVALID_PENDING_BUY_EXPOSURE"
                ),
                duplicate_reason=(
                    "DUPLICATE_PENDING_BUY_EXPOSURE_SYMBOL"
                ),
            )
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

        if any(
            not symbol
            for symbol in pending_buys
        ):
            raise WebullAccountRiskError(
                "INVALID_PENDING_BUY_SYMBOL"
            )

        if (
            len(set(positions))
            != len(positions)
        ):
            raise WebullAccountRiskError(
                "DUPLICATE_POSITION_SYMBOL"
            )

        if (
            len(set(pending_buys))
            != len(pending_buys)
        ):
            raise WebullAccountRiskError(
                "DUPLICATE_PENDING_BUY_SYMBOL"
            )

        if not set(
            pending_buys
        ).issubset(
            set(orders)
        ):
            raise WebullAccountRiskError(
                "PENDING_BUY_NOT_OPEN_ORDER"
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

        object.__setattr__(
            self,
            "pending_buy_symbols",
            pending_buys,
        )

        object.__setattr__(
            self,
            "position_exposures",
            position_exposures,
        )

        object.__setattr__(
            self,
            "pending_buy_exposures",
            pending_buy_exposures,
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

    current_symbol_exposure: float
    projected_symbol_exposure: float
    max_position_exposure: float


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
        max_position_exposure=(
            WEBULL_EXECUTION_MAX_POSITION_EXPOSURE_DOLLARS
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

        reserved_position_symbols = (
            set(
                risk_state.open_position_symbols
            )
            | set(
                risk_state.pending_buy_symbols
            )
        )

        projected_position_symbols = (
            reserved_position_symbols
            | {symbol}
        )

        projected_positions = len(
            projected_position_symbols
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

        position_exposure_map = dict(
            risk_state.position_exposures
        )

        pending_buy_exposure_map = dict(
            risk_state.pending_buy_exposures
        )

        position_exposure_known = (
            symbol
            not in risk_state.open_position_symbols
            or symbol
            in position_exposure_map
        )

        pending_buy_exposure_known = (
            symbol
            not in risk_state.pending_buy_symbols
            or symbol
            in pending_buy_exposure_map
        )

        current_symbol_exposure = round(
            position_exposure_map.get(
                symbol,
                0.0,
            )
            + pending_buy_exposure_map.get(
                symbol,
                0.0,
            ),
            2,
        )

        projected_symbol_exposure = round(
            current_symbol_exposure
            + proposed_exposure,
            2,
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
                current_symbol_exposure=(
                    current_symbol_exposure
                ),
                projected_symbol_exposure=(
                    projected_symbol_exposure
                ),
                max_position_exposure=(
                    limits.max_position_exposure
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

        if not position_exposure_known:
            return decision(
                allowed=False,
                reason=(
                    "POSITION_EXPOSURE_DATA_MISSING"
                ),
            )

        if not pending_buy_exposure_known:
            return decision(
                allowed=False,
                reason=(
                    "PENDING_BUY_EXPOSURE_DATA_MISSING"
                ),
            )

        if (
            projected_symbol_exposure
            > limits.max_position_exposure
        ):
            return decision(
                allowed=False,
                reason=(
                    "MAX_POSITION_EXPOSURE_EXCEEDED"
                ),
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


def build_execution_risk_state(
    *,
    positions: tuple[
        ParsedWebullPosition,
        ...
    ] | list[
        ParsedWebullPosition
    ],
    open_orders: tuple[
        ParsedWebullOpenOrder,
        ...
    ] | list[
        ParsedWebullOpenOrder
    ],
    daily_realized_pnl: float,
    kill_switch_active: bool,
    data_is_current: bool = True,
) -> WebullExecutionRiskState:
    """
    Build authoritative execution-risk state from the same
    strictly parsed Webull positions/open orders used by the
    account snapshot.

    BUY order exposure is reserved at remaining quantity times
    limit price. SELL orders reserve no new long exposure.
    """
    position_totals = {}

    for position in positions:
        symbol = (
            position.symbol
            .strip()
            .upper()
        )

        position_totals[
            symbol
        ] = round(
            position_totals.get(
                symbol,
                0.0,
            )
            + float(
                position.market_value
            ),
            2,
        )

    open_order_symbols = tuple(
        order.symbol
        .strip()
        .upper()
        for order
        in open_orders
    )

    pending_buy_totals = {}

    for order in open_orders:
        if (
            order.side
            .strip()
            .upper()
            != "BUY"
        ):
            continue

        symbol = (
            order.symbol
            .strip()
            .upper()
        )

        pending_buy_totals[
            symbol
        ] = round(
            pending_buy_totals.get(
                symbol,
                0.0,
            )
            + float(
                order.reserved_exposure
            ),
            2,
        )

    return WebullExecutionRiskState(
        daily_realized_pnl=(
            daily_realized_pnl
        ),
        open_position_symbols=tuple(
            sorted(
                position_totals
            )
        ),
        open_order_symbols=(
            open_order_symbols
        ),
        pending_buy_symbols=tuple(
            sorted(
                pending_buy_totals
            )
        ),
        position_exposures=tuple(
            sorted(
                position_totals.items()
            )
        ),
        pending_buy_exposures=tuple(
            sorted(
                pending_buy_totals.items()
            )
        ),
        kill_switch_active=(
            kill_switch_active
        ),
        data_is_current=(
            data_is_current
        ),
    )
