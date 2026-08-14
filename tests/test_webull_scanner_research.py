import pytest

from trading_bot.scanner_research import (
    rank_scanner_models,
)
from trading_bot.webull_strategy_market_data import (
    WebullStrategyMarketData,
)


def bar(
        day,
        *,
        close,
        high,
        low,
        volume,
):
    return {
        "t": f"{day}T00:00:00Z",
        "o": close,
        "h": high,
        "l": low,
        "c": close,
        "v": volume,
    }


def test_webull_scanner_statistics_use_only_prior_sessions():
    history = {
        "TEST": [
            bar(
                "2026-08-07",
                close=10,
                high=11,
                low=9,
                volume=1_000_000,
            ),
            bar(
                "2026-08-10",
                close=12,
                high=13,
                low=11,
                volume=2_000_000,
            ),
            bar(
                "2026-08-11",
                close=14,
                high=15,
                low=13,
                volume=3_000_000,
            ),
            # Evaluation date itself must never enter
            # scanner statistics.
            bar(
                "2026-08-12",
                close=100,
                high=120,
                low=80,
                volume=100_000_000,
            ),
        ]
    }

    results = (
        WebullStrategyMarketData
        .scanner_statistics_from_daily_history(
            daily_history=history,
            date_str="2026-08-12",
            lookback_days=3,
        )
    )

    assert len(results) == 1

    stats = results[0]

    assert stats.valid_bars == 3
    assert stats.avg_volume == pytest.approx(
        2_000_000
    )
    assert stats.avg_price == pytest.approx(
        12.0
    )
    assert stats.avg_range == pytest.approx(
        2.0
    )
    assert stats.avg_range_pct == pytest.approx(
        (2.0 / 12.0) * 100.0
    )


def test_webull_scanner_statistics_take_most_recent_lookback():
    history = {
        "TEST": [
            bar(
                "2026-08-06",
                close=2,
                high=2.5,
                low=1.5,
                volume=500_000,
            ),
            bar(
                "2026-08-07",
                close=10,
                high=11,
                low=9,
                volume=1_000_000,
            ),
            bar(
                "2026-08-10",
                close=20,
                high=22,
                low=18,
                volume=2_000_000,
            ),
        ]
    }

    results = (
        WebullStrategyMarketData
        .scanner_statistics_from_daily_history(
            daily_history=history,
            date_str="2026-08-11",
            lookback_days=2,
        )
    )

    assert results[0].valid_bars == 2
    assert results[0].avg_price == pytest.approx(
        15.0
    )


def test_research_models_preserve_candidate_limit():
    history = {
        symbol: [
            bar(
                "2026-08-10",
                close=price,
                high=price * 1.06,
                low=price * 0.94,
                volume=volume,
            )
            for _ in range(30)
        ]
        for symbol, price, volume in [
            ("A", 5, 800_000),
            ("B", 10, 1_000_000),
            ("C", 20, 2_000_000),
            ("D", 30, 3_000_000),
        ]
    }

    statistics = (
        WebullStrategyMarketData
        .scanner_statistics_from_daily_history(
            daily_history=history,
            date_str="2026-08-11",
            lookback_days=30,
        )
    )

    rankings = rank_scanner_models(
        statistics,
        current_symbols=[],
    )

    assert set(rankings) == {
        "V1_LOG_VOLUME",
        "V2_LOG_DOLLAR_VOLUME",
        "V3_Z_FACTOR",
    }

    for rows in rankings.values():
        assert sum(
            row.selected
            for row in rows
        ) == 3
