from __future__ import annotations

import random

from dataclasses import dataclass

from .webull_account_risk import (
    WebullAccountRiskGate,
    WebullExecutionRiskLimits,
    WebullExecutionRiskState,
)
from .webull_safety import (
    WebullAccountState,
    WebullOrderProposal,
)


@dataclass(frozen=True)
class WebullAccountRiskStressReport:
    seed: int
    scenarios: int
    allowed: int
    rejected: int

    stale_account_rejections: int
    stale_risk_rejections: int
    kill_switch_rejections: int
    daily_loss_rejections: int
    duplicate_symbol_order_rejections: int
    max_order_rejections: int
    max_position_rejections: int
    capital_rejections: int

    invariant_failures: int


def run_webull_account_risk_stress(
    *,
    scenarios: int = 10000,
    seed: int = 20260817,
) -> WebullAccountRiskStressReport:
    if (
        isinstance(scenarios, bool)
        or not isinstance(scenarios, int)
        or scenarios <= 0
    ):
        raise ValueError(
            "INVALID_ACCOUNT_RISK_STRESS_COUNT"
        )

    rng = random.Random(seed)

    counts = {
        "allowed": 0,
        "rejected": 0,
        "stale_account_rejections": 0,
        "stale_risk_rejections": 0,
        "kill_switch_rejections": 0,
        "daily_loss_rejections": 0,
        "duplicate_symbol_order_rejections": 0,
        "max_order_rejections": 0,
        "max_position_rejections": 0,
        "capital_rejections": 0,
        "invariant_failures": 0,
    }

    reason_to_counter = {
        "ACCOUNT_DATA_STALE_OR_UNKNOWN":
            "stale_account_rejections",
        "ACCOUNT_RISK_DATA_STALE_OR_UNKNOWN":
            "stale_risk_rejections",
        "TRADING_KILL_SWITCH_ACTIVE":
            "kill_switch_rejections",
        "DAILY_LOSS_LIMIT_REACHED":
            "daily_loss_rejections",
        "OPEN_ORDER_ALREADY_EXISTS_FOR_SYMBOL":
            "duplicate_symbol_order_rejections",
        "MAX_OPEN_ORDERS_EXCEEDED":
            "max_order_rejections",
        "MAX_OPEN_POSITIONS_EXCEEDED":
            "max_position_rejections",
        "INSUFFICIENT_SAFE_EXECUTION_CAPITAL":
            "capital_rejections",
    }

    universe = tuple(
        f"S{index:02d}"
        for index in range(20)
    )

    for _ in range(scenarios):
        max_positions = rng.randint(
            1,
            5,
        )

        max_orders = rng.randint(
            1,
            6,
        )

        max_daily_loss = round(
            rng.uniform(
                10.0,
                250.0,
            ),
            2,
        )

        position_count = rng.randint(
            0,
            6,
        )

        position_symbols = tuple(
            universe[:position_count]
        )

        order_count = rng.randint(
            0,
            7,
        )

        order_symbols = tuple(
            rng.choice(
                universe
            )
            for _ in range(order_count)
        )

        pending_buy_symbols = tuple(
            order_symbol
            for order_symbol
            in dict.fromkeys(
                order_symbols
            )
            if rng.random() < 0.60
        )

        symbol = rng.choice(
            universe
        )

        cash = round(
            rng.uniform(
                0.0,
                1000.0,
            ),
            2,
        )

        buying_power = (
            None
            if rng.random() < 0.20
            else round(
                rng.uniform(
                    0.0,
                    1200.0,
                ),
                2,
            )
        )

        quantity = rng.randint(
            1,
            20,
        )

        price = round(
            rng.uniform(
                1.0,
                50.0,
            ),
            2,
        )

        daily_pnl = round(
            rng.uniform(
                -300.0,
                300.0,
            ),
            2,
        )

        account_current = (
            rng.random() >= 0.05
        )

        risk_current = (
            rng.random() >= 0.05
        )

        kill_switch = (
            rng.random() < 0.05
        )

        account = WebullAccountState(
            account_type="CASH",
            available_cash=cash,
            position_exposure=0.0,
            open_buy_order_exposure=0.0,
            data_is_current=(
                account_current
            ),
            buying_power=buying_power,
        )

        proposal = WebullOrderProposal(
            symbol=symbol,
            side="BUY",
            quantity=quantity,
            limit_price=price,
            manually_approved=True,
        )

        risk_state = WebullExecutionRiskState(
            daily_realized_pnl=daily_pnl,
            open_position_symbols=(
                position_symbols
            ),
            open_order_symbols=(
                order_symbols
            ),
            kill_switch_active=(
                kill_switch
            ),
            pending_buy_symbols=(
                pending_buy_symbols
            ),
            position_exposures=tuple(
                (
                    position_symbol,
                    0.0,
                )
                for position_symbol
                in position_symbols
            ),
            pending_buy_exposures=tuple(
                (
                    pending_symbol,
                    0.0,
                )
                for pending_symbol
                in pending_buy_symbols
            ),
            data_is_current=(
                risk_current
            ),
        )

        limits = WebullExecutionRiskLimits(
            max_daily_loss=(
                max_daily_loss
            ),
            max_open_positions=(
                max_positions
            ),
            max_open_orders=(
                max_orders
            ),
            max_position_exposure=1000000.0,
        )

        result = (
            WebullAccountRiskGate
            .evaluate_new_buy(
                account=account,
                proposal=proposal,
                risk_state=risk_state,
                limits=limits,
            )
        )

        if result.allowed:
            counts["allowed"] += 1

            safe_capital = cash

            if buying_power is not None:
                safe_capital = min(
                    cash,
                    buying_power,
                )

            violations = [
                not account_current,
                not risk_current,
                kill_switch,
                daily_pnl
                <= -max_daily_loss,
                symbol in order_symbols,
                order_count + 1
                > max_orders,
                (
                    len(
                        set(position_symbols)
                        | set(
                            pending_buy_symbols
                        )
                        | {symbol}
                    )
                    > max_positions
                ),
                proposal.proposed_exposure
                > safe_capital,
            ]

            if any(violations):
                counts[
                    "invariant_failures"
                ] += 1

                raise AssertionError(
                    "ACCOUNT_RISK_ALLOWED_UNSAFE_STATE"
                )

        else:
            counts["rejected"] += 1

            counter = (
                reason_to_counter.get(
                    result.reason
                )
            )

            if counter is not None:
                counts[counter] += 1

    return WebullAccountRiskStressReport(
        seed=seed,
        scenarios=scenarios,
        **counts,
    )
