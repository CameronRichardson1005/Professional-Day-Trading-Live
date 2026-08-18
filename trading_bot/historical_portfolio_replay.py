from __future__ import annotations

import heapq
import math

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from itertools import groupby
from typing import Iterable, Mapping, Sequence

from .historical_execution_replay import (
    HistoricalReplayError,
    _manipulation_entry_time,
    _normalize_bars,
    _parse_timestamp,
    replay_master_row_strategy,
)
from .historical_execution_simulator import (
    HistoricalBar,
    HistoricalExecutionSimulator,
)


class HistoricalPortfolioReplayError(
    RuntimeError
):
    pass


@dataclass(frozen=True)
class HistoricalPortfolioCandidate:
    date: str
    symbol: str
    strategy: str

    created_at: datetime
    status: str

    entry_price: float
    fill_time: datetime | None
    cancel_time: datetime | None

    exit_time: datetime | None
    exit_price: float | None
    per_share_pnl: float

    allocation_score: float = 0.0
    allocation_weight: float = 1.0

    @property
    def candidate_id(self) -> str:
        return (
            f"{self.date}|{self.symbol}|"
            f"{self.strategy}|"
            f"{self.created_at.isoformat()}"
        )


@dataclass(frozen=True)
class HistoricalPortfolioDayResult:
    date: str
    realized_pnl: float
    accepted_entries: int
    rejected_entries: int
    daily_loss_halt_rejections: int


@dataclass(frozen=True)
class HistoricalPortfolioReport:
    per_position_cap: float
    max_daily_loss: float
    max_open_positions: int
    max_open_orders: int
    operational_cap: float
    hard_cap: float

    candidates: int
    accepted_entries: int
    rejected_entries: int
    completed_positions: int
    accepted_unfilled_orders: int

    total_realized_pnl: float

    max_position_symbols_observed: int
    max_open_orders_observed: int
    max_exposure_observed: float

    rejection_counts: tuple[
        tuple[str, int],
        ...
    ]

    strategy_realized_pnl: tuple[
        tuple[str, float],
        ...
    ]

    days: tuple[
        HistoricalPortfolioDayResult,
        ...
    ]


@dataclass
class _AcceptedTrade:
    candidate: HistoricalPortfolioCandidate
    quantity: int
    reserved_exposure: float


def build_historical_portfolio_candidate(
    *,
    row: dict[str, object],
    minute_bars: list[dict],
    strategy: str,
) -> HistoricalPortfolioCandidate | None:
    key = strategy.strip().upper()

    if key not in {
        "MANIPULATION",
        "QUICK_FLIP",
    }:
        raise HistoricalPortfolioReplayError(
            "UNSUPPORTED_PORTFOLIO_STRATEGY"
        )

    signal_field = (
        "manipulation_signal"
        if key == "MANIPULATION"
        else "quick_flip_signal"
    )

    if (
        str(
            row.get(
                signal_field,
                "",
            )
        )
        .strip()
        .upper()
        != "INVEST"
    ):
        return None

    date_str = str(
        row.get(
            "date",
            "",
        )
    ).strip()

    symbol = (
        str(
            row.get(
                "symbol",
                "",
            )
        )
        .strip()
        .upper()
    )

    if not date_str or not symbol:
        raise HistoricalPortfolioReplayError(
            "PORTFOLIO_CANDIDATE_IDENTITY_REQUIRED"
        )

    normalized = _normalize_bars(
        symbol=symbol,
        minute_bars=minute_bars,
    )

    if not normalized:
        raise HistoricalPortfolioReplayError(
            "PORTFOLIO_MINUTE_BARS_REQUIRED"
        )

    if key == "MANIPULATION":
        created_at = (
            _manipulation_entry_time(
                date_str
            )
        )

    else:
        confirmation = (
            row.get(
                "quick_flip_confirmation_time"
            )
            or row.get(
                "quick_flip_reversal_time"
            )
        )

        if not confirmation:
            raise HistoricalPortfolioReplayError(
                "QUICK_FLIP_CONFIRMATION_REQUIRED"
            )

        created_at = _parse_timestamp(
            confirmation
        )

    isolated = HistoricalExecutionSimulator(
        starting_cash=1_000_000.0
    )

    result = replay_master_row_strategy(
        simulator=isolated,
        row=row,
        minute_bars=minute_bars,
        strategy=key,
        quantity=1,
    )

    isolated.assert_invariants()

    if result.status not in {
        "COMPLETED",
        "ENTRY_NOT_FILLED",
    }:
        raise HistoricalPortfolioReplayError(
            "UNEXPECTED_PORTFOLIO_CANDIDATE_STATUS:"
            + result.status
        )

    if result.entry_price is None:
        raise HistoricalPortfolioReplayError(
            "PORTFOLIO_ENTRY_PRICE_REQUIRED"
        )

    if result.status == "COMPLETED":
        if (
            result.entry_fill_time is None
            or result.exit_time is None
            or result.exit_price is None
        ):
            raise HistoricalPortfolioReplayError(
                "COMPLETED_PORTFOLIO_TIMES_REQUIRED"
            )

        cancel_time = None

    else:
        cancel_time = normalized[-1].timestamp

    return HistoricalPortfolioCandidate(
        date=date_str,
        symbol=symbol,
        strategy=key,
        created_at=created_at,
        status=result.status,
        entry_price=float(
            result.entry_price
        ),
        fill_time=(
            result.entry_fill_time
        ),
        cancel_time=cancel_time,
        exit_time=result.exit_time,
        exit_price=(
            None
            if result.exit_price is None
            else float(
                result.exit_price
            )
        ),
        per_share_pnl=float(
            result.realized_pnl
        ),
    )


def _mark_price(
    *,
    candidate: HistoricalPortfolioCandidate,
    timestamp: datetime,
    market_bars: Mapping[
        tuple[str, str],
        Sequence[HistoricalBar],
    ],
) -> float:
    bars = market_bars.get(
        (
            candidate.date,
            candidate.symbol,
        ),
        (),
    )

    for bar in reversed(
        bars
    ):
        if bar.timestamp <= timestamp:
            return float(
                bar.close
            )

    return float(
        candidate.entry_price
    )


def replay_historical_portfolio(
    *,
    candidates: Iterable[
        HistoricalPortfolioCandidate
    ],
    market_bars: Mapping[
        tuple[str, str],
        Sequence[HistoricalBar],
    ],
    per_position_cap: float,
    max_daily_loss: float = 25.0,
    max_open_positions: int = 2,
    max_open_orders: int = 2,
    operational_cap: float = 475.0,
    hard_cap: float = 500.0,
    strategy_priority: tuple[
        str,
        ...
    ] = (
        "MANIPULATION",
        "QUICK_FLIP",
    ),
) -> HistoricalPortfolioReport:
    numeric_limits = (
        per_position_cap,
        max_daily_loss,
        operational_cap,
        hard_cap,
    )

    if not all(
        math.isfinite(
            float(value)
        )
        and float(value) > 0
        for value in numeric_limits
    ):
        raise HistoricalPortfolioReplayError(
            "INVALID_PORTFOLIO_NUMERIC_LIMIT"
        )

    if (
        isinstance(
            max_open_positions,
            bool,
        )
        or not isinstance(
            max_open_positions,
            int,
        )
        or max_open_positions <= 0
    ):
        raise HistoricalPortfolioReplayError(
            "INVALID_PORTFOLIO_POSITION_LIMIT"
        )

    if (
        isinstance(
            max_open_orders,
            bool,
        )
        or not isinstance(
            max_open_orders,
            int,
        )
        or max_open_orders <= 0
    ):
        raise HistoricalPortfolioReplayError(
            "INVALID_PORTFOLIO_ORDER_LIMIT"
        )

    if operational_cap > hard_cap:
        raise HistoricalPortfolioReplayError(
            "PORTFOLIO_OPERATIONAL_CAP_ABOVE_HARD_CAP"
        )

    priority = {
        strategy.strip().upper(): index
        for index, strategy
        in enumerate(
            strategy_priority
        )
    }

    items = list(
        candidates
    )

    for candidate in items:
        if (
            candidate.created_at.tzinfo
            is None
        ):
            raise HistoricalPortfolioReplayError(
                "PORTFOLIO_TIME_MUST_BE_AWARE"
            )

        if candidate.strategy not in {
            "MANIPULATION",
            "QUICK_FLIP",
        }:
            raise HistoricalPortfolioReplayError(
                "INVALID_PORTFOLIO_CANDIDATE_STRATEGY"
            )

        if not math.isfinite(
            float(
                candidate.allocation_score
            )
        ):
            raise HistoricalPortfolioReplayError(
                "INVALID_PORTFOLIO_ALLOCATION_SCORE"
            )

        if (
            not math.isfinite(
                float(
                    candidate.allocation_weight
                )
            )
            or not (
                0.0
                < float(
                    candidate.allocation_weight
                )
                <= 1.0
            )
        ):
            raise HistoricalPortfolioReplayError(
                "INVALID_PORTFOLIO_ALLOCATION_WEIGHT"
            )

        if (
            candidate.status
            == "COMPLETED"
            and (
                candidate.fill_time is None
                or candidate.exit_time is None
            )
        ):
            raise HistoricalPortfolioReplayError(
                "COMPLETED_PORTFOLIO_EVENT_TIMES_REQUIRED"
            )

        if (
            candidate.status
            == "ENTRY_NOT_FILLED"
            and candidate.cancel_time is None
        ):
            raise HistoricalPortfolioReplayError(
                "UNFILLED_PORTFOLIO_CANCEL_REQUIRED"
            )

    items.sort(
        key=lambda item: (
            item.created_at,
            priority.get(
                item.strategy,
                len(priority),
            ),
            -float(
                item.allocation_score
            ),
            item.symbol,
            item.strategy,
        )
    )

    pending: dict[
        str,
        _AcceptedTrade,
    ] = {}

    positions: dict[
        str,
        _AcceptedTrade,
    ] = {}

    events: list[
        tuple[
            datetime,
            int,
            int,
            str,
            str,
        ]
    ] = []

    event_counter = 0

    daily_realized = defaultdict(
        float
    )

    accepted_by_day = Counter()
    rejected_by_day = Counter()
    halt_by_day = Counter()

    rejection_counts = Counter()
    strategy_pnl = defaultdict(float)

    accepted_entries = 0
    completed_positions = 0
    accepted_unfilled = 0

    max_position_symbols = 0
    max_orders = 0
    max_exposure = 0.0

    def position_symbols() -> set[str]:
        return {
            trade.candidate.symbol
            for trade
            in positions.values()
        }

    def pending_symbols() -> set[str]:
        return {
            trade.candidate.symbol
            for trade
            in pending.values()
        }

    def position_exposure(
        *,
        timestamp: datetime,
        symbol: str | None = None,
    ) -> float:
        total = 0.0

        for trade in positions.values():
            if (
                symbol is not None
                and trade.candidate.symbol
                != symbol
            ):
                continue

            mark = _mark_price(
                candidate=trade.candidate,
                timestamp=timestamp,
                market_bars=market_bars,
            )

            total += (
                trade.quantity
                * mark
            )

        return round(
            total,
            6,
        )

    def pending_exposure() -> float:
        return round(
            sum(
                trade.reserved_exposure
                for trade
                in pending.values()
            ),
            6,
        )

    def total_exposure(
        *,
        timestamp: datetime,
    ) -> float:
        return round(
            position_exposure(
                timestamp=timestamp
            )
            + pending_exposure(),
            6,
        )

    def observe(
        *,
        timestamp: datetime,
    ) -> None:
        nonlocal max_position_symbols
        nonlocal max_orders
        nonlocal max_exposure

        max_position_symbols = max(
            max_position_symbols,
            len(
                position_symbols()
            ),
        )

        max_orders = max(
            max_orders,
            len(pending),
        )

        max_exposure = max(
            max_exposure,
            total_exposure(
                timestamp=timestamp
            ),
        )

        reserved_symbols = (
            position_symbols()
            | pending_symbols()
        )

        if (
            len(reserved_symbols)
            > max_open_positions
        ):
            raise HistoricalPortfolioReplayError(
                "PORTFOLIO_POSITION_INVARIANT_BROKEN"
            )

        if (
            len(pending)
            > max_open_orders
        ):
            raise HistoricalPortfolioReplayError(
                "PORTFOLIO_ORDER_INVARIANT_BROKEN"
            )

    def schedule(
        *,
        timestamp: datetime,
        event_priority: int,
        event_type: str,
        trade_id: str,
    ) -> None:
        nonlocal event_counter

        event_counter += 1

        heapq.heappush(
            events,
            (
                timestamp,
                event_priority,
                event_counter,
                event_type,
                trade_id,
            ),
        )

    def process_events_through(
        *,
        timestamp: datetime | None,
    ) -> None:
        nonlocal completed_positions
        nonlocal accepted_unfilled

        while events:
            (
                event_time,
                _,
                _,
                event_type,
                trade_id,
            ) = events[0]

            if (
                timestamp is not None
                and event_time
                > timestamp
            ):
                break

            heapq.heappop(
                events
            )

            if event_type == "FILL":
                trade = pending.pop(
                    trade_id,
                    None,
                )

                if trade is None:
                    continue

                positions[
                    trade_id
                ] = trade

            elif event_type == "EXIT":
                trade = positions.pop(
                    trade_id,
                    None,
                )

                if trade is None:
                    raise HistoricalPortfolioReplayError(
                        "PORTFOLIO_EXIT_WITHOUT_POSITION"
                    )

                pnl = (
                    trade.quantity
                    * trade.candidate.per_share_pnl
                )

                daily_realized[
                    trade.candidate.date
                ] += pnl

                strategy_pnl[
                    trade.candidate.strategy
                ] += pnl

                completed_positions += 1

            elif event_type == "CANCEL":
                trade = pending.pop(
                    trade_id,
                    None,
                )

                if trade is None:
                    continue

                accepted_unfilled += 1

            else:
                raise HistoricalPortfolioReplayError(
                    "UNKNOWN_PORTFOLIO_EVENT"
                )

            observe(
                timestamp=event_time
            )

    for created_at, group_iter in groupby(
        items,
        key=lambda item: item.created_at,
    ):
        process_events_through(
            timestamp=created_at
        )

        group = list(
            group_iter
        )

        group.sort(
            key=lambda item: (
                priority.get(
                    item.strategy,
                    len(priority),
                ),
                -float(
                    item.allocation_score
                ),
                item.symbol,
                item.strategy,
            )
        )

        strategy_event_pools = {}

        for candidate in group:
            if (
                candidate.strategy
                not in strategy_event_pools
            ):
                strategy_event_pools[
                    candidate.strategy
                ] = max(
                    0.0,
                    float(
                        operational_cap
                    )
                    - total_exposure(
                        timestamp=created_at
                    ),
                )

            reason = None

            if (
                daily_realized[
                    candidate.date
                ]
                <= -max_daily_loss
            ):
                reason = (
                    "DAILY_LOSS_LIMIT_REACHED"
                )

            elif (
                candidate.symbol
                in pending_symbols()
            ):
                reason = (
                    "OPEN_ORDER_ALREADY_EXISTS_FOR_SYMBOL"
                )

            elif (
                len(pending) + 1
                > max_open_orders
            ):
                reason = (
                    "MAX_OPEN_ORDERS_EXCEEDED"
                )

            else:
                projected_symbols = (
                    position_symbols()
                    | pending_symbols()
                    | {
                        candidate.symbol
                    }
                )

                if (
                    len(projected_symbols)
                    > max_open_positions
                ):
                    reason = (
                        "MAX_OPEN_POSITIONS_EXCEEDED"
                    )

            current_symbol_exposure = (
                position_exposure(
                    timestamp=created_at,
                    symbol=candidate.symbol,
                )
            )

            remaining_symbol_capacity = (
                per_position_cap
                - current_symbol_exposure
            )

            policy_pool = (
                strategy_event_pools[
                    candidate.strategy
                ]
            )

            policy_budget = round(
                policy_pool
                * float(
                    candidate.allocation_weight
                ),
                2,
            )

            quantity = 0

            if (
                reason is None
                and policy_budget <= 0
            ):
                reason = (
                    "POLICY_BUDGET_EXHAUSTED"
                )

            position_budget = min(
                remaining_symbol_capacity,
                policy_budget,
            )

            if reason is None:
                quantity = math.floor(
                    position_budget
                    / candidate.entry_price
                )

                if quantity <= 0:
                    if (
                        remaining_symbol_capacity
                        <= 0
                    ):
                        reason = (
                            "PER_POSITION_CAP_EXHAUSTED"
                        )
                    else:
                        reason = (
                            "POSITION_BUDGET_BELOW_ONE_SHARE"
                        )

            proposed_exposure = round(
                quantity
                * candidate.entry_price,
                6,
            )

            if reason is None:
                current_total = (
                    total_exposure(
                        timestamp=created_at
                    )
                )

                projected_total = round(
                    current_total
                    + proposed_exposure,
                    6,
                )

                if projected_total > hard_cap:
                    reason = (
                        "HARD_EXPOSURE_CAP_EXCEEDED"
                    )

                elif (
                    projected_total
                    > operational_cap
                ):
                    reason = (
                        "OPERATIONAL_EXPOSURE_CAP_EXCEEDED"
                    )

            if reason is not None:
                rejection_counts[
                    reason
                ] += 1

                rejected_by_day[
                    candidate.date
                ] += 1

                if (
                    reason
                    == "DAILY_LOSS_LIMIT_REACHED"
                ):
                    halt_by_day[
                        candidate.date
                    ] += 1

                continue

            trade = _AcceptedTrade(
                candidate=candidate,
                quantity=quantity,
                reserved_exposure=(
                    proposed_exposure
                ),
            )

            trade_id = (
                candidate.candidate_id
            )

            if (
                trade_id in pending
                or trade_id in positions
            ):
                raise HistoricalPortfolioReplayError(
                    "DUPLICATE_PORTFOLIO_CANDIDATE_ID"
                )

            pending[
                trade_id
            ] = trade

            accepted_entries += 1

            accepted_by_day[
                candidate.date
            ] += 1

            if candidate.status == "COMPLETED":
                schedule(
                    timestamp=(
                        candidate.fill_time
                    ),
                    event_priority=0,
                    event_type="FILL",
                    trade_id=trade_id,
                )

                schedule(
                    timestamp=(
                        candidate.exit_time
                    ),
                    event_priority=1,
                    event_type="EXIT",
                    trade_id=trade_id,
                )

            else:
                schedule(
                    timestamp=(
                        candidate.cancel_time
                    ),
                    event_priority=2,
                    event_type="CANCEL",
                    trade_id=trade_id,
                )

            observe(
                timestamp=created_at
            )

        process_events_through(
            timestamp=created_at
        )

    process_events_through(
        timestamp=None
    )

    if pending:
        raise HistoricalPortfolioReplayError(
            "PORTFOLIO_PENDING_ORDERS_REMAIN"
        )

    if positions:
        raise HistoricalPortfolioReplayError(
            "PORTFOLIO_POSITIONS_REMAIN"
        )

    all_dates = sorted({
        candidate.date
        for candidate
        in items
    })

    days = tuple(
        HistoricalPortfolioDayResult(
            date=date,
            realized_pnl=round(
                daily_realized[
                    date
                ],
                6,
            ),
            accepted_entries=(
                accepted_by_day[
                    date
                ]
            ),
            rejected_entries=(
                rejected_by_day[
                    date
                ]
            ),
            daily_loss_halt_rejections=(
                halt_by_day[
                    date
                ]
            ),
        )
        for date in all_dates
    )

    return HistoricalPortfolioReport(
        per_position_cap=round(
            float(
                per_position_cap
            ),
            2,
        ),
        max_daily_loss=round(
            float(
                max_daily_loss
            ),
            2,
        ),
        max_open_positions=(
            max_open_positions
        ),
        max_open_orders=(
            max_open_orders
        ),
        operational_cap=round(
            float(
                operational_cap
            ),
            2,
        ),
        hard_cap=round(
            float(
                hard_cap
            ),
            2,
        ),
        candidates=len(items),
        accepted_entries=(
            accepted_entries
        ),
        rejected_entries=(
            len(items)
            - accepted_entries
        ),
        completed_positions=(
            completed_positions
        ),
        accepted_unfilled_orders=(
            accepted_unfilled
        ),
        total_realized_pnl=round(
            sum(
                daily_realized.values()
            ),
            6,
        ),
        max_position_symbols_observed=(
            max_position_symbols
        ),
        max_open_orders_observed=(
            max_orders
        ),
        max_exposure_observed=round(
            max_exposure,
            6,
        ),
        rejection_counts=tuple(
            sorted(
                rejection_counts.items()
            )
        ),
        strategy_realized_pnl=tuple(
            sorted(
                (
                    strategy,
                    round(
                        pnl,
                        6,
                    ),
                )
                for strategy, pnl
                in strategy_pnl.items()
            )
        ),
        days=days,
    )
