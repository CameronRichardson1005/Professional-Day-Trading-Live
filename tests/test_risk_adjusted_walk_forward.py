from trading_bot.risk_adjusted_walk_forward import (
    SEPARATE_SIGNALS,
    SYMBOL_DEDUPED_CAUSAL,
    performance_before_date,
    production_rows,
    run_walk_forward,
)


CORE = {
    "CORE",
}


def row(
    date,
    symbol,
    *,
    selected="",
    clean="YES",
    manip_signal="NO INVEST",
    manip_entry="",
    manip_target="",
    manip_stop="",
    manip_filled="",
    manip_return="",
    qf_signal="NO INVEST",
    qf_entry="",
    qf_tp1="",
    qf_tp2="",
    qf_filled="",
    qf_return="",
    qf_mfe="",
    qf_mae="",
    qf_confirmation="",
):
    return {
        "date": date,
        "symbol": symbol,
        "v1_selected": selected,
        "post_opening_outcome_clean": clean,

        "manipulation_signal": manip_signal,
        "manipulation_entry": manip_entry,
        "manipulation_target": manip_target,
        "manipulation_trading_stop": manip_stop,
        "manipulation_filled": manip_filled,
        "manipulation_outcome": (
            "TARGET"
            if manip_filled == "YES"
            and float(
                manip_return or 0
            ) > 0
            else (
                "STOP"
                if manip_filled == "YES"
                else ""
            )
        ),
        "manipulation_return_pct": manip_return,

        "quick_flip_signal": qf_signal,
        "quick_flip_entry": qf_entry,
        "quick_flip_tp1": qf_tp1,
        "quick_flip_tp2": qf_tp2,
        "quick_flip_filled": qf_filled,
        "quick_flip_endpoint_return_pct": qf_return,
        "quick_flip_mfe_pct": qf_mfe,
        "quick_flip_mae_pct": qf_mae,
        "quick_flip_confirmation_time": qf_confirmation,
        "quick_flip_tp1_hit": "",
        "quick_flip_tp2_hit": "",
    }


def test_production_rows_include_core_and_v1_selected():
    rows = [
        row(
            "2026-03-02",
            "CORE",
        ),
        row(
            "2026-03-02",
            "CANDIDATE",
            selected="YES",
        ),
        row(
            "2026-03-02",
            "OTHER",
            selected="NO",
        ),
    ]

    result = production_rows(
        rows,
        permanent_symbols=CORE,
    )

    assert {
        item["symbol"]
        for item
        in result
    } == {
        "CORE",
        "CANDIDATE",
    }


def test_performance_context_never_uses_current_day():
    rows = [
        row(
            "2026-03-02",
            "CORE",
            manip_signal="INVEST",
            manip_entry="10",
            manip_target="11",
            manip_stop="9",
            manip_filled="YES",
            manip_return="2",
        ),
        row(
            "2026-03-03",
            "CORE",
            manip_signal="INVEST",
            manip_entry="10",
            manip_target="11",
            manip_stop="9",
            manip_filled="YES",
            manip_return="-5",
        ),
    ]

    summary = performance_before_date(
        production_history=rows,
        trading_date="2026-03-03",
        strategy="MANIPULATION",
    )

    assert summary.filled_trades == 1
    assert (
        summary.expectancy_per_filled_trade_pct
        == 2.0
    )


def test_zero_reserve_matches_manipulation_first_sequence():
    rows = [
        row(
            "2026-03-02",
            "CORE",
            qf_signal="INVEST",
            qf_entry="10",
            qf_tp1="11",
            qf_tp2="12",
            qf_filled="YES",
            qf_return="2",
            qf_mfe="4",
            qf_mae="-1",
            qf_confirmation=(
                "2026-03-02T15:00:00+00:00"
            ),
        ),
        row(
            "2026-03-03",
            "CORE",
            manip_signal="INVEST",
            manip_entry="10",
            manip_target="12",
            manip_stop="9",
            manip_filled="YES",
            manip_return="1",
            qf_signal="INVEST",
            qf_entry="10",
            qf_tp1="11",
            qf_tp2="13",
            qf_filled="YES",
            qf_return="5",
            qf_mfe="5",
            qf_mae="-1",
            qf_confirmation=(
                "2026-03-03T15:00:00+00:00"
            ),
        ),
    ]

    result = run_walk_forward(
        rows=rows,
        permanent_symbols=CORE,
        portfolio_mode=(
            SEPARATE_SIGNALS
        ),
        quick_flip_reserve_fraction=0,
    )

    day = result.days[1]

    assert day.manipulation_signals == 1
    assert day.quick_flip_signals == 1

    # Manipulation has 2R geometry and receives the full pool.
    assert day.v2_allocated == 1.0
    assert day.v2_cash_retained == 0.0

    assert len(
        day.allocations
    ) == 1

    assert (
        day.allocations[0].strategy
        == "MANIPULATION"
    )


def test_qf_reserve_keeps_capital_for_later_signal():
    rows = [
        row(
            "2026-03-02",
            "CORE",
            qf_signal="INVEST",
            qf_entry="10",
            qf_tp1="11",
            qf_tp2="12",
            qf_filled="YES",
            qf_return="3",
            qf_mfe="4",
            qf_mae="-1",
            qf_confirmation=(
                "2026-03-02T15:00:00+00:00"
            ),
        ),
        row(
            "2026-03-03",
            "CORE",
            manip_signal="INVEST",
            manip_entry="10",
            manip_target="12",
            manip_stop="9",
            manip_filled="YES",
            manip_return="1",
            qf_signal="INVEST",
            qf_entry="10",
            qf_tp1="11",
            qf_tp2="13",
            qf_filled="YES",
            qf_return="5",
            qf_mfe="5",
            qf_mae="-1",
            qf_confirmation=(
                "2026-03-03T15:00:00+00:00"
            ),
        ),
    ]

    result = run_walk_forward(
        rows=rows,
        permanent_symbols=CORE,
        portfolio_mode=(
            SEPARATE_SIGNALS
        ),
        quick_flip_reserve_fraction=0.25,
    )

    day = result.days[1]

    strategies = {
        item.strategy:
        item.allocation
        for item
        in day.allocations
    }

    assert strategies[
        "MANIPULATION"
    ] == 0.75

    assert strategies[
        "QUICK_FLIP"
    ] == 0.25

    assert day.v2_cash_retained == 0.0


def test_symbol_deduped_blocks_later_same_symbol_qf():
    rows = [
        row(
            "2026-03-02",
            "CORE",
            qf_signal="INVEST",
            qf_entry="10",
            qf_tp1="11",
            qf_tp2="12",
            qf_filled="YES",
            qf_return="3",
            qf_mfe="4",
            qf_mae="-1",
            qf_confirmation=(
                "2026-03-02T15:00:00+00:00"
            ),
        ),
        row(
            "2026-03-03",
            "CORE",
            manip_signal="INVEST",
            manip_entry="10",
            manip_target="12",
            manip_stop="9",
            manip_filled="YES",
            manip_return="1",
            qf_signal="INVEST",
            qf_entry="10",
            qf_tp1="11",
            qf_tp2="13",
            qf_filled="YES",
            qf_return="5",
            qf_mfe="5",
            qf_mae="-1",
            qf_confirmation=(
                "2026-03-03T15:00:00+00:00"
            ),
        ),
    ]

    result = run_walk_forward(
        rows=rows,
        permanent_symbols=CORE,
        portfolio_mode=(
            SYMBOL_DEDUPED_CAUSAL
        ),
        quick_flip_reserve_fraction=0.25,
    )

    day = result.days[1]

    assert len(
        day.allocations
    ) == 1

    assert (
        day.allocations[0].strategy
        == "MANIPULATION"
    )

    assert (
        day.symbol_deduped_count
        == 1
    )

    assert (
        day.v2_cash_retained
        == 0.25
    )
