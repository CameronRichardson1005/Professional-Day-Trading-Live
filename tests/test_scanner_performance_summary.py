from trading_bot.scanner_performance_summary import (
    summarize,
)


def base_row(
    *,
    date,
    selected="YES",
    rank="1",
    manipulation_signal="NO INVEST",
    manipulation_filled="",
    manipulation_outcome="",
    manipulation_return="",
    quick_flip_signal="NO INVEST",
    quick_flip_filled="",
    quick_flip_return="",
    tp1="",
    tp2="",
    clean="YES",
):
    return {
        "date": date,

        "v1_selected": selected,
        "v1_rank": rank,

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
        "quick_flip_mfe_pct": "",
        "quick_flip_mae_pct": "",
    }


def test_manipulation_selection_expectancy_includes_zero_nontrades():
    rows = [
        base_row(
            date="2026-03-02",
            manipulation_signal="INVEST",
            manipulation_filled="YES",
            manipulation_outcome="TARGET",
            manipulation_return="2.0",
        ),
        base_row(
            date="2026-03-02",
        ),
    ]

    result = summarize(
        rows=rows,
        model="v1",
        strategy="MANIPULATION",
    )

    assert (
        result.selected_observations
        == 2
    )

    assert result.strategy_signals == 1
    assert result.filled_trades == 1

    assert (
        result.expectancy_per_selection_pct
        == 1.0
    )

    assert (
        result.expectancy_per_signal_pct
        == 2.0
    )

    assert result.target_hits == 1


def test_quick_flip_hit_rates():
    rows = [
        base_row(
            date="2026-03-02",
            quick_flip_signal="INVEST",
            quick_flip_filled="YES",
            quick_flip_return="3.0",
            tp1="YES",
            tp2="YES",
        ),
        base_row(
            date="2026-03-03",
            quick_flip_signal="INVEST",
            quick_flip_filled="YES",
            quick_flip_return="-1.0",
            tp1="NO",
            tp2="NO",
        ),
    ]

    result = summarize(
        rows=rows,
        model="v1",
        strategy="QUICK_FLIP",
    )

    assert result.filled_trades == 2
    assert result.tp1_hits == 1
    assert result.tp2_hits == 1

    assert (
        result.tp1_hit_rate_pct
        == 50.0
    )

    assert (
        result.tp2_hit_rate_pct
        == 50.0
    )

    assert (
        result.win_rate_pct
        == 50.0
    )


def test_strict_sample_excludes_partial_outcome():
    rows = [
        base_row(
            date="2026-03-02",
            clean="YES",
        ),
        base_row(
            date="2026-03-03",
            clean="NO",
        ),
    ]

    result = summarize(
        rows=rows,
        model="v1",
        strategy="MANIPULATION",
        strict=True,
    )

    assert (
        result.selected_observations
        == 1
    )


def test_rank_filter():
    rows = [
        base_row(
            date="2026-03-02",
            rank="1",
        ),
        base_row(
            date="2026-03-02",
            rank="2",
        ),
    ]

    result = summarize(
        rows=rows,
        model="v1",
        strategy="MANIPULATION",
        rank=1,
    )

    assert (
        result.selected_observations
        == 1
    )
