from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from types import SimpleNamespace
from typing import Iterable

from .risk_adjusted_allocator import (
    build_shadow_risk_adjusted_plan,
)
from .risk_adjusted_strategy_adapters import (
    build_manipulation_opportunity,
    build_quick_flip_opportunity,
)
from .scanner_performance_summary import (
    PerformanceSummary,
    summarize,
)


SEPARATE_SIGNALS = "SEPARATE_SIGNALS"
SYMBOL_DEDUPED_CAUSAL = "SYMBOL_DEDUPED_CAUSAL"

PORTFOLIO_MODES = {
    SEPARATE_SIGNALS,
    SYMBOL_DEDUPED_CAUSAL,
}


@dataclass(frozen=True)
class WalkForwardAllocation:
    date: str
    symbol: str
    strategy: str
    event_time: str

    allocation: float
    realized_return_pct: float
    contribution_pct: float

    score: float
    reward_risk: float


@dataclass(frozen=True)
class WalkForwardDay:
    date: str
    portfolio_mode: str
    quick_flip_reserve_fraction: float

    baseline_return_pct: float
    v2_return_pct: float

    v2_cash_retained: float
    v2_allocated: float

    manipulation_signals: int
    quick_flip_signals: int

    quick_flip_opportunities_scored: int
    quick_flip_opportunities_unscored: int

    symbol_deduped_count: int

    allocations: tuple[
        WalkForwardAllocation,
        ...
    ]


@dataclass(frozen=True)
class WalkForwardPerformance:
    days: int

    compounded_return_pct: float
    average_daily_return_pct: float
    max_drawdown_pct: float

    positive_days: int
    negative_days: int
    flat_days: int


@dataclass(frozen=True)
class WalkForwardResult:
    portfolio_mode: str
    quick_flip_reserve_fraction: float

    days: tuple[
        WalkForwardDay,
        ...
    ]

    baseline: WalkForwardPerformance
    v2: WalkForwardPerformance

    v2_helped_days: int
    v2_hurt_days: int
    v2_equal_days: int

    days_retaining_cash: int
    all_cash_days: int

    average_cash_retained: float
    average_capital_deployed: float

    symbol_deduped_count: int


def _as_float(
    value,
) -> float | None:
    if value in {
        None,
        "",
    }:
        return None

    try:
        return float(value)
    except (
        TypeError,
        ValueError,
    ):
        return None


def _is_yes(
    value,
) -> bool:
    return (
        str(
            value
        ).upper()
        == "YES"
    )


def is_production_row(
    row: dict[str, str],
    *,
    permanent_symbols: set[str],
) -> bool:
    symbol = str(
        row.get(
            "symbol",
            "",
        )
    ).upper()

    return (
        symbol
        in permanent_symbols
        or row.get(
            "v1_selected"
        )
        == "YES"
    )


def production_rows(
    rows: Iterable[
        dict[str, str]
    ],
    *,
    permanent_symbols: set[str],
) -> list[
    dict[str, str]
]:
    return [
        row
        for row in rows
        if is_production_row(
            row,
            permanent_symbols=(
                permanent_symbols
            ),
        )
    ]


def _selected_copy(
    row: dict[str, str],
) -> dict[str, str]:
    return {
        **row,
        "v1_selected": "YES",
    }


def performance_before_date(
    *,
    production_history: list[
        dict[str, str]
    ],
    trading_date: str,
    strategy: str,
) -> PerformanceSummary:
    prior = [
        _selected_copy(
            row
        )
        for row
        in production_history
        if str(
            row.get(
                "date",
                "",
            )
        )
        < trading_date
    ]

    return summarize(
        rows=prior,
        model="v1",
        strategy=strategy,
        strict=True,
    )


def _manipulation_return(
    row: dict[str, str],
) -> float:
    if not _is_yes(
        row.get(
            "manipulation_filled"
        )
    ):
        return 0.0

    value = _as_float(
        row.get(
            "manipulation_return_pct"
        )
    )

    return (
        value
        if value is not None
        else 0.0
    )


def _quick_flip_return(
    row: dict[str, str],
) -> float:
    if not _is_yes(
        row.get(
            "quick_flip_filled"
        )
    ):
        return 0.0

    value = _as_float(
        row.get(
            "quick_flip_endpoint_return_pct"
        )
    )

    return (
        value
        if value is not None
        else 0.0
    )


def _manipulation_opportunity(
    *,
    row: dict[str, str],
    performance: PerformanceSummary,
):
    entry = _as_float(
        row.get(
            "manipulation_entry"
        )
    )

    target = _as_float(
        row.get(
            "manipulation_target"
        )
    )

    stop = _as_float(
        row.get(
            "manipulation_trading_stop"
        )
    )

    if (
        entry is None
        or target is None
        or stop is None
    ):
        return None

    stock = SimpleNamespace(
        symbol=str(
            row["symbol"]
        ).upper(),
        signal="INVEST",
        limit_buy=entry,
        limit_sell=target,
        trading_stop_loss=stop,
    )

    try:
        return (
            build_manipulation_opportunity(
                stock,
                performance=performance,
            )
        )
    except ValueError:
        return None


def _quick_flip_opportunity(
    *,
    row: dict[str, str],
    performance: PerformanceSummary,
):
    entry = _as_float(
        row.get(
            "quick_flip_entry"
        )
    )

    tp1 = _as_float(
        row.get(
            "quick_flip_tp1"
        )
    )

    tp2 = _as_float(
        row.get(
            "quick_flip_tp2"
        )
    )

    if (
        entry is None
        or tp1 is None
        or tp2 is None
    ):
        return None

    signal = SimpleNamespace(
        symbol=str(
            row["symbol"]
        ).upper(),
        signal="INVEST",
        entry_price=entry,
        take_profit_1=tp1,
        take_profit_2=tp2,
    )

    try:
        return (
            build_quick_flip_opportunity(
                signal,
                performance=performance,
            )
        )
    except ValueError:
        # Most importantly, this covers early walk-forward
        # dates where no prior Quick Flip MFE/MAE sample
        # exists yet. Future history must never be backfilled.
        return None


def _confirmation_sort_key(
    row: dict[str, str],
):
    text = str(
        row.get(
            "quick_flip_confirmation_time",
            "",
        )
    )

    try:
        return datetime.fromisoformat(
            text
        )
    except ValueError:
        return datetime.max


def _quick_flip_groups(
    rows: list[
        dict[str, str]
    ],
) -> list[
    tuple[
        str,
        list[
            dict[str, str]
        ],
    ]
]:
    grouped = {}

    for row in rows:
        event_time = str(
            row.get(
                "quick_flip_confirmation_time",
                "",
            )
        )

        if not event_time:
            continue

        grouped.setdefault(
            event_time,
            [],
        ).append(
            row
        )

    result = []

    for event_time in sorted(
        grouped,
        key=lambda value:
        datetime.fromisoformat(
            value
        ),
    ):
        result.append(
            (
                event_time,
                grouped[
                    event_time
                ],
            )
        )

    return result


def _baseline_day_return(
    *,
    manipulation_rows: list[
        dict[str, str]
    ],
    quick_flip_rows: list[
        dict[str, str]
    ],
) -> float:
    """
    Causal equal-weight control approximating current sequential
    reservation behavior.

    Manipulation is known first at 09:45 ET and receives the whole
    normalized deployable pool when any Manipulation signal exists.

    Only when there is no Manipulation signal does the first
    confirmed Quick Flip timestamp receive the pool.
    """
    if manipulation_rows:
        weight = (
            1.0
            / len(
                manipulation_rows
            )
        )

        return sum(
            weight
            * _manipulation_return(
                row
            )
            for row
            in manipulation_rows
        )

    groups = (
        _quick_flip_groups(
            quick_flip_rows
        )
    )

    if not groups:
        return 0.0

    _, first_group = groups[0]

    weight = (
        1.0
        / len(
            first_group
        )
    )

    return sum(
        weight
        * _quick_flip_return(
            row
        )
        for row
        in first_group
    )


def simulate_walk_forward_day(
    *,
    trading_date: str,
    day_rows: list[
        dict[str, str]
    ],
    production_history: list[
        dict[str, str]
    ],
    portfolio_mode: str = (
        SEPARATE_SIGNALS
    ),
    quick_flip_reserve_fraction: float = 0.0,
    minimum_reward_risk: float = 1.25,
    dominance_ratio: float = 1.75,
    concentration_power: float = 2.0,
) -> WalkForwardDay:
    if (
        portfolio_mode
        not in PORTFOLIO_MODES
    ):
        raise ValueError(
            "Unknown portfolio mode: "
            f"{portfolio_mode}"
        )

    reserve = float(
        quick_flip_reserve_fraction
    )

    if not 0 <= reserve <= 1:
        raise ValueError(
            "quick_flip_reserve_fraction "
            "must be between 0 and 1."
        )

    strict_rows = [
        row
        for row
        in day_rows
        if (
            row.get(
                "post_opening_outcome_clean"
            )
            == "YES"
        )
    ]

    manipulation_rows = [
        row
        for row
        in strict_rows
        if (
            row.get(
                "manipulation_signal"
            )
            == "INVEST"
        )
    ]

    quick_flip_rows = [
        row
        for row
        in strict_rows
        if (
            row.get(
                "quick_flip_signal"
            )
            == "INVEST"
        )
    ]

    baseline_return = (
        _baseline_day_return(
            manipulation_rows=(
                manipulation_rows
            ),
            quick_flip_rows=(
                quick_flip_rows
            ),
        )
    )

    manipulation_performance = (
        performance_before_date(
            production_history=(
                production_history
            ),
            trading_date=(
                trading_date
            ),
            strategy="MANIPULATION",
        )
    )

    quick_flip_performance = (
        performance_before_date(
            production_history=(
                production_history
            ),
            trading_date=(
                trading_date
            ),
            strategy="QUICK_FLIP",
        )
    )

    allocations = []

    allocated_symbols = set()

    manipulation_pool = (
        1.0
        - reserve
    )

    manipulation_opportunities = []
    manipulation_rows_by_key = {}

    for row in manipulation_rows:
        opportunity = (
            _manipulation_opportunity(
                row=row,
                performance=(
                    manipulation_performance
                ),
            )
        )

        if opportunity is None:
            continue

        key = (
            opportunity.strategy,
            opportunity.symbol,
        )

        manipulation_rows_by_key[
            key
        ] = row

        manipulation_opportunities.append(
            opportunity
        )

    manipulation_cash_retained = (
        manipulation_pool
    )

    if (
        manipulation_pool > 0
        and manipulation_opportunities
    ):
        plan = (
            build_shadow_risk_adjusted_plan(
                manipulation_opportunities,
                deployable_pool=(
                    manipulation_pool
                ),
                minimum_reward_risk=(
                    minimum_reward_risk
                ),
                dominance_ratio=(
                    dominance_ratio
                ),
                concentration_power=(
                    concentration_power
                ),
            )
        )

        manipulation_cash_retained = (
            plan.cash_retained
        )

        for allocation in (
            plan.allocations
        ):
            if (
                allocation
                .recommended_allocation
                <= 0
            ):
                continue

            key = (
                allocation.strategy,
                allocation.symbol,
            )

            row = (
                manipulation_rows_by_key[
                    key
                ]
            )

            realized = (
                _manipulation_return(
                    row
                )
            )

            amount = float(
                allocation
                .recommended_allocation
            )

            allocations.append(
                WalkForwardAllocation(
                    date=trading_date,
                    symbol=(
                        allocation.symbol
                    ),
                    strategy=(
                        allocation.strategy
                    ),
                    event_time="09:45_ET",
                    allocation=amount,
                    realized_return_pct=(
                        realized
                    ),
                    contribution_pct=(
                        amount
                        * realized
                    ),
                    score=(
                        allocation.score
                    ),
                    reward_risk=(
                        allocation
                        .reward_risk
                    ),
                )
            )

            allocated_symbols.add(
                allocation.symbol
            )

    # Reserved QF cash plus any Manipulation cash deliberately
    # retained because no Manipulation opportunity cleared V2.
    remaining = (
        reserve
        + manipulation_cash_retained
    )

    quick_flip_scored = 0
    quick_flip_unscored = 0
    symbol_deduped_count = 0

    for (
        event_time,
        event_rows,
    ) in _quick_flip_groups(
        quick_flip_rows
    ):
        if remaining <= 0:
            break

        opportunities = []
        rows_by_key = {}

        for row in event_rows:
            symbol = str(
                row["symbol"]
            ).upper()

            if (
                portfolio_mode
                == SYMBOL_DEDUPED_CAUSAL
                and symbol
                in allocated_symbols
            ):
                symbol_deduped_count += 1
                continue

            opportunity = (
                _quick_flip_opportunity(
                    row=row,
                    performance=(
                        quick_flip_performance
                    ),
                )
            )

            if opportunity is None:
                quick_flip_unscored += 1
                continue

            quick_flip_scored += 1

            key = (
                opportunity.strategy,
                opportunity.symbol,
            )

            rows_by_key[
                key
            ] = row

            opportunities.append(
                opportunity
            )

        if not opportunities:
            continue

        plan = (
            build_shadow_risk_adjusted_plan(
                opportunities,
                deployable_pool=remaining,
                minimum_reward_risk=(
                    minimum_reward_risk
                ),
                dominance_ratio=(
                    dominance_ratio
                ),
                concentration_power=(
                    concentration_power
                ),
            )
        )

        remaining = (
            plan.cash_retained
        )

        for allocation in (
            plan.allocations
        ):
            if (
                allocation
                .recommended_allocation
                <= 0
            ):
                continue

            key = (
                allocation.strategy,
                allocation.symbol,
            )

            row = rows_by_key[
                key
            ]

            realized = (
                _quick_flip_return(
                    row
                )
            )

            amount = float(
                allocation
                .recommended_allocation
            )

            allocations.append(
                WalkForwardAllocation(
                    date=trading_date,
                    symbol=(
                        allocation.symbol
                    ),
                    strategy=(
                        allocation.strategy
                    ),
                    event_time=(
                        event_time
                    ),
                    allocation=amount,
                    realized_return_pct=(
                        realized
                    ),
                    contribution_pct=(
                        amount
                        * realized
                    ),
                    score=(
                        allocation.score
                    ),
                    reward_risk=(
                        allocation
                        .reward_risk
                    ),
                )
            )

            allocated_symbols.add(
                allocation.symbol
            )

    total_allocated = sum(
        item.allocation
        for item in allocations
    )

    v2_return = sum(
        item.contribution_pct
        for item in allocations
    )

    return WalkForwardDay(
        date=trading_date,
        portfolio_mode=(
            portfolio_mode
        ),
        quick_flip_reserve_fraction=(
            reserve
        ),
        baseline_return_pct=(
            baseline_return
        ),
        v2_return_pct=v2_return,
        v2_cash_retained=max(
            0.0,
            1.0
            - total_allocated,
        ),
        v2_allocated=min(
            1.0,
            total_allocated,
        ),
        manipulation_signals=len(
            manipulation_rows
        ),
        quick_flip_signals=len(
            quick_flip_rows
        ),
        quick_flip_opportunities_scored=(
            quick_flip_scored
        ),
        quick_flip_opportunities_unscored=(
            quick_flip_unscored
        ),
        symbol_deduped_count=(
            symbol_deduped_count
        ),
        allocations=tuple(
            allocations
        ),
    )


def _performance(
    daily_returns: list[
        float
    ],
) -> WalkForwardPerformance:
    equity = 1.0
    peak = 1.0
    max_drawdown = 0.0

    for value in daily_returns:
        equity *= (
            1.0
            + value / 100.0
        )

        peak = max(
            peak,
            equity,
        )

        if peak > 0:
            drawdown = (
                (
                    equity
                    / peak
                )
                - 1.0
            ) * 100.0

            max_drawdown = min(
                max_drawdown,
                drawdown,
            )

    compounded = (
        equity
        - 1.0
    ) * 100.0

    average = (
        sum(
            daily_returns
        )
        / len(
            daily_returns
        )
        if daily_returns
        else 0.0
    )

    return WalkForwardPerformance(
        days=len(
            daily_returns
        ),
        compounded_return_pct=(
            compounded
        ),
        average_daily_return_pct=(
            average
        ),
        max_drawdown_pct=(
            max_drawdown
        ),
        positive_days=sum(
            value > 0
            for value
            in daily_returns
        ),
        negative_days=sum(
            value < 0
            for value
            in daily_returns
        ),
        flat_days=sum(
            value == 0
            for value
            in daily_returns
        ),
    )


def run_walk_forward(
    *,
    rows: list[
        dict[str, str]
    ],
    permanent_symbols: set[str],
    portfolio_mode: str = (
        SEPARATE_SIGNALS
    ),
    quick_flip_reserve_fraction: float = 0.0,
    minimum_reward_risk: float = 1.25,
    dominance_ratio: float = 1.75,
    concentration_power: float = 2.0,
) -> WalkForwardResult:
    history = production_rows(
        rows,
        permanent_symbols=(
            permanent_symbols
        ),
    )

    dates = sorted({
        str(
            row["date"]
        )
        for row
        in history
    })

    by_date = {
        date_str: [
            row
            for row
            in history
            if str(
                row["date"]
            )
            == date_str
        ]
        for date_str
        in dates
    }

    day_results = []

    for trading_date in dates:
        day_results.append(
            simulate_walk_forward_day(
                trading_date=(
                    trading_date
                ),
                day_rows=(
                    by_date[
                        trading_date
                    ]
                ),
                production_history=(
                    history
                ),
                portfolio_mode=(
                    portfolio_mode
                ),
                quick_flip_reserve_fraction=(
                    quick_flip_reserve_fraction
                ),
                minimum_reward_risk=(
                    minimum_reward_risk
                ),
                dominance_ratio=(
                    dominance_ratio
                ),
                concentration_power=(
                    concentration_power
                ),
            )
        )

    baseline_returns = [
        day.baseline_return_pct
        for day
        in day_results
    ]

    v2_returns = [
        day.v2_return_pct
        for day
        in day_results
    ]

    tolerance = 1e-12

    helped = sum(
        day.v2_return_pct
        > (
            day.baseline_return_pct
            + tolerance
        )
        for day
        in day_results
    )

    hurt = sum(
        day.v2_return_pct
        < (
            day.baseline_return_pct
            - tolerance
        )
        for day
        in day_results
    )

    equal = (
        len(
            day_results
        )
        - helped
        - hurt
    )

    return WalkForwardResult(
        portfolio_mode=(
            portfolio_mode
        ),
        quick_flip_reserve_fraction=(
            quick_flip_reserve_fraction
        ),
        days=tuple(
            day_results
        ),
        baseline=_performance(
            baseline_returns
        ),
        v2=_performance(
            v2_returns
        ),
        v2_helped_days=helped,
        v2_hurt_days=hurt,
        v2_equal_days=equal,
        days_retaining_cash=sum(
            day.v2_cash_retained
            > tolerance
            for day
            in day_results
        ),
        all_cash_days=sum(
            day.v2_cash_retained
            >= (
                1.0
                - tolerance
            )
            for day
            in day_results
        ),
        average_cash_retained=(
            sum(
                day.v2_cash_retained
                for day
                in day_results
            )
            / len(
                day_results
            )
            if day_results
            else 0.0
        ),
        average_capital_deployed=(
            sum(
                day.v2_allocated
                for day
                in day_results
            )
            / len(
                day_results
            )
            if day_results
            else 0.0
        ),
        symbol_deduped_count=sum(
            day.symbol_deduped_count
            for day
            in day_results
        ),
    )
