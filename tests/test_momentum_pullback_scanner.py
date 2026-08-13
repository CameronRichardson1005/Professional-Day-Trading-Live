from trading_bot.momentum_pullback_scanner import (
    MomentumPullbackScanner,
    MomentumScannerRules,
    MomentumStockSnapshot,
)


def make_snapshot(
    symbol="TEST",
    *,
    price=8.0,
    gain=15.0,
    rvol=6.0,
    float_shares=None,
    catalyst=None,
):
    return MomentumStockSnapshot(
        symbol=symbol,
        price=price,
        percent_gain=gain,
        relative_volume=rvol,
        current_volume=1_000_000,
        average_volume_30d=150_000,
        float_shares=float_shares,
        catalyst=catalyst,
    )


def test_market_data_candidate_passes_core_rules():
    scanner = MomentumPullbackScanner()

    snapshot = make_snapshot()

    assert scanner.is_market_data_eligible(
        snapshot
    )


def test_gain_must_be_at_least_ten_percent():
    scanner = MomentumPullbackScanner()

    failures = scanner.market_data_failures(
        make_snapshot(gain=9.99)
    )

    assert "GAIN BELOW MINIMUM" in failures


def test_relative_volume_must_be_at_least_five():
    scanner = MomentumPullbackScanner()

    failures = scanner.market_data_failures(
        make_snapshot(rvol=4.99)
    )

    assert (
        "RELATIVE VOLUME BELOW MINIMUM"
        in failures
    )


def test_source_price_range_is_one_to_twenty():
    scanner = MomentumPullbackScanner()

    assert scanner.is_market_data_eligible(
        make_snapshot(price=20.0)
    )

    assert (
        "PRICE ABOVE MAXIMUM"
        in scanner.market_data_failures(
            make_snapshot(price=20.01)
        )
    )


def test_price_open_research_variant_supported():
    scanner = MomentumPullbackScanner(
        rules=MomentumScannerRules(
            maximum_price=None,
        )
    )

    assert scanner.is_market_data_eligible(
        make_snapshot(price=50.0)
    )


def test_missing_float_and_catalyst_are_not_fabricated():
    scanner = MomentumPullbackScanner()

    snapshot = make_snapshot(
        float_shares=None,
        catalyst=None,
    )

    assert scanner.is_market_data_eligible(
        snapshot
    )

    assert not scanner.is_five_pillar_qualified(
        snapshot
    )

    failures = scanner.five_pillar_failures(
        snapshot
    )

    assert "FLOAT UNCONFIRMED" in failures
    assert "CATALYST UNCONFIRMED" in failures


def test_confirmed_five_pillar_candidate():
    scanner = MomentumPullbackScanner()

    snapshot = make_snapshot(
        float_shares=8_000_000,
        catalyst="Positive earnings catalyst",
    )

    assert scanner.is_five_pillar_qualified(
        snapshot
    )


def test_candidates_rank_by_percentage_gain():
    scanner = MomentumPullbackScanner()

    selected = scanner.select_candidates([
        make_snapshot("AAA", gain=15, rvol=10),
        make_snapshot("BBB", gain=30, rvol=5),
        make_snapshot("CCC", gain=20, rvol=8),
        make_snapshot("DDD", gain=12, rvol=20),
    ])

    assert [
        item.symbol
        for item in selected
    ] == [
        "BBB",
        "CCC",
        "AAA",
    ]
