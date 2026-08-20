from trading_bot.scanner import ScannerRules
from trading_bot.scanner import StockScanner
from trading_bot.scanner import StockStats


def make_stats(
        symbol,
        valid_bars=30,
        avg_volume=1_000_000,
        avg_price=10.0,
        avg_range=0.50,
        avg_range_pct=5.0,
):
    return StockStats(
        symbol=symbol,
        valid_bars=valid_bars,
        avg_volume=avg_volume,
        avg_price=avg_price,
        avg_range=avg_range,
        avg_range_pct=avg_range_pct,
    )


def test_scanner_selects_top_three_by_ranking_score():
    scanner = StockScanner(
        current_symbols=["BBAI", "OPEN"],
    )

    statistics = [
        make_stats(
            "AAA",
            avg_volume=1_000_000,
            avg_range_pct=5.0,
        ),
        make_stats(
            "BBB",
            avg_volume=800_000,
            avg_range_pct=8.0,
        ),
        make_stats(
            "CCC",
            avg_volume=1_200_000,
            avg_range_pct=6.0,
        ),
        make_stats(
            "DDD",
            avg_volume=600_000,
            avg_range_pct=10.0,
        ),
    ]

    selected = scanner.select_candidates(statistics)

    assert [
        stats.symbol
        for stats in selected
    ] == [
        "DDD",
        "BBB",
        "CCC",
    ]


def test_scanner_rejects_ineligible_candidates():
    scanner = StockScanner(
        current_symbols=[],
    )

    statistics = [
        make_stats("VALID"),
        make_stats("FEW", valid_bars=19),
        make_stats("CHEAP", avg_price=1.99),
        make_stats("EXPENSIVE", avg_price=30.01),
        make_stats(
            "LOWVOL",
            avg_volume=499_999,
        ),
        make_stats(
            "LOWDOLLAR",
            avg_range=0.19,
        ),
        make_stats(
            "LOWPCT",
            avg_range_pct=3.99,
        ),
    ]

    selected = scanner.select_candidates(statistics)

    assert [
        stats.symbol
        for stats in selected
    ] == [
        "EXPENSIVE",
        "VALID",
    ]


def test_current_symbols_are_always_retained():
    scanner = StockScanner(
        current_symbols=[
            "BBAI",
            "OPEN",
            "BBAI",
        ],
    )

    statistics = [
        make_stats(
            "BBAI",
            valid_bars=1,
            avg_price=100.0,
        ),
        make_stats("SNAP"),
    ]

    assert scanner.select_symbols(statistics) == [
        "BBAI",
        "OPEN",
        "SNAP",
    ]


def test_reliability_filters_core_and_candidates():
    from trading_bot.scanner import OpeningReliability

    scanner = StockScanner(
        current_symbols=["BBAI", "OPEN"],
    )

    statistics = [
        make_stats("SNAP"),
    ]

    reliability = [
        OpeningReliability(
            symbol="BBAI",
            usable_days=10,
            total_bars=120,
            expected_bars=150,
        ),
        OpeningReliability(
            symbol="OPEN",
            usable_days=10,
            total_bars=145,
            expected_bars=150,
        ),
        OpeningReliability(
            symbol="SNAP",
            usable_days=10,
            total_bars=140,
            expected_bars=150,
        ),
    ]

    assert scanner.select_symbols(
        statistics,
        reliability=reliability,
    ) == ["OPEN", "SNAP"]


def test_reliability_falls_back_when_history_is_insufficient():
    from trading_bot.scanner import OpeningReliability

    scanner = StockScanner(
        current_symbols=["BBAI", "OPEN"],
    )

    statistics = [
        make_stats("SNAP"),
    ]

    reliability = [
        OpeningReliability(
            symbol="BBAI",
            usable_days=2,
            total_bars=20,
            expected_bars=30,
        ),
    ]

    assert scanner.select_symbols(
        statistics,
        reliability=reliability,
    ) == [
        "BBAI",
        "OPEN",
        "SNAP",
    ]


def test_full_candidate_ranking_preserves_production_top_three():
    scanner = StockScanner(
        current_symbols=["CORE"],
    )

    statistics = [
        make_stats("FIFTH", avg_range_pct=6.0),
        make_stats("FIRST", avg_range_pct=10.0),
        make_stats("FOURTH", avg_range_pct=7.0),
        make_stats("SECOND", avg_range_pct=9.0),
        make_stats("SIXTH", avg_range_pct=5.0),
        make_stats("THIRD", avg_range_pct=8.0),
    ]

    ranked = scanner.rank_candidates(
        statistics
    )

    production = scanner.select_candidates(
        statistics
    )

    assert [
        row.symbol
        for row in ranked
    ] == [
        "FIRST",
        "SECOND",
        "THIRD",
        "FOURTH",
        "FIFTH",
        "SIXTH",
    ]

    assert [
        row.symbol
        for row in production
    ] == [
        "FIRST",
        "SECOND",
        "THIRD",
    ]


def test_scanner_alternatives_are_ranks_four_to_six():
    scanner = StockScanner(
        current_symbols=["CORE"],
    )

    statistics = [
        make_stats("A", avg_range_pct=10.0),
        make_stats("B", avg_range_pct=9.0),
        make_stats("C", avg_range_pct=8.0),
        make_stats("D", avg_range_pct=7.0),
        make_stats("E", avg_range_pct=6.0),
        make_stats("F", avg_range_pct=5.0),
    ]

    alternatives = (
        scanner.select_alternatives(
            statistics,
            start_rank=4,
            limit=3,
        )
    )

    assert [
        (
            rank,
            row.symbol,
        )
        for rank, row
        in alternatives
    ] == [
        (4, "D"),
        (5, "E"),
        (6, "F"),
    ]


def test_production_scanner_uses_v2_dollar_volume_not_v1_share_volume():
    scanner = StockScanner(
        current_symbols=[],
        rules=ScannerRules(candidate_limit=1),
    )

    # LOW_DOLLAR wins the old V1 share-volume score because it
    # trades many more shares.
    low_dollar = make_stats(
        "LOW_DOLLAR",
        avg_price=2.50,
        avg_volume=5_000_000,
        avg_range_pct=8.0,
    )

    # HIGH_DOLLAR trades fewer shares, but far more dollars:
    #   LOW_DOLLAR  = $12.5M average dollar volume
    #   HIGH_DOLLAR = $50.0M average dollar volume
    #
    # V2 must therefore rank HIGH_DOLLAR above LOW_DOLLAR.
    high_dollar = make_stats(
        "HIGH_DOLLAR",
        avg_price=50.00,
        avg_volume=1_000_000,
        avg_range_pct=8.0,
    )

    # Preserve the old V1 score for research/control comparison.
    assert (
        low_dollar.ranking_score
        > high_dollar.ranking_score
    )

    selected = scanner.select_candidates(
        [
            low_dollar,
            high_dollar,
        ]
    )

    assert [
        row.symbol
        for row in selected
    ] == [
        "HIGH_DOLLAR",
    ]
