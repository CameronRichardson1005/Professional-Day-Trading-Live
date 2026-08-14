from trading_bot.risk_adjusted_allocator import (
    RiskAdjustedOpportunity,
)
from trading_bot.risk_adjusted_dominance_shadow import (
    build_dominance_equal_weight_plan,
)


def opportunity(
    symbol,
    reward,
    risk=1.0,
):
    return RiskAdjustedOpportunity(
        symbol=symbol,
        strategy="MANIPULATION",
        expected_reward_pct=reward,
        expected_risk_pct=risk,
    )


def test_non_dominant_candidates_are_equal_weighted():
    plan = (
        build_dominance_equal_weight_plan(
            [
                opportunity(
                    "A",
                    2.0,
                ),
                opportunity(
                    "B",
                    1.5,
                ),
            ],
            deployable_pool=10000.0,
        )
    )

    assert (
        plan.decision_reason
        == "EQUAL_WEIGHT_PORTFOLIO"
    )

    funded = [
        item
        for item in plan.allocations
        if item.allocation_weight > 0
    ]

    assert len(funded) == 2

    assert {
        item.allocation_weight
        for item in funded
    } == {
        0.5,
    }

    assert {
        item.recommended_allocation
        for item in funded
    } == {
        5000.0,
    }


def test_dominant_candidate_receives_full_pool():
    plan = (
        build_dominance_equal_weight_plan(
            [
                opportunity(
                    "A",
                    3.0,
                ),
                opportunity(
                    "B",
                    1.0,
                ),
            ],
            deployable_pool=9000.0,
        )
    )

    assert (
        plan.decision_reason
        == "DOMINANT_OPPORTUNITY"
    )

    funded = [
        item
        for item in plan.allocations
        if item.allocation_weight > 0
    ]

    assert len(funded) == 1
    assert funded[0].symbol == "A"
    assert funded[0].allocation_weight == 1.0

    assert (
        funded[0].recommended_allocation
        == 9000.0
    )

    assert plan.cash_retained == 0.0


def test_policy_does_not_use_old_1_25_rr_gate():
    plan = (
        build_dominance_equal_weight_plan(
            [
                opportunity(
                    "A",
                    0.50,
                ),
                opportunity(
                    "B",
                    0.40,
                ),
            ],
            deployable_pool=1000.0,
        )
    )

    assert all(
        item.eligible
        for item
        in plan.allocations
    )

    assert (
        plan.decision_reason
        == "EQUAL_WEIGHT_PORTFOLIO"
    )

    assert sum(
        item.recommended_allocation
        for item
        in plan.allocations
    ) == 1000.0


def test_equal_weight_split_conserves_every_cent():
    plan = (
        build_dominance_equal_weight_plan(
            [
                opportunity(
                    "A",
                    1.00,
                ),
                opportunity(
                    "B",
                    0.90,
                ),
                opportunity(
                    "C",
                    0.80,
                ),
            ],
            deployable_pool=100.0,
        )
    )

    assert (
        plan.decision_reason
        == "EQUAL_WEIGHT_PORTFOLIO"
    )

    values = sorted(
        item.recommended_allocation
        for item
        in plan.allocations
    )

    assert values == [
        33.33,
        33.33,
        33.34,
    ]

    assert round(
        sum(values),
        2,
    ) == 100.0

    assert plan.cash_retained == 0.0


def test_no_candidates_retains_cash():
    plan = (
        build_dominance_equal_weight_plan(
            [],
            deployable_pool=5000.0,
        )
    )

    assert (
        plan.decision_reason
        == "NO_CANDIDATES"
    )

    assert plan.cash_retained == 5000.0
    assert plan.allocations == ()
