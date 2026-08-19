import pytest

from trading_bot.risk_adjusted_allocator import (
    RiskAdjustedOpportunity,
)
from trading_bot.risk_adjusted_live_shadow import (
    build_causal_dominance_equal_weight_shadow,
)
from trading_bot.risk_adjusted_shadow_report import (
    build_daily_shadow_allocation_report,
    fractional_quantity_for_shadow_allocation,
    shadow_report_to_dict,
)


def test_fractional_quantity_is_dollars_over_entry():
    assert (
        fractional_quantity_for_shadow_allocation(
            allocation=13.95,
            entry_price=18.37,
        )
        == pytest.approx(
            0.75939031,
            abs=0.00000001,
        )
    )


def test_zero_allocation_has_zero_fractional_quantity():
    assert (
        fractional_quantity_for_shadow_allocation(
            allocation=0.0,
            entry_price=18.37,
        )
        == 0.0
    )


def test_v2_report_serializes_fractional_quantity():
    opportunity = RiskAdjustedOpportunity(
        symbol="SOFI",
        strategy="MANIPULATION",
        expected_reward_pct=2.0,
        expected_risk_pct=1.0,
        entry_price=20.0,
    )

    report = (
        build_daily_shadow_allocation_report(
            trading_date="2026-08-17",
            model="v1",
            opportunities=[
                opportunity,
            ],
            deployable_pool=100.0,
        )
    )

    payload = shadow_report_to_dict(
        report
    )

    comparison = payload[
        "comparisons"
    ][0]

    assert (
        payload[
            "fractionalSizingResearch"
        ]
        is True
    )

    assert (
        comparison[
            "entryPrice"
        ]
        == 20.0
    )

    assert (
        comparison[
            "equalFractionalQuantity"
        ]
        == 5.0
    )

    assert (
        comparison[
            "riskAdjustedFractionalQuantity"
        ]
        == 5.0
    )


def test_v1_causal_shadow_serializes_fractional_quantity():
    opportunity = RiskAdjustedOpportunity(
        symbol="BBAI",
        strategy="MANIPULATION",
        expected_reward_pct=2.0,
        expected_risk_pct=1.0,
        entry_price=4.0,
    )

    payload = (
        build_causal_dominance_equal_weight_shadow(
            opportunities=[
                opportunity,
            ],
            quick_flip_results={},
            quick_flip_previews=[],
            deployable_pool=10.0,
            production_allocations={},
        )
    )

    assert (
        payload[
            "fractionalSizingResearch"
        ]
        is True
    )

    allocation = (
        payload[
            "events"
        ][0][
            "allocations"
        ][0]
    )

    assert (
        allocation[
            "entryPrice"
        ]
        == 4.0
    )

    assert (
        allocation[
            "fractionalQuantity"
        ]
        == 2.5
    )
