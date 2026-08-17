from __future__ import annotations

import random

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from .historical_execution_simulator import (
    HistoricalBar,
    HistoricalExecutionError,
    HistoricalExecutionSimulator,
)
from .webull_execution import (
    WebullTradeIntent,
)
from .webull_reduce_only_close import (
    WebullReduceOnlyCloseIntent,
)


class HistoricalExecutionStressError(
    RuntimeError
):
    pass


@dataclass(frozen=True)
class HistoricalExecutionStressReport:
    seed: int
    scenarios: int

    cancelled_before_fill: int

    ambiguous_buy_accepted: int
    ambiguous_buy_rejected: int

    ambiguous_close_accepted: int
    ambiguous_close_rejected: int

    partial_buy_fills: int
    partial_close_fills: int

    restart_round_trips: int

    duplicate_retry_rejections: int
    stale_close_rejections: int

    final_flat_scenarios: int
    invariant_failures: int


def _expect_error(
    callable_object,
    *,
    expected: str,
) -> None:
    try:
        callable_object()

    except HistoricalExecutionError as error:
        if str(error) != expected:
            raise HistoricalExecutionStressError(
                "UNEXPECTED_STRESS_ERROR:"
                f"expected={expected}:"
                f"observed={error}"
            ) from error

        return

    raise HistoricalExecutionStressError(
        "EXPECTED_STRESS_ERROR_NOT_RAISED:"
        f"{expected}"
    )


def _bar(
    *,
    symbol: str,
    timestamp: datetime,
    price: float,
    should_fill: bool,
    side: str,
) -> HistoricalBar:
    price = float(price)

    if should_fill:
        low = max(
            0.0001,
            price - 0.05,
        )

        high = (
            price + 0.05
        )

    elif side == "BUY":
        low = (
            price + 0.05
        )

        high = (
            price + 0.15
        )

    else:
        low = max(
            0.0001,
            price - 0.15,
        )

        high = max(
            low + 0.01,
            price - 0.05,
        )

    midpoint = (
        low
        + (
            high - low
        ) / 2.0
    )

    return HistoricalBar(
        symbol=symbol,
        timestamp=timestamp,
        open=midpoint,
        high=high,
        low=low,
        close=midpoint,
        volume=100000.0,
    )


def run_historical_execution_stress(
    *,
    scenarios: int = 5000,
    seed: int = 20260817,
) -> HistoricalExecutionStressReport:
    if (
        isinstance(scenarios, bool)
        or not isinstance(
            scenarios,
            int,
        )
        or scenarios <= 0
    ):
        raise HistoricalExecutionStressError(
            "INVALID_STRESS_SCENARIO_COUNT"
        )

    rng = random.Random(
        seed
    )

    cancelled_before_fill = 0

    ambiguous_buy_accepted = 0
    ambiguous_buy_rejected = 0

    ambiguous_close_accepted = 0
    ambiguous_close_rejected = 0

    partial_buy_fills = 0
    partial_close_fills = 0

    restart_round_trips = 0

    duplicate_retry_rejections = 0
    stale_close_rejections = 0

    final_flat_scenarios = 0
    invariant_failures = 0

    base_time = datetime(
        2026,
        3,
        2,
        14,
        45,
        tzinfo=UTC,
    )

    for index in range(
        scenarios
    ):
        starting_cash = 100000.0

        simulator = (
            HistoricalExecutionSimulator(
                starting_cash=(
                    starting_cash
                )
            )
        )

        symbol = (
            f"T{index % 97:02d}"
        )

        quantity = rng.randint(
            1,
            20,
        )

        entry_price = round(
            rng.uniform(
                2.0,
                250.0,
            ),
            4,
        )

        buy_id = (
            f"stress-{seed}-"
            f"{index}-buy"
        )

        created_at = (
            base_time
            + timedelta(
                seconds=index
            )
        )

        buy_intent = (
            WebullTradeIntent(
                client_order_id=buy_id,
                strategy_name=(
                    "STRESS_TEST"
                ),
                symbol=symbol,
                side="BUY",
                quantity=quantity,
                limit_price=(
                    entry_price
                ),
                created_at=created_at,
            )
        )

        scenario_type = (
            rng.randrange(10)
        )

        if scenario_type == 0:
            simulator.place_buy(
                buy_intent
            )

            simulator.process_bar(
                _bar(
                    symbol=symbol,
                    timestamp=(
                        created_at
                        + timedelta(
                            minutes=1
                        )
                    ),
                    price=entry_price,
                    should_fill=False,
                    side="BUY",
                )
            )

            simulator.cancel(
                buy_id
            )

            cancelled_before_fill += 1

            if (
                simulator.available_cash
                != starting_cash
            ):
                raise (
                    HistoricalExecutionStressError(
                        "CANCEL_DID_NOT_RELEASE_CASH"
                    )
                )

            simulator.assert_invariants()

            if simulator.holdings:
                raise (
                    HistoricalExecutionStressError(
                        "CANCEL_CREATED_POSITION"
                    )
                )

            if any(
                order.active
                for order
                in simulator.orders.values()
            ):
                raise (
                    HistoricalExecutionStressError(
                        "CANCEL_LEFT_ACTIVE_ORDER"
                    )
                )

            final_flat_scenarios += 1

            continue

        ambiguous_buy = (
            rng.random()
            < 0.25
        )

        if ambiguous_buy:
            _expect_error(
                lambda: (
                    simulator.place_buy(
                        buy_intent,
                        ambiguous_after_accept=True,
                    )
                ),
                expected=(
                    "SUBMISSION_UNKNOWN"
                ),
            )

            _expect_error(
                lambda: (
                    simulator.place_buy(
                        buy_intent
                    )
                ),
                expected=(
                    "DUPLICATE_CLIENT_ORDER_ID"
                ),
            )

            duplicate_retry_rejections += 1

            if rng.random() < 0.50:
                simulator = (
                    HistoricalExecutionSimulator
                    .from_state(
                        simulator.state_dict()
                    )
                )

                restart_round_trips += 1

            accepted = (
                rng.random()
                < 0.75
            )

            simulator.resolve_submission(
                buy_id,
                accepted=accepted,
            )

            if accepted:
                ambiguous_buy_accepted += 1

            else:
                ambiguous_buy_rejected += 1

                buy_id = (
                    f"stress-{seed}-"
                    f"{index}-buy-retry"
                )

                buy_intent = (
                    WebullTradeIntent(
                        client_order_id=buy_id,
                        strategy_name=(
                            "STRESS_TEST"
                        ),
                        symbol=symbol,
                        side="BUY",
                        quantity=quantity,
                        limit_price=(
                            entry_price
                        ),
                        created_at=(
                            created_at
                            + timedelta(
                                seconds=1
                            )
                        ),
                    )
                )

                simulator.place_buy(
                    buy_intent
                )

        else:
            simulator.place_buy(
                buy_intent
            )

        if (
            quantity > 1
            and rng.random()
            < 0.55
        ):
            first_fill = (
                rng.randint(
                    1,
                    quantity - 1,
                )
            )

            simulator.process_bar(
                _bar(
                    symbol=symbol,
                    timestamp=(
                        created_at
                        + timedelta(
                            minutes=1
                        )
                    ),
                    price=entry_price,
                    should_fill=True,
                    side="BUY",
                ),
                max_fill_quantity=(
                    first_fill
                ),
            )

            partial_buy_fills += 1

            if rng.random() < 0.35:
                simulator = (
                    HistoricalExecutionSimulator
                    .from_state(
                        simulator.state_dict()
                    )
                )

                restart_round_trips += 1

        simulator.process_bar(
            _bar(
                symbol=symbol,
                timestamp=(
                    created_at
                    + timedelta(
                        minutes=2
                    )
                ),
                price=entry_price,
                should_fill=True,
                side="BUY",
            )
        )

        held = (
            simulator.held_quantity(
                symbol
            )
        )

        if abs(
            held - quantity
        ) > 0.00001:
            raise HistoricalExecutionStressError(
                "BUY_POSITION_MISMATCH"
            )

        if rng.random() < 0.20:
            stale_close_id = (
                f"stress-{seed}-"
                f"{index}-stale-close"
            )

            stale_intent = (
                WebullReduceOnlyCloseIntent(
                    client_order_id=(
                        stale_close_id
                    ),
                    symbol=symbol,
                    quantity=quantity,
                    limit_price=(
                        entry_price
                    ),
                    confirmed_position_quantity=(
                        held
                    ),
                    created_at=(
                        created_at
                        + timedelta(
                            minutes=3
                        )
                    ),
                )
            )

            simulator.holdings[
                symbol
            ] = (
                held + 1.0
            )

            _expect_error(
                lambda: (
                    simulator
                    .place_reduce_only_close(
                        stale_intent
                    )
                ),
                expected=(
                    "CONFIRMED_POSITION_CHANGED"
                ),
            )

            stale_close_rejections += 1

            simulator.holdings[
                symbol
            ] = held

            simulator.assert_invariants()

        close_price = round(
            max(
                0.01,
                entry_price
                + rng.uniform(
                    -1.5,
                    1.5,
                ),
            ),
            4,
        )

        close_id = (
            f"stress-{seed}-"
            f"{index}-close"
        )

        close_created_at = (
            created_at
            + timedelta(
                minutes=3
            )
        )

        close_intent = (
            WebullReduceOnlyCloseIntent(
                client_order_id=(
                    close_id
                ),
                symbol=symbol,
                quantity=quantity,
                limit_price=(
                    close_price
                ),
                confirmed_position_quantity=(
                    simulator
                    .held_quantity(
                        symbol
                    )
                ),
                created_at=(
                    close_created_at
                ),
            )
        )

        ambiguous_close = (
            rng.random()
            < 0.25
        )

        if ambiguous_close:
            _expect_error(
                lambda: (
                    simulator
                    .place_reduce_only_close(
                        close_intent,
                        ambiguous_after_accept=True,
                    )
                ),
                expected=(
                    "SUBMISSION_UNKNOWN"
                ),
            )

            _expect_error(
                lambda: (
                    simulator
                    .place_reduce_only_close(
                        close_intent
                    )
                ),
                expected=(
                    "DUPLICATE_CLIENT_ORDER_ID"
                ),
            )

            duplicate_retry_rejections += 1

            if rng.random() < 0.50:
                simulator = (
                    HistoricalExecutionSimulator
                    .from_state(
                        simulator.state_dict()
                    )
                )

                restart_round_trips += 1

            accepted = (
                rng.random()
                < 0.75
            )

            simulator.resolve_submission(
                close_id,
                accepted=accepted,
            )

            if accepted:
                ambiguous_close_accepted += 1

            else:
                ambiguous_close_rejected += 1

                close_id = (
                    f"stress-{seed}-"
                    f"{index}-close-retry"
                )

                close_intent = (
                    WebullReduceOnlyCloseIntent(
                        client_order_id=(
                            close_id
                        ),
                        symbol=symbol,
                        quantity=quantity,
                        limit_price=(
                            close_price
                        ),
                        confirmed_position_quantity=(
                            simulator
                            .held_quantity(
                                symbol
                            )
                        ),
                        created_at=(
                            close_created_at
                            + timedelta(
                                seconds=1
                            )
                        ),
                    )
                )

                simulator.place_reduce_only_close(
                    close_intent
                )

        else:
            simulator.place_reduce_only_close(
                close_intent
            )

        if (
            quantity > 1
            and rng.random()
            < 0.55
        ):
            first_close_fill = (
                rng.randint(
                    1,
                    quantity - 1,
                )
            )

            simulator.process_bar(
                _bar(
                    symbol=symbol,
                    timestamp=(
                        close_created_at
                        + timedelta(
                            minutes=1
                        )
                    ),
                    price=close_price,
                    should_fill=True,
                    side="SELL",
                ),
                max_fill_quantity=(
                    first_close_fill
                ),
            )

            partial_close_fills += 1

            if rng.random() < 0.35:
                simulator = (
                    HistoricalExecutionSimulator
                    .from_state(
                        simulator.state_dict()
                    )
                )

                restart_round_trips += 1

        simulator.process_bar(
            _bar(
                symbol=symbol,
                timestamp=(
                    close_created_at
                    + timedelta(
                        minutes=2
                    )
                ),
                price=close_price,
                should_fill=True,
                side="SELL",
            )
        )

        try:
            simulator.assert_invariants()

        except HistoricalExecutionError:
            invariant_failures += 1
            raise

        if (
            simulator.held_quantity(
                symbol
            )
            > 0.00001
        ):
            raise HistoricalExecutionStressError(
                "STRESS_POSITION_NOT_FLAT"
            )

        if any(
            order.active
            for order
            in simulator.orders.values()
        ):
            raise HistoricalExecutionStressError(
                "STRESS_ACTIVE_ORDER_AT_END"
            )

        expected_cash = (
            starting_cash
            + (
                float(quantity)
                * (
                    close_price
                    - entry_price
                )
            )
        )

        if abs(
            simulator.cash
            - expected_cash
        ) > 0.0001:
            raise HistoricalExecutionStressError(
                "STRESS_CASH_MISMATCH:"
                f"expected={expected_cash}:"
                f"observed={simulator.cash}"
            )

        final_flat_scenarios += 1

    return HistoricalExecutionStressReport(
        seed=seed,
        scenarios=scenarios,

        cancelled_before_fill=(
            cancelled_before_fill
        ),

        ambiguous_buy_accepted=(
            ambiguous_buy_accepted
        ),

        ambiguous_buy_rejected=(
            ambiguous_buy_rejected
        ),

        ambiguous_close_accepted=(
            ambiguous_close_accepted
        ),

        ambiguous_close_rejected=(
            ambiguous_close_rejected
        ),

        partial_buy_fills=(
            partial_buy_fills
        ),

        partial_close_fills=(
            partial_close_fills
        ),

        restart_round_trips=(
            restart_round_trips
        ),

        duplicate_retry_rejections=(
            duplicate_retry_rejections
        ),

        stale_close_rejections=(
            stale_close_rejections
        ),

        final_flat_scenarios=(
            final_flat_scenarios
        ),

        invariant_failures=(
            invariant_failures
        ),
    )
