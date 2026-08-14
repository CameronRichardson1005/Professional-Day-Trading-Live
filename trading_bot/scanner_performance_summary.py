from __future__ import annotations

import csv
import math
import statistics
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path


MODEL_PREFIXES = (
    "v1",
    "v2",
    "v3",
    "v4",
)


@dataclass(frozen=True)
class PerformanceSummary:
    model: str
    strategy: str
    sample: str
    rank: int | None

    selected_observations: int
    strategy_signals: int
    filled_trades: int

    wins: int
    losses: int

    target_hits: int
    stop_hits: int

    tp1_hits: int
    tp2_hits: int

    average_return_pct: float | None
    expectancy_per_selection_pct: float
    expectancy_per_signal_pct: float
    expectancy_per_filled_trade_pct: float | None

    win_rate_pct: float | None
    target_rate_pct: float | None
    tp1_hit_rate_pct: float | None
    tp2_hit_rate_pct: float | None

    average_mfe_pct: float | None
    average_mae_pct: float | None

    profit_factor: float | None

    daily_compounded_return_pct: float
    annualized_sharpe: float | None
    annualized_sortino: float | None
    max_drawdown_pct: float

    # Positive magnitude of the 75th percentile of historical
    # Quick Flip adverse excursion. None for Manipulation or
    # when no Quick Flip MAE observations exist.
    tail_mae_75_pct: float | None = None


def _float(
    value: object,
) -> float | None:
    text = str(
        value
    ).strip()

    if not text:
        return None

    try:
        return float(
            text
        )
    except (
        TypeError,
        ValueError,
    ):
        return None


def _mean(
    values: list[float],
) -> float | None:
    if not values:
        return None

    return statistics.fmean(
        values
    )


def _percentile(
    values: list[float],
    percentile: float,
) -> float | None:
    """
    Linear-interpolated empirical percentile.

    The caller supplies positive magnitudes when measuring
    adverse excursion, so larger values mean larger downside.
    """
    if not values:
        return None

    if not 0.0 <= percentile <= 1.0:
        raise ValueError(
            "percentile must be between 0 and 1."
        )

    ordered = sorted(
        float(value)
        for value in values
    )

    if len(ordered) == 1:
        return ordered[0]

    position = (
        (len(ordered) - 1)
        * percentile
    )

    lower_index = int(
        math.floor(position)
    )

    upper_index = int(
        math.ceil(position)
    )

    lower = ordered[
        lower_index
    ]

    upper = ordered[
        upper_index
    ]

    if lower_index == upper_index:
        return lower

    fraction = (
        position
        - lower_index
    )

    return (
        lower
        + (
            upper - lower
        )
        * fraction
    )


def _ratio_pct(
    numerator: int,
    denominator: int,
) -> float | None:
    if denominator <= 0:
        return None

    return (
        numerator
        / denominator
        * 100.0
    )


def _profit_factor(
    returns: list[float],
) -> float | None:
    gross_profit = sum(
        value
        for value in returns
        if value > 0
    )

    gross_loss = abs(
        sum(
            value
            for value in returns
            if value < 0
        )
    )

    if gross_loss == 0:
        if gross_profit > 0:
            return math.inf

        return None

    return (
        gross_profit
        / gross_loss
    )


def _daily_metrics(
    daily_returns_pct: list[float],
) -> tuple[
    float,
    float | None,
    float | None,
    float,
]:
    if not daily_returns_pct:
        return (
            0.0,
            None,
            None,
            0.0,
        )

    daily_decimal = [
        value / 100.0
        for value in daily_returns_pct
    ]

    equity = 1.0

    peak = 1.0
    max_drawdown = 0.0

    for daily_return in daily_decimal:
        equity *= (
            1.0
            + daily_return
        )

        peak = max(
            peak,
            equity,
        )

        if peak > 0:
            drawdown = (
                peak - equity
            ) / peak

            max_drawdown = max(
                max_drawdown,
                drawdown,
            )

    compounded = (
        equity - 1.0
    ) * 100.0

    mean_daily = (
        statistics.fmean(
            daily_decimal
        )
    )

    sharpe = None

    if len(
        daily_decimal
    ) >= 2:
        std = statistics.stdev(
            daily_decimal
        )

        if std > 0:
            sharpe = (
                mean_daily
                / std
                * math.sqrt(252.0)
            )

    downside_squared = [
        min(
            value,
            0.0,
        ) ** 2
        for value in daily_decimal
    ]

    downside_deviation = math.sqrt(
        statistics.fmean(
            downside_squared
        )
    )

    sortino = None

    if downside_deviation > 0:
        sortino = (
            mean_daily
            / downside_deviation
            * math.sqrt(252.0)
        )

    return (
        compounded,
        sharpe,
        sortino,
        max_drawdown * 100.0,
    )


def load_master_rows(
    path: Path,
) -> list[dict[str, str]]:
    with path.open(
        newline="",
        encoding="utf-8",
    ) as handle:
        return list(
            csv.DictReader(
                handle
            )
        )


def summarize(
    *,
    rows: list[dict[str, str]],
    model: str,
    strategy: str,
    strict: bool = False,
    rank: int | None = None,
) -> PerformanceSummary:
    if model not in MODEL_PREFIXES:
        raise ValueError(
            f"Unknown model prefix: {model}"
        )

    if strategy not in {
        "MANIPULATION",
        "QUICK_FLIP",
    }:
        raise ValueError(
            f"Unknown strategy: {strategy}"
        )

    selected = []

    for row in rows:
        if (
            row.get(
                f"{model}_selected"
            )
            != "YES"
        ):
            continue

        if rank is not None:
            try:
                row_rank = int(
                    row[
                        f"{model}_rank"
                    ]
                )
            except (
                TypeError,
                ValueError,
            ):
                continue

            if row_rank != rank:
                continue

        if strict:
            if (
                row.get(
                    "post_opening_outcome_clean"
                )
                != "YES"
            ):
                continue

        selected.append(
            row
        )

    if strategy == "MANIPULATION":
        signal_field = (
            "manipulation_signal"
        )

        return_field = (
            "manipulation_return_pct"
        )

        filled_field = (
            "manipulation_filled"
        )

    else:
        signal_field = (
            "quick_flip_signal"
        )

        return_field = (
            "quick_flip_endpoint_return_pct"
        )

        filled_field = (
            "quick_flip_filled"
        )

    signal_rows = [
        row
        for row in selected
        if row.get(
            signal_field
        ) == "INVEST"
    ]

    filled_rows = [
        row
        for row in signal_rows
        if row.get(
            filled_field
        ) == "YES"
    ]

    returns = []

    return_by_row = {}

    for index, row in enumerate(
        selected
    ):
        value = _float(
            row.get(
                return_field
            )
        )

        if value is not None:
            returns.append(
                value
            )

            return_by_row[
                index
            ] = value

    wins = sum(
        value > 0
        for value in returns
    )

    losses = sum(
        value < 0
        for value in returns
    )

    target_hits = 0
    stop_hits = 0

    tp1_hits = 0
    tp2_hits = 0

    mfe_values = []
    mae_values = []

    if strategy == "MANIPULATION":
        target_hits = sum(
            row.get(
                "manipulation_outcome"
            ) == "TARGET"
            for row in filled_rows
        )

        stop_hits = sum(
            row.get(
                "manipulation_outcome"
            ) == "STOP"
            for row in filled_rows
        )

    else:
        tp1_hits = sum(
            row.get(
                "quick_flip_tp1_hit"
            ) == "YES"
            for row in filled_rows
        )

        tp2_hits = sum(
            row.get(
                "quick_flip_tp2_hit"
            ) == "YES"
            for row in filled_rows
        )

        for row in filled_rows:
            mfe = _float(
                row.get(
                    "quick_flip_mfe_pct"
                )
            )

            mae = _float(
                row.get(
                    "quick_flip_mae_pct"
                )
            )

            if mfe is not None:
                mfe_values.append(
                    mfe
                )

            if mae is not None:
                mae_values.append(
                    mae
                )

    selected_count = len(
        selected
    )

    signal_count = len(
        signal_rows
    )

    filled_count = len(
        filled_rows
    )

    total_realized_return = sum(
        returns
    )

    expectancy_selection = (
        total_realized_return
        / selected_count
        if selected_count
        else 0.0
    )

    expectancy_signal = (
        total_realized_return
        / signal_count
        if signal_count
        else 0.0
    )

    expectancy_filled = (
        total_realized_return
        / filled_count
        if filled_count
        else None
    )

    daily_selected_returns = (
        defaultdict(
            list
        )
    )

    for row in selected:
        value = _float(
            row.get(
                return_field
            )
        )

        daily_selected_returns[
            row["date"]
        ].append(
            value
            if value is not None
            else 0.0
        )

    daily_returns = []

    for date_str in sorted(
        daily_selected_returns
    ):
        values = (
            daily_selected_returns[
                date_str
            ]
        )

        daily_returns.append(
            statistics.fmean(
                values
            )
        )

    (
        compounded_return,
        sharpe,
        sortino,
        max_drawdown,
    ) = _daily_metrics(
        daily_returns
    )

    return PerformanceSummary(
        model=model.upper(),
        strategy=strategy,
        sample=(
            "STRICT"
            if strict
            else "ALL"
        ),
        rank=rank,
        selected_observations=(
            selected_count
        ),
        strategy_signals=(
            signal_count
        ),
        filled_trades=(
            filled_count
        ),
        wins=wins,
        losses=losses,
        target_hits=target_hits,
        stop_hits=stop_hits,
        tp1_hits=tp1_hits,
        tp2_hits=tp2_hits,
        average_return_pct=(
            _mean(
                returns
            )
        ),
        expectancy_per_selection_pct=(
            expectancy_selection
        ),
        expectancy_per_signal_pct=(
            expectancy_signal
        ),
        expectancy_per_filled_trade_pct=(
            expectancy_filled
        ),
        win_rate_pct=(
            _ratio_pct(
                wins,
                wins + losses,
            )
        ),
        target_rate_pct=(
            _ratio_pct(
                target_hits,
                filled_count,
            )
            if strategy
            == "MANIPULATION"
            else None
        ),
        tp1_hit_rate_pct=(
            _ratio_pct(
                tp1_hits,
                filled_count,
            )
            if strategy
            == "QUICK_FLIP"
            else None
        ),
        tp2_hit_rate_pct=(
            _ratio_pct(
                tp2_hits,
                filled_count,
            )
            if strategy
            == "QUICK_FLIP"
            else None
        ),
        average_mfe_pct=(
            _mean(
                mfe_values
            )
        ),
        average_mae_pct=(
            _mean(
                mae_values
            )
        ),
        tail_mae_75_pct=(
            _percentile(
                [
                    abs(value)
                    for value
                    in mae_values
                ],
                0.75,
            )
        ),
        profit_factor=(
            _profit_factor(
                returns
            )
        ),
        daily_compounded_return_pct=(
            compounded_return
        ),
        annualized_sharpe=(
            sharpe
        ),
        annualized_sortino=(
            sortino
        ),
        max_drawdown_pct=(
            max_drawdown
        ),
    )
