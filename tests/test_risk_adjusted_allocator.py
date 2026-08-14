import pytest

from trading_bot.risk_adjusted_allocator import (
    RiskAdjustedOpportunity,
    build_shadow_risk_adjusted_plan,
    score_risk_adjusted_opportunity,
)


def opportunity(
    symbol,
    *,
    reward,
    risk,
    strategy="MANIPULATION",
    expectancy=None,
    win_rate=None,
    samples=None,
    setup_quality=1.0,
    liquidity_quality=1.0,
):
    return RiskAdjustedOpportunity(
        symbol=symbol,
        strategy=strategy,
        expected_reward_pct=reward,
        expected_risk_pct=risk,
        expectancy_pct=expectancy,
        win_rate_pct=win_rate,
        historical_samples=samples,
        setup_quality=setup_quality,
        liquidity_quality=liquidity_quality,
    )


def test_reward_risk_is_primary_measure():
    score = score_risk_adjusted_opportunity(
        opportunity(
            "OPEN",
            reward=6.0,
            risk=2.0,
        )
    )

    assert score.reward_risk == 3.0
    assert score.raw_score == 3.0
    assert score.eligible is True


def test_same_reward_lower_risk_scores_higher():
    lower_risk = (
        score_risk_adjusted_opportunity(
            opportunity(
                "LOW",
                reward=5.0,
                risk=1.0,
            )
        )
    )

    higher_risk = (
        score_risk_adjusted_opportunity(
            opportunity(
                "HIGH",
                reward=5.0,
                risk=2.5,
            )
        )
    )

    assert (
        lower_risk.raw_score
        > higher_risk.raw_score
    )


def test_below_minimum_reward_risk_is_rejected():
    score = score_risk_adjusted_opportunity(
        opportunity(
            "WEAK",
            reward=2.0,
            risk=2.0,
        ),
        minimum_reward_risk=1.25,
    )

    assert score.eligible is False
    assert (
        score.rejection_reason
        == "REWARD_RISK_BELOW_MINIMUM"
    )


def test_small_history_has_limited_influence():
    small = score_risk_adjusted_opportunity(
        opportunity(
            "SMALL",
            reward=4.0,
            risk=2.0,
            expectancy=2.0,
            win_rate=80.0,
            samples=3,
        )
    )

    full = score_risk_adjusted_opportunity(
        opportunity(
            "FULL",
            reward=4.0,
            risk=2.0,
            expectancy=2.0,
            win_rate=80.0,
            samples=30,
        )
    )

    assert small.history_confidence == 0.1
    assert full.history_confidence == 1.0
    assert full.raw_score > small.raw_score


def test_dominant_stock_can_receive_entire_pool():
    plan = build_shadow_risk_adjusted_plan(
        [
            opportunity(
                "BEST",
                reward=8.0,
                risk=1.0,
            ),
            opportunity(
                "SECOND",
                reward=3.0,
                risk=2.0,
            ),
            opportunity(
                "THIRD",
                reward=2.0,
                risk=2.0,
            ),
        ],
        deployable_pool=9000.0,
        dominance_ratio=1.75,
    )

    by_symbol = {
        item.symbol: item
        for item in plan.allocations
    }

    assert (
        by_symbol["BEST"]
        .allocation_weight
        == 1.0
    )
    assert (
        by_symbol["BEST"]
        .recommended_allocation
        == 9000.0
    )
    assert (
        by_symbol["SECOND"]
        .recommended_allocation
        == 0.0
    )
    assert (
        by_symbol["THIRD"]
        .recommended_allocation
        == 0.0
    )
    assert plan.cash_retained == 0.0


def test_non_dominant_candidates_are_not_equal_weighted():
    plan = build_shadow_risk_adjusted_plan(
        [
            opportunity(
                "A",
                reward=5.0,
                risk=2.0,
            ),
            opportunity(
                "B",
                reward=4.0,
                risk=2.0,
            ),
            opportunity(
                "C",
                reward=3.0,
                risk=2.0,
            ),
        ],
        deployable_pool=9000.0,
        dominance_ratio=10.0,
    )

    by_symbol = {
        item.symbol: item
        for item in plan.allocations
    }

    assert (
        by_symbol["A"]
        .recommended_allocation
        > by_symbol["B"]
        .recommended_allocation
        > by_symbol["C"]
        .recommended_allocation
    )

    assert sum(
        item.allocation_weight
        for item in plan.allocations
    ) == pytest.approx(
        1.0,
        abs=0.000002,
    )


def test_trade_nothing_when_nothing_is_attractive():
    plan = build_shadow_risk_adjusted_plan(
        [
            opportunity(
                "A",
                reward=1.0,
                risk=2.0,
            ),
            opportunity(
                "B",
                reward=2.0,
                risk=2.0,
            ),
        ],
        deployable_pool=5000.0,
        minimum_reward_risk=1.25,
    )

    assert all(
        item.recommended_allocation == 0
        for item in plan.allocations
    )

    assert plan.cash_retained == 5000.0


def test_quick_flip_can_use_empirical_mae_as_risk():
    score = score_risk_adjusted_opportunity(
        opportunity(
            "QF",
            strategy="QUICK_FLIP",
            reward=5.5,
            risk=1.8,
            expectancy=1.2,
            win_rate=62.0,
            samples=30,
        )
    )

    assert score.reward_risk == pytest.approx(
        3.055556,
        abs=0.000001,
    )
    assert score.eligible is True


def test_zero_or_negative_risk_is_invalid():
    with pytest.raises(
        ValueError,
        match="expected_risk_pct",
    ):
        score_risk_adjusted_opportunity(
            opportunity(
                "BAD",
                reward=4.0,
                risk=0.0,
            )
        )


def test_plan_is_explicitly_shadow_only():
    plan = build_shadow_risk_adjusted_plan(
        [
            opportunity(
                "OPEN",
                reward=4.0,
                risk=2.0,
            )
        ],
        deployable_pool=1000.0,
    )

    assert plan.shadow_only is True
    assert (
        plan.method
        == "RISK_ADJUSTED_SHADOW_V1"
    )
