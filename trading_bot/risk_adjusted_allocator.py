from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RiskAdjustedOpportunity:
    """
    One candidate supplied to the V2 shadow allocator.

    expected_reward_pct:
        Realistic expected upside from entry, in percent.

    expected_risk_pct:
        Realistic downside risk, in percent.

        Manipulation can use entry-to-trading-stop risk.

        Quick Flip intentionally has no automatic stop loss, so
        its adapter should eventually use historical adverse
        excursion (MAE), not an invented stop.

    expectancy_pct / win_rate_pct:
        Optional historical evidence. These are sample-size
        adjusted so a small history cannot dominate the ranking.

    setup_quality / liquidity_quality:
        Multipliers in [0, 1]. They default to neutral/full
        quality and can be populated by later adapters.
    """

    symbol: str
    strategy: str

    expected_reward_pct: float
    expected_risk_pct: float

    expectancy_pct: float | None = None
    win_rate_pct: float | None = None
    historical_samples: int | None = None

    setup_quality: float = 1.0
    liquidity_quality: float = 1.0

    # Intended strategy entry used only for shadow/research
    # execution sizing. It does not influence scoring.
    entry_price: float | None = None


@dataclass(frozen=True)
class RiskAdjustedScore:
    symbol: str
    strategy: str

    expected_reward_pct: float
    expected_risk_pct: float
    reward_risk: float

    expectancy_pct: float | None
    win_rate_pct: float | None
    historical_samples: int | None
    history_confidence: float

    expectancy_multiplier: float
    win_rate_multiplier: float
    setup_quality: float
    liquidity_quality: float

    raw_score: float
    eligible: bool
    rejection_reason: str | None


@dataclass(frozen=True)
class ShadowCapitalAllocation:
    symbol: str
    strategy: str
    score: float
    reward_risk: float
    allocation_weight: float
    recommended_allocation: float
    eligible: bool
    rejection_reason: str | None


@dataclass(frozen=True)
class ShadowRiskAdjustedPlan:
    deployable_pool: float
    minimum_reward_risk: float
    dominance_ratio: float
    concentration_power: float

    allocations: tuple[ShadowCapitalAllocation, ...]
    cash_retained: float

    method: str = "RISK_ADJUSTED_SHADOW_V1"
    shadow_only: bool = True


def _validate_quality(
    name: str,
    value: float,
) -> float:
    value = float(value)

    if not 0 <= value <= 1:
        raise ValueError(
            f"{name} must be between 0 and 1."
        )

    return value


def _history_confidence(
    historical_samples: int | None,
    *,
    full_confidence_samples: int = 30,
) -> float:
    """
    Shrink historical evidence toward neutral until enough
    observations exist.

    0 samples  -> 0 historical influence
    15 samples -> 50% historical influence
    30+        -> full historical influence
    """
    if historical_samples is None:
        return 0.0

    if historical_samples < 0:
        raise ValueError(
            "historical_samples cannot be negative."
        )

    if full_confidence_samples <= 0:
        raise ValueError(
            "full_confidence_samples must be positive."
        )

    return min(
        1.0,
        historical_samples
        / float(full_confidence_samples),
    )


def score_risk_adjusted_opportunity(
    opportunity: RiskAdjustedOpportunity,
    *,
    minimum_reward_risk: float = 1.25,
    full_confidence_samples: int = 30,
) -> RiskAdjustedScore:
    """
    Score one day-trading opportunity.

    Reward/risk is deliberately the core of the score.

    Historical expectancy and win rate modify that score only in
    proportion to the amount of history available.

    This function does not allocate capital or submit orders.
    """
    reward = float(
        opportunity.expected_reward_pct
    )
    risk = float(
        opportunity.expected_risk_pct
    )

    if reward < 0:
        raise ValueError(
            "expected_reward_pct cannot be negative."
        )

    if risk <= 0:
        raise ValueError(
            "expected_risk_pct must be positive."
        )

    if minimum_reward_risk <= 0:
        raise ValueError(
            "minimum_reward_risk must be positive."
        )

    setup_quality = _validate_quality(
        "setup_quality",
        opportunity.setup_quality,
    )
    liquidity_quality = _validate_quality(
        "liquidity_quality",
        opportunity.liquidity_quality,
    )

    if (
        opportunity.win_rate_pct is not None
        and not 0
        <= float(opportunity.win_rate_pct)
        <= 100
    ):
        raise ValueError(
            "win_rate_pct must be between 0 and 100."
        )

    confidence = _history_confidence(
        opportunity.historical_samples,
        full_confidence_samples=(
            full_confidence_samples
        ),
    )

    reward_risk = reward / risk

    # Positive historical expectancy can increase the score;
    # negative expectancy can reduce it. The impact is capped
    # and shrunk toward neutral when the sample is small.
    expectancy_multiplier = 1.0

    if opportunity.expectancy_pct is not None:
        expectancy_to_risk = (
            float(opportunity.expectancy_pct)
            / risk
        )

        expectancy_effect = max(
            -1.0,
            min(
                1.0,
                expectancy_to_risk,
            ),
        )

        expectancy_multiplier = (
            1.0
            + confidence
            * expectancy_effect
        )

    # 50% win rate is neutral.
    #
    # 0% win rate would imply a 0.5 multiplier at full
    # confidence, while 100% would imply 1.5.
    win_rate_multiplier = 1.0

    if opportunity.win_rate_pct is not None:
        observed_win_multiplier = (
            0.5
            + float(opportunity.win_rate_pct)
            / 100.0
        )

        win_rate_multiplier = (
            1.0
            + confidence
            * (
                observed_win_multiplier
                - 1.0
            )
        )

    raw_score = (
        reward_risk
        * expectancy_multiplier
        * win_rate_multiplier
        * setup_quality
        * liquidity_quality
    )

    rejection_reason = None

    if reward_risk < minimum_reward_risk:
        rejection_reason = (
            "REWARD_RISK_BELOW_MINIMUM"
        )
    elif raw_score <= 0:
        rejection_reason = (
            "NON_POSITIVE_RISK_ADJUSTED_SCORE"
        )
    elif setup_quality <= 0:
        rejection_reason = (
            "ZERO_SETUP_QUALITY"
        )
    elif liquidity_quality <= 0:
        rejection_reason = (
            "ZERO_LIQUIDITY_QUALITY"
        )

    return RiskAdjustedScore(
        symbol=opportunity.symbol,
        strategy=opportunity.strategy,
        expected_reward_pct=round(
            reward,
            6,
        ),
        expected_risk_pct=round(
            risk,
            6,
        ),
        reward_risk=round(
            reward_risk,
            6,
        ),
        expectancy_pct=(
            None
            if opportunity.expectancy_pct is None
            else round(
                float(
                    opportunity.expectancy_pct
                ),
                6,
            )
        ),
        win_rate_pct=(
            None
            if opportunity.win_rate_pct is None
            else round(
                float(
                    opportunity.win_rate_pct
                ),
                6,
            )
        ),
        historical_samples=(
            opportunity.historical_samples
        ),
        history_confidence=round(
            confidence,
            6,
        ),
        expectancy_multiplier=round(
            expectancy_multiplier,
            6,
        ),
        win_rate_multiplier=round(
            win_rate_multiplier,
            6,
        ),
        setup_quality=round(
            setup_quality,
            6,
        ),
        liquidity_quality=round(
            liquidity_quality,
            6,
        ),
        raw_score=round(
            raw_score,
            8,
        ),
        eligible=(
            rejection_reason is None
        ),
        rejection_reason=(
            rejection_reason
        ),
    )


def build_shadow_risk_adjusted_plan(
    opportunities: list[
        RiskAdjustedOpportunity
    ],
    *,
    deployable_pool: float,
    minimum_reward_risk: float = 1.25,
    dominance_ratio: float = 1.75,
    concentration_power: float = 2.0,
    full_confidence_samples: int = 30,
) -> ShadowRiskAdjustedPlan:
    """
    Rank day-trading candidates and produce hypothetical capital
    weights.

    IMPORTANT:
    This is SHADOW ONLY. It has no integration with Webull
    preview sizing or order submission.

    Rules
    -----
    1. Candidates below the minimum reward/risk receive 0%.
    2. If no candidate qualifies, retain all capital in cash.
    3. If only one qualifies, it receives 100% of the pool.
    4. If the best score is dominance_ratio times the second-best
       score, the best candidate receives 100% of the pool.
    5. Otherwise scores are raised to concentration_power before
       normalization. This deliberately rewards stronger
       opportunities more than equal weighting.
    """
    pool = max(
        0.0,
        float(deployable_pool),
    )

    if dominance_ratio <= 1:
        raise ValueError(
            "dominance_ratio must be greater than 1."
        )

    if concentration_power <= 0:
        raise ValueError(
            "concentration_power must be positive."
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
        for opportunity in opportunities
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

    if len(eligible) == 1:
        only = eligible[0]
        weights[
            (
                only.symbol,
                only.strategy,
            )
        ] = 1.0

    elif len(eligible) > 1:
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
        else:
            powered = {
                (
                    score.symbol,
                    score.strategy,
                ): (
                    score.raw_score
                    ** concentration_power
                )
                for score in eligible
            }

            total = sum(
                powered.values()
            )

            if total > 0:
                weights = {
                    key: value / total
                    for key, value
                    in powered.items()
                }

    allocations = []

    for score in scores:
        weight = weights.get(
            (
                score.symbol,
                score.strategy,
            ),
            0.0,
        )

        allocations.append(
            ShadowCapitalAllocation(
                symbol=score.symbol,
                strategy=score.strategy,
                score=score.raw_score,
                reward_risk=(
                    score.reward_risk
                ),
                allocation_weight=round(
                    weight,
                    6,
                ),
                recommended_allocation=round(
                    pool * weight,
                    2,
                ),
                eligible=score.eligible,
                rejection_reason=(
                    score.rejection_reason
                ),
            )
        )

    allocated = sum(
        item.recommended_allocation
        for item in allocations
    )

    return ShadowRiskAdjustedPlan(
        deployable_pool=round(
            pool,
            2,
        ),
        minimum_reward_risk=round(
            minimum_reward_risk,
            6,
        ),
        dominance_ratio=round(
            dominance_ratio,
            6,
        ),
        concentration_power=round(
            concentration_power,
            6,
        ),
        allocations=tuple(
            allocations
        ),
        cash_retained=round(
            max(
                0.0,
                pool - allocated,
            ),
            2,
        ),
    )
