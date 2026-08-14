from __future__ import annotations

from dataclasses import dataclass

from .risk_adjusted_allocator import (
    RiskAdjustedOpportunity,
    score_risk_adjusted_opportunity,
)


METHOD = "DOMINANCE_EQUAL_WEIGHT_SHADOW_V1"

# This is the effectively-ungated value used in the corrected
# walk-forward research. It replaces the old 1.25 research gate
# for this policy only.
MINIMUM_REWARD_RISK = 0.01

# Keep the original pre-sensitivity-test dominance threshold.
DOMINANCE_RATIO = 1.75


@dataclass(frozen=True)
class DominanceEqualAllocation:
    symbol: str
    strategy: str

    score: float
    reward_risk: float

    allocation_weight: float
    recommended_allocation: float

    eligible: bool
    rejection_reason: str | None


@dataclass(frozen=True)
class DominanceEqualPlan:
    deployable_pool: float

    minimum_reward_risk: float
    dominance_ratio: float

    decision_reason: str

    best_symbol: str | None
    best_strategy: str | None

    allocations: tuple[
        DominanceEqualAllocation,
        ...
    ]

    cash_retained: float

    method: str = METHOD
    shadow_only: bool = True


def _cent_allocations(
    *,
    pool: float,
    funded_keys: list[
        tuple[str, str]
    ],
) -> dict[
    tuple[str, str],
    float,
]:
    """
    Split a dollar pool exactly to the cent.

    Dominant plans have one funded key.

    Equal-weight plans divide whole cents evenly and distribute
    any remaining cents deterministically. This prevents research
    or live-shadow rounding from creating fake leftover capital.
    """
    if not funded_keys:
        return {}

    cents = int(
        round(
            float(pool) * 100.0
        )
    )

    count = len(
        funded_keys
    )

    base = cents // count
    remainder = cents % count

    result = {}

    for index, key in enumerate(
        sorted(
            funded_keys
        )
    ):
        value = (
            base
            + (
                1
                if index < remainder
                else 0
            )
        )

        result[key] = (
            value / 100.0
        )

    return result


def build_dominance_equal_weight_plan(
    opportunities: list[
        RiskAdjustedOpportunity
    ],
    *,
    deployable_pool: float,
    minimum_reward_risk: float = (
        MINIMUM_REWARD_RISK
    ),
    dominance_ratio: float = (
        DOMINANCE_RATIO
    ),
    full_confidence_samples: int = 30,
) -> DominanceEqualPlan:
    """
    Build the researched dominance + equal-weight shadow policy.

    Rules
    -----
    1. Score opportunities using the existing causal V2 score.
    2. Use the effectively-ungated 0.01 R/R research threshold.
    3. If nothing qualifies, retain the pool as cash.
    4. If only one qualifies, fund it fully.
    5. If the best score is >= dominance_ratio times the second,
       fund only the dominant opportunity.
    6. Otherwise equal-weight every eligible opportunity.

    Score magnitude NEVER controls position size in the
    non-dominant case.

    This is SHADOW ONLY.
    """
    pool = round(
        max(
            0.0,
            float(
                deployable_pool
            ),
        ),
        2,
    )

    if dominance_ratio <= 1:
        raise ValueError(
            "dominance_ratio must be greater than 1."
        )

    scores = [
        score_risk_adjusted_opportunity(
            opportunity,
            minimum_reward_risk=(
                minimum_reward_risk
            ),
            full_confidence_samples=(
                full_confidence_samples
            ),
        )
        for opportunity
        in opportunities
    ]

    eligible = [
        score
        for score in scores
        if score.eligible
    ]

    weights: dict[
        tuple[str, str],
        float,
    ] = {}

    decision_reason = (
        "NO_CANDIDATES"
    )

    best_symbol = None
    best_strategy = None

    if not scores:
        decision_reason = (
            "NO_CANDIDATES"
        )

    elif not eligible:
        decision_reason = (
            "NO_ELIGIBLE_OPPORTUNITIES"
        )

    elif len(eligible) == 1:
        only = eligible[0]

        best_symbol = only.symbol
        best_strategy = only.strategy

        weights[
            (
                only.symbol,
                only.strategy,
            )
        ] = 1.0

        decision_reason = (
            "SINGLE_ELIGIBLE_OPPORTUNITY"
        )

    else:
        ranked = sorted(
            eligible,
            key=lambda item: (
                -item.raw_score,
                item.symbol,
                item.strategy,
            ),
        )

        top = ranked[0]
        second = ranked[1]

        best_symbol = top.symbol
        best_strategy = top.strategy

        is_dominant = (
            second.raw_score <= 0
            or (
                top.raw_score
                / second.raw_score
            )
            >= dominance_ratio
        )

        if is_dominant:
            weights[
                (
                    top.symbol,
                    top.strategy,
                )
            ] = 1.0

            decision_reason = (
                "DOMINANT_OPPORTUNITY"
            )

        else:
            equal_weight = (
                1.0 / len(eligible)
            )

            for score in eligible:
                weights[
                    (
                        score.symbol,
                        score.strategy,
                    )
                ] = equal_weight

            decision_reason = (
                "EQUAL_WEIGHT_PORTFOLIO"
            )

    funded_keys = [
        key
        for key, weight
        in weights.items()
        if weight > 0
    ]

    dollar_allocations = (
        _cent_allocations(
            pool=pool,
            funded_keys=funded_keys,
        )
    )

    allocations = tuple(
        DominanceEqualAllocation(
            symbol=score.symbol,
            strategy=score.strategy,
            score=score.raw_score,
            reward_risk=(
                score.reward_risk
            ),
            allocation_weight=round(
                weights.get(
                    (
                        score.symbol,
                        score.strategy,
                    ),
                    0.0,
                ),
                8,
            ),
            recommended_allocation=(
                dollar_allocations.get(
                    (
                        score.symbol,
                        score.strategy,
                    ),
                    0.0,
                )
            ),
            eligible=score.eligible,
            rejection_reason=(
                score.rejection_reason
            ),
        )
        for score in scores
    )

    funded = any(
        item.allocation_weight > 0
        for item in allocations
    )

    cash_retained = (
        0.0
        if funded
        else pool
    )

    return DominanceEqualPlan(
        deployable_pool=pool,
        minimum_reward_risk=round(
            float(
                minimum_reward_risk
            ),
            6,
        ),
        dominance_ratio=round(
            float(
                dominance_ratio
            ),
            6,
        ),
        decision_reason=(
            decision_reason
        ),
        best_symbol=best_symbol,
        best_strategy=best_strategy,
        allocations=allocations,
        cash_retained=(
            cash_retained
        ),
    )


def dominance_equal_plan_to_dict(
    plan: DominanceEqualPlan,
) -> dict:
    return {
        "method": plan.method,
        "shadowOnly": True,
        "deployablePool": (
            plan.deployable_pool
        ),
        "minimumRewardRisk": (
            plan.minimum_reward_risk
        ),
        "dominanceRatio": (
            plan.dominance_ratio
        ),
        "decisionReason": (
            plan.decision_reason
        ),
        "bestSymbol": (
            plan.best_symbol
        ),
        "bestStrategy": (
            plan.best_strategy
        ),
        "cashRetained": (
            plan.cash_retained
        ),
        "allocations": [
            {
                "symbol": item.symbol,
                "strategy": (
                    item.strategy
                ),
                "score": item.score,
                "rewardRisk": (
                    item.reward_risk
                ),
                "allocationWeight": (
                    item.allocation_weight
                ),
                "recommendedAllocation": (
                    item.recommended_allocation
                ),
                "eligible": (
                    item.eligible
                ),
                "rejectionReason": (
                    item.rejection_reason
                ),
            }
            for item
            in plan.allocations
        ],
    }
