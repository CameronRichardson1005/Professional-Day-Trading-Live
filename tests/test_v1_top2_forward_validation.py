from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from trading_bot.scanner import (
    ScannerRules,
    StockScanner,
    StockStats,
)
from trading_bot.scanner_realized_performance import (
    RealizedStrategyObservation,
)
from trading_bot.v1_top2_forward_validation import (
    build_forward_rows,
    compare_top2_top3,
    load_forward_rows,
    write_forward_rows,
)


def stats(
    symbol,
    *,
    range_pct,
):
    return StockStats(
        symbol=symbol,
        valid_bars=30,
        avg_volume=1_000_000,
        avg_price=10.0,
        avg_range=1.0,
        avg_range_pct=range_pct,
    )


def observation(
    symbol,
    *,
    signal="NO INVEST",
    filled=None,
    outcome=None,
    return_pct=None,
    clean=True,
):
    return RealizedStrategyObservation(
        date="2026-08-14",
        symbol=symbol,
        atr_14=1.0,

        opening_open=10.0,
        opening_high=11.0,
        opening_low=9.0,
        opening_close=9.5,

        minute_bars=390,
        missing_minutes=0,
        missing_opening_minutes=0,
        missing_quick_flip_minutes=0,
        missing_post_1100_minutes=0,

        quick_flip_signal_clean=True,
        post_opening_outcome_clean=clean,

        manipulation_signal=signal,
        manipulation_entry=9.0,
        manipulation_target=9.5,
        manipulation_trading_stop=8.75,
        manipulation_filled=filled,
        manipulation_outcome=outcome,
        manipulation_return_pct=return_pct,

        quick_flip_status="NO_LIQUIDITY",
        quick_flip_signal="NO INVEST",
        quick_flip_pattern=None,
        quick_flip_entry=None,
        quick_flip_tp1=None,
        quick_flip_tp2=None,
        quick_flip_filled=None,
        quick_flip_fill_time=None,
        quick_flip_tp1_hit=None,
        quick_flip_tp2_hit=None,
        quick_flip_mfe_pct=None,
        quick_flip_mae_pct=None,
        quick_flip_endpoint_price=None,
        quick_flip_endpoint_return_pct=None,
    )


def scanner():
    return StockScanner(
        current_symbols=[
            "CORE",
        ],
        rules=ScannerRules(
            candidate_limit=3,
        ),
    )


def test_forward_rows_reject_freeze_date():
    with pytest.raises(
        ValueError,
        match="after 2026-08-13",
    ):
        build_forward_rows(
            session=date(
                2026,
                8,
                13,
            ),
            scanner=scanner(),
            statistics=[],
            realized_by_symbol={},
        )


def test_forward_rows_use_existing_v1_scanner_order():
    statistics = [
        stats(
            "THIRD",
            range_pct=5.0,
        ),
        stats(
            "FIRST",
            range_pct=9.0,
        ),
        stats(
            "SECOND",
            range_pct=7.0,
        ),
        stats(
            "FOURTH",
            range_pct=4.5,
        ),
    ]

    realized = {
        symbol: observation(
            symbol
        )
        for symbol in (
            "FIRST",
            "SECOND",
            "THIRD",
        )
    }

    rows = build_forward_rows(
        session=date(
            2026,
            8,
            14,
        ),
        scanner=scanner(),
        statistics=statistics,
        realized_by_symbol=realized,
    )

    assert [
        row.symbol
        for row in rows
    ] == [
        "FIRST",
        "SECOND",
        "THIRD",
    ]

    assert [
        row.rank
        for row in rows
    ] == [
        1,
        2,
        3,
    ]

    assert [
        row.top2_challenger
        for row in rows
    ] == [
        True,
        True,
        False,
    ]

    assert all(
        row.top3_baseline
        for row in rows
    )


def test_forward_ledger_is_idempotent_and_frozen(
    tmp_path,
):
    path = (
        Path(tmp_path)
        / "forward.csv"
    )

    rows = build_forward_rows(
        session=date(
            2026,
            8,
            14,
        ),
        scanner=scanner(),
        statistics=[
            stats(
                "FIRST",
                range_pct=9.0,
            ),
            stats(
                "SECOND",
                range_pct=7.0,
            ),
            stats(
                "THIRD",
                range_pct=5.0,
            ),
        ],
        realized_by_symbol={
            "FIRST": observation(
                "FIRST"
            ),
            "SECOND": observation(
                "SECOND"
            ),
            "THIRD": observation(
                "THIRD"
            ),
        },
    )

    write_forward_rows(
        path=path,
        rows=rows,
    )

    write_forward_rows(
        path=path,
        rows=rows,
    )

    loaded = (
        load_forward_rows(
            path
        )
    )

    assert len(loaded) == 3

    changed = replace(
        rows[0],
        return_pct=1.0,
    )

    with pytest.raises(
        ValueError,
        match="Refusing to rewrite",
    ):
        write_forward_rows(
            path=path,
            rows=[
                changed
            ],
        )


def test_top2_top3_comparison_includes_zero_nontrades():
    rows = build_forward_rows(
        session=date(
            2026,
            8,
            14,
        ),
        scanner=scanner(),
        statistics=[
            stats(
                "FIRST",
                range_pct=9.0,
            ),
            stats(
                "SECOND",
                range_pct=7.0,
            ),
            stats(
                "THIRD",
                range_pct=5.0,
            ),
        ],
        realized_by_symbol={
            "FIRST": observation(
                "FIRST",
                signal="INVEST",
                filled=True,
                outcome="TARGET",
                return_pct=0.6,
            ),
            "SECOND": observation(
                "SECOND",
            ),
            "THIRD": observation(
                "THIRD",
                signal="INVEST",
                filled=True,
                outcome="STOP",
                return_pct=-0.6,
            ),
        },
    )

    comparison = (
        compare_top2_top3(
            rows=rows
        )
    )

    assert (
        comparison
        .top2
        .selections
        == 2
    )

    assert (
        comparison
        .top2
        .expectancy_per_selection_pct
        == pytest.approx(
            0.3
        )
    )

    assert (
        comparison
        .top3
        .expectancy_per_selection_pct
        == pytest.approx(
            0.0
        )
    )

    assert (
        comparison
        .expectancy_difference_pct
        == pytest.approx(
            0.3
        )
    )
