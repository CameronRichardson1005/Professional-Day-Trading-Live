from trading_bot.fibonacci_paper_evaluation import (
    build_fibonacci_paper_evaluation,
)
from trading_bot.webull_paper_analytics import (
    WebullPaperAnalyticsGroup,
    WebullPaperAnalyticsReport,
)


def group(
    *,
    key,
    closed,
    expectancy,
):
    return WebullPaperAnalyticsGroup(
        key=key,
        approved_orders=closed,
        entered_trades=closed,
        closed_trades=closed,
        no_entry=0,
        wins=closed if expectancy > 0 else 0,
        losses=closed if expectancy < 0 else 0,
        breakeven=closed if expectancy == 0 else 0,
        target_exits=closed if expectancy > 0 else 0,
        stop_exits=closed if expectancy < 0 else 0,
        time_exits=closed if expectancy == 0 else 0,
        win_rate_pct=(
            100.0
            if expectancy > 0
            else 0.0
        ),
        realized_pnl=expectancy * closed,
        average_pnl_per_trade=expectancy,
        average_return_pct=expectancy,
        expectancy_per_trade=expectancy,
        average_mfe_pct=2.0,
        average_mae_pct=-1.0,
        sample_label=(
            "NO CLOSED SAMPLE"
            if closed == 0
            else "SMALL SAMPLE"
        ),
    )


def report(
    *,
    closed,
    groups=(),
):
    return WebullPaperAnalyticsReport(
        total_orders=closed,
        entered_trades=closed,
        closed_trades=closed,
        open_trades=0,
        no_entry=0,
        realized_pnl=0.0,
        win_rate_pct=None,
        average_return_pct=None,
        expectancy_per_trade=None,
        by_symbol=groups,
        by_entry_time=(),
        by_reward_risk=(),
        by_impulse_atr=(),
        by_pullback_volume=(),
        by_confirmation_time=(),
    )


def test_no_data_does_not_rank_cohorts():
    evaluation = build_fibonacci_paper_evaluation(
        analytics=report(
            closed=0,
        )
    )

    assert evaluation.evidence_status == "NO DATA"
    assert evaluation.strongest_cohort is None
    assert evaluation.weakest_cohort is None
    assert (
        evaluation.parameter_changes_allowed
        is False
    )


def test_very_small_groups_are_not_ranked():
    evaluation = build_fibonacci_paper_evaluation(
        analytics=report(
            closed=4,
            groups=(
                group(
                    key="OPEN",
                    closed=4,
                    expectancy=5.0,
                ),
            ),
        )
    )

    assert evaluation.evidence_status == (
        "VERY EARLY"
    )
    assert evaluation.strongest_cohort is None


def test_groups_require_five_closed_trades():
    evaluation = build_fibonacci_paper_evaluation(
        analytics=report(
            closed=10,
            groups=(
                group(
                    key="OPEN",
                    closed=5,
                    expectancy=2.0,
                ),
                group(
                    key="SOUN",
                    closed=5,
                    expectancy=-1.0,
                ),
            ),
        )
    )

    assert evaluation.evidence_status == "EARLY"

    assert evaluation.strongest_cohort is not None
    assert evaluation.strongest_cohort.key == "OPEN"

    assert evaluation.weakest_cohort is not None
    assert evaluation.weakest_cohort.key == "SOUN"


def test_fifty_closed_trades_are_reviewable():
    evaluation = build_fibonacci_paper_evaluation(
        analytics=report(
            closed=50,
        )
    )

    assert evaluation.evidence_status == (
        "REVIEWABLE"
    )
    assert (
        evaluation.parameter_changes_allowed
        is False
    )
