from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .risk_adjusted_allocator import (
    RiskAdjustedOpportunity,
    ShadowRiskAdjustedPlan,
    build_shadow_risk_adjusted_plan,
)
from .scanner_performance_summary import (
    PerformanceSummary,
    summarize,
)


@dataclass(frozen=True)
class StrategyPerformanceContext:
    model: str
    as_of_date: str
    strict: bool

    manipulation: PerformanceSummary
    quick_flip: PerformanceSummary

    rows_available_before_date: int


@dataclass(frozen=True)
class ShadowAllocationComparison:
    symbol: str
    strategy: str

    reward_risk: float
    score: float

    equal_weight: float
    equal_allocation: float

    risk_adjusted_weight: float
    risk_adjusted_allocation: float

    eligible: bool
    rejection_reason: str | None


@dataclass(frozen=True)
class DailyShadowAllocationReport:
    trading_date: str
    model: str
    deployable_pool: float

    best_symbol: str | None
    best_strategy: str | None

    decision_reason: str

    comparisons: tuple[
        ShadowAllocationComparison,
        ...
    ]

    cash_retained: float
    shadow_only: bool = True


def _date_text(
    value: date | str,
) -> str:
    if isinstance(
        value,
        date,
    ):
        return value.isoformat()

    text = str(value).strip()

    try:
        return date.fromisoformat(
            text
        ).isoformat()
    except ValueError as error:
        raise ValueError(
            "Expected ISO trading date YYYY-MM-DD."
        ) from error


def rows_before_trading_date(
    rows: list[dict[str, str]],
    *,
    trading_date: date | str,
) -> list[dict[str, str]]:
    """
    Remove the current trading date and all future rows.

    This is the anti-lookahead boundary for the shadow allocator.
    """
    cutoff = _date_text(
        trading_date
    )

    result = []

    for row in rows:
        row_date = str(
            row.get(
                "date",
                "",
            )
        ).strip()

        if not row_date:
            continue

        try:
            normalized = (
                date.fromisoformat(
                    row_date
                )
                .isoformat()
            )
        except ValueError:
            continue

        if normalized < cutoff:
            result.append(
                row
            )

    return result


def build_strategy_performance_context(
    *,
    rows: list[dict[str, str]],
    model: str,
    trading_date: date | str,
    strict: bool = True,
) -> StrategyPerformanceContext:
    """
    Build both strategy histories using only information that
    existed before the requested trading date.
    """
    as_of_date = _date_text(
        trading_date
    )

    historical_rows = (
        rows_before_trading_date(
            rows,
            trading_date=as_of_date,
        )
    )

    manipulation = summarize(
        rows=historical_rows,
        model=model,
        strategy="MANIPULATION",
        strict=strict,
    )

    quick_flip = summarize(
        rows=historical_rows,
        model=model,
        strategy="QUICK_FLIP",
        strict=strict,
    )

    return StrategyPerformanceContext(
        model=model.upper(),
        as_of_date=as_of_date,
        strict=strict,
        manipulation=manipulation,
        quick_flip=quick_flip,
        rows_available_before_date=(
            len(historical_rows)
        ),
    )


def _decision_reason(
    plan: ShadowRiskAdjustedPlan,
) -> tuple[
    str,
    str | None,
    str | None,
]:
    eligible = [
        item
        for item in plan.allocations
        if item.eligible
    ]

    funded = [
        item
        for item in plan.allocations
        if item.recommended_allocation
        > 0
    ]

    if not plan.allocations:
        return (
            "NO_CANDIDATES",
            None,
            None,
        )

    if not eligible:
        return (
            "NO_ELIGIBLE_OPPORTUNITIES",
            None,
            None,
        )

    ranked = sorted(
        eligible,
        key=lambda item: (
            -item.score,
            item.symbol,
            item.strategy,
        ),
    )

    best = ranked[0]

    if len(eligible) == 1:
        return (
            "SINGLE_ELIGIBLE_OPPORTUNITY",
            best.symbol,
            best.strategy,
        )

    if (
        len(funded) == 1
        and funded[0].allocation_weight
        == 1.0
    ):
        return (
            "DOMINANT_OPPORTUNITY",
            best.symbol,
            best.strategy,
        )

    return (
        "SCORE_WEIGHTED_PORTFOLIO",
        best.symbol,
        best.strategy,
    )


def build_daily_shadow_allocation_report(
    *,
    trading_date: date | str,
    model: str,
    opportunities: list[
        RiskAdjustedOpportunity
    ],
    deployable_pool: float,
    minimum_reward_risk: float = 1.25,
    dominance_ratio: float = 1.75,
    concentration_power: float = 2.0,
    full_confidence_samples: int = 30,
) -> DailyShadowAllocationReport:
    """
    Compare today's existing equal-weight concept against the V2
    shadow risk-adjusted recommendation.

    This function never modifies Webull preview sizing.
    """
    trading_date_text = _date_text(
        trading_date
    )

    plan = build_shadow_risk_adjusted_plan(
        opportunities,
        deployable_pool=(
            deployable_pool
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
        full_confidence_samples=(
            full_confidence_samples
        ),
    )

    candidate_count = len(
        opportunities
    )

    equal_weight = (
        1.0 / candidate_count
        if candidate_count
        else 0.0
    )

    equal_allocation = (
        float(deployable_pool)
        * equal_weight
    )

    (
        reason,
        best_symbol,
        best_strategy,
    ) = _decision_reason(
        plan
    )

    comparisons = tuple(
        ShadowAllocationComparison(
            symbol=item.symbol,
            strategy=item.strategy,
            reward_risk=(
                item.reward_risk
            ),
            score=item.score,
            equal_weight=round(
                equal_weight,
                6,
            ),
            equal_allocation=round(
                equal_allocation,
                2,
            ),
            risk_adjusted_weight=(
                item.allocation_weight
            ),
            risk_adjusted_allocation=(
                item.recommended_allocation
            ),
            eligible=item.eligible,
            rejection_reason=(
                item.rejection_reason
            ),
        )
        for item in plan.allocations
    )

    return DailyShadowAllocationReport(
        trading_date=(
            trading_date_text
        ),
        model=model.upper(),
        deployable_pool=round(
            float(deployable_pool),
            2,
        ),
        best_symbol=best_symbol,
        best_strategy=best_strategy,
        decision_reason=reason,
        comparisons=comparisons,
        cash_retained=(
            plan.cash_retained
        ),
    )


def shadow_report_to_dict(
    report: DailyShadowAllocationReport,
) -> dict:
    return {
        "tradingDate": (
            report.trading_date
        ),
        "model": report.model,
        "shadowOnly": True,
        "deployablePool": (
            report.deployable_pool
        ),
        "bestSymbol": (
            report.best_symbol
        ),
        "bestStrategy": (
            report.best_strategy
        ),
        "decisionReason": (
            report.decision_reason
        ),
        "cashRetained": (
            report.cash_retained
        ),
        "comparisons": [
            {
                "symbol": item.symbol,
                "strategy": (
                    item.strategy
                ),
                "rewardRisk": (
                    item.reward_risk
                ),
                "score": item.score,
                "equalWeight": (
                    item.equal_weight
                ),
                "equalAllocation": (
                    item.equal_allocation
                ),
                "riskAdjustedWeight": (
                    item.risk_adjusted_weight
                ),
                "riskAdjustedAllocation": (
                    item.risk_adjusted_allocation
                ),
                "eligible": (
                    item.eligible
                ),
                "rejectionReason": (
                    item.rejection_reason
                ),
            }
            for item
            in report.comparisons
        ],
    }
