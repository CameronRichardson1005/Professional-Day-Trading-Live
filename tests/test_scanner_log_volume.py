import math

from trading_bot.scanner import (
    ScannerRules,
    StockScanner,
    StockStats,
)


def stats(
    symbol,
    *,
    price,
    volume,
    range_pct,
    avg_range=1.0,
):
    return StockStats(
        symbol=symbol,
        valid_bars=30,
        avg_volume=volume,
        avg_price=price,
        avg_range=avg_range,
        avg_range_pct=range_pct,
    )


def test_default_scanner_has_no_maximum_price():
    scanner = StockScanner(
        current_symbols=[],
    )

    candidate = stats(
        "IONQ",
        price=40.0,
        volume=708_000,
        range_pct=6.63,
        avg_range=2.64,
    )

    failures = scanner.eligibility_failures(
        candidate
    )

    assert "PRICE ABOVE MAXIMUM" not in failures
    assert failures == []


def test_explicit_maximum_price_can_still_be_used():
    scanner = StockScanner(
        current_symbols=[],
        rules=ScannerRules(
            maximum_price=30.0,
        ),
    )

    candidate = stats(
        "TEST",
        price=40.0,
        volume=1_000_000,
        range_pct=6.0,
    )

    assert (
        "PRICE ABOVE MAXIMUM"
        in scanner.eligibility_failures(candidate)
    )


def test_ranking_score_uses_log_volume():
    candidate = stats(
        "TEST",
        price=50.0,
        volume=1_000_000,
        range_pct=5.0,
    )

    expected = (
        5.0
        * math.log1p(
            1_000_000 / 500_000
        )
    )

    assert candidate.ranking_score == expected


def test_log_volume_reduces_raw_volume_dominance():
    higher_range = stats(
        "RANGE",
        price=50.0,
        volume=1_000_000,
        range_pct=10.0,
    )

    huge_volume = stats(
        "VOLUME",
        price=50.0,
        volume=2_000_000,
        range_pct=6.0,
    )

    assert (
        higher_range.ranking_score
        > huge_volume.ranking_score
    )
