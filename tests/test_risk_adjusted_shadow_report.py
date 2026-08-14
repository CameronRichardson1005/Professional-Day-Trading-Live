from trading_bot.risk_adjusted_allocator import (
    RiskAdjustedOpportunity,
)
from trading_bot.risk_adjusted_shadow_report import (
    build_daily_shadow_allocation_report,
    build_strategy_performance_context,
    rows_before_trading_date,
    shadow_report_to_dict,
)


def row(
    *,
    day,
    selected="YES",
    clean="YES",
    manipulation_signal="NO INVEST",
    manipulation_filled="",
    manipulation_outcome="",
    manipulation_return="",
    quick_flip_signal="NO INVEST",
    quick_flip_filled="",
    quick_flip_return="",
    tp1="",
    tp2="",
    mfe="",
    mae="",
):
    return {
        "date": day,
        "v1_selected": selected,
        "v1_rank": "1",
        "post_opening_outcome_clean": (
            clean
        ),
        "manipulation_signal": (
            manipulation_signal
        ),
        "manipulation_filled": (
            manipulation_filled
        ),
        "manipulation_outcome": (
            manipulation_outcome
        ),
        "manipulation_return_pct": (
            manipulation_return
        ),
        "quick_flip_signal": (
            quick_flip_signal
        ),
        "quick_flip_filled": (
            quick_flip_filled
        ),
        "quick_flip_endpoint_return_pct": (
            quick_flip_return
        ),
        "quick_flip_tp1_hit": tp1,
        "quick_flip_tp2_hit": tp2,
        "quick_flip_mfe_pct": mfe,
        "quick_flip_mae_pct": mae,
    }


def opportunity(
    symbol,
    *,
    reward,
    risk,
    strategy="MANIPULATION",
):
    return RiskAdjustedOpportunity(
        symbol=symbol,
        strategy=strategy,
        expected_reward_pct=reward,
        expected_risk_pct=risk,
    )


def test_rows_before_date_prevents_lookahead():
    rows = [
        row(
            day="2026-08-13"
        ),
        row(
            day="2026-08-14"
        ),
        row(
            day="2026-08-15"
        ),
    ]

    historical = (
        rows_before_trading_date(
            rows,
            trading_date="2026-08-14",
        )
    )

    assert [
        item["date"]
        for item in historical
    ] == [
        "2026-08-13"
    ]


def test_performance_context_excludes_current_day():
    rows = [
        row(
            day="2026-08-13",
            manipulation_signal="INVEST",
            manipulation_filled="YES",
            manipulation_outcome="TARGET",
            manipulation_return="2.0",
        ),
        row(
            day="2026-08-14",
            manipulation_signal="INVEST",
            manipulation_filled="YES",
            manipulation_outcome="STOP",
            manipulation_return="-10.0",
        ),
    ]

    context = (
        build_strategy_performance_context(
            rows=rows,
            model="v1",
            trading_date="2026-08-14",
            strict=True,
        )
    )

    assert (
        context.manipulation
        .filled_trades
        == 1
    )

    assert (
        context.manipulation
        .average_return_pct
        == 2.0
    )


def test_quick_flip_history_contains_mfe_mae():
    rows = [
        row(
            day="2026-08-13",
            quick_flip_signal="INVEST",
            quick_flip_filled="YES",
            quick_flip_return="3.0",
            tp1="YES",
            tp2="NO",
            mfe="6.0",
            mae="-1.5",
        )
    ]

    context = (
        build_strategy_performance_context(
            rows=rows,
            model="v1",
            trading_date="2026-08-14",
            strict=True,
        )
    )

    assert (
        context.quick_flip
        .average_mfe_pct
        == 6.0
    )

    assert (
        context.quick_flip
        .average_mae_pct
        == -1.5
    )


def test_report_compares_equal_and_v2_weights():
    report = (
        build_daily_shadow_allocation_report(
            trading_date="2026-08-14",
            model="v1",
            opportunities=[
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
            ],
            deployable_pool=9000.0,
            dominance_ratio=10.0,
        )
    )

    by_symbol = {
        item.symbol: item
        for item in report.comparisons
    }

    assert (
        by_symbol["A"]
        .equal_allocation
        == 4500.0
    )

    assert (
        by_symbol["B"]
        .equal_allocation
        == 4500.0
    )

    assert (
        by_symbol["A"]
        .risk_adjusted_allocation
        > by_symbol["B"]
        .risk_adjusted_allocation
    )

    assert (
        report.decision_reason
        == "SCORE_WEIGHTED_PORTFOLIO"
    )


def test_dominant_opportunity_reason_is_recorded():
    report = (
        build_daily_shadow_allocation_report(
            trading_date="2026-08-14",
            model="v1",
            opportunities=[
                opportunity(
                    "BEST",
                    reward=8.0,
                    risk=1.0,
                ),
                opportunity(
                    "OTHER",
                    reward=3.0,
                    risk=2.0,
                ),
            ],
            deployable_pool=9000.0,
        )
    )

    assert report.best_symbol == "BEST"
    assert (
        report.decision_reason
        == "DOMINANT_OPPORTUNITY"
    )

    best = next(
        item
        for item in report.comparisons
        if item.symbol == "BEST"
    )

    assert (
        best.risk_adjusted_allocation
        == 9000.0
    )


def test_nothing_attractive_keeps_cash():
    report = (
        build_daily_shadow_allocation_report(
            trading_date="2026-08-14",
            model="v1",
            opportunities=[
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
        )
    )

    assert (
        report.decision_reason
        == "NO_ELIGIBLE_OPPORTUNITIES"
    )

    assert (
        report.cash_retained
        == 5000.0
    )


def test_report_serialization_is_shadow_only():
    report = (
        build_daily_shadow_allocation_report(
            trading_date="2026-08-14",
            model="v1",
            opportunities=[
                opportunity(
                    "OPEN",
                    reward=4.0,
                    risk=2.0,
                )
            ],
            deployable_pool=1000.0,
        )
    )

    payload = shadow_report_to_dict(
        report
    )

    assert payload["shadowOnly"] is True
    assert (
        payload["decisionReason"]
        == "SINGLE_ELIGIBLE_OPPORTUNITY"
    )
    assert (
        payload["bestSymbol"]
        == "OPEN"
    )
