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
        "CCC",
        "BBB",
        "DDD",
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
    ] == ["VALID"]


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
