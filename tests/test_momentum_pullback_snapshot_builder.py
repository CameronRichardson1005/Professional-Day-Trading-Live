from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from trading_bot.momentum_pullback_snapshot_builder import (
    average_prior_cumulative_volume,
    build_momentum_snapshot,
    calculate_percent_gain,
    calculate_time_normalized_rvol,
    cumulative_volume_through,
)


EASTERN = ZoneInfo(
    "America/New_York"
)


def test_percent_gain():
    result = calculate_percent_gain(
        current_price=11.0,
        previous_close=10.0,
    )

    assert result == pytest.approx(
        10.0
    )


def test_time_normalized_rvol():
    result = calculate_time_normalized_rvol(
        cumulative_volume_today=500_000,
        average_cumulative_volume=100_000,
    )

    assert result == pytest.approx(
        5.0
    )


def test_snapshot_builds_gain_and_rvol():
    snapshot = build_momentum_snapshot(
        symbol="TEST",
        current_price=12.0,
        previous_close=10.0,
        cumulative_volume_today=600_000,
        average_cumulative_volume=100_000,
    )

    assert snapshot.symbol == "TEST"

    assert snapshot.percent_gain == (
        pytest.approx(
            20.0
        )
    )

    assert snapshot.relative_volume == (
        pytest.approx(
            6.0
        )
    )


def test_cumulative_volume_through_cutoff():
    cutoff = datetime(
        2026,
        8,
        13,
        9,
        31,
        tzinfo=EASTERN,
    )

    bars = [
        {
            "timestamp": datetime(
                2026,
                8,
                13,
                9,
                30,
                tzinfo=EASTERN,
            ),
            "volume": 100,
        },
        {
            "timestamp": datetime(
                2026,
                8,
                13,
                9,
                31,
                tzinfo=EASTERN,
            ),
            "volume": 200,
        },
        {
            "timestamp": datetime(
                2026,
                8,
                13,
                9,
                32,
                tzinfo=EASTERN,
            ),
            "volume": 300,
        },
    ]

    result = cumulative_volume_through(
        bars=bars,
        cutoff=cutoff,
    )

    assert result == 300


def test_average_prior_cumulative_volume():
    sessions = []

    for day, volume in (
        (6, 100),
        (7, 200),
        (8, 300),
        (9, 400),
        (10, 500),
    ):
        sessions.append([
            {
                "symbol": "TEST",
                "timestamp": datetime(
                    2026,
                    8,
                    day,
                    9,
                    30,
                    tzinfo=EASTERN,
                ),
                "volume": volume,
            },
            {
                "symbol": "TEST",
                "timestamp": datetime(
                    2026,
                    8,
                    day,
                    10,
                    0,
                    tzinfo=EASTERN,
                ),
                "volume": 999,
            },
        ])

    baseline = (
        average_prior_cumulative_volume(
            prior_sessions=sessions,
            cutoff_time=datetime(
                2026,
                8,
                13,
                9,
                45,
            ).time(),
            minimum_sessions=5,
        )
    )

    assert baseline is not None
    assert baseline.sessions_used == 5

    assert (
        baseline.average_cumulative_volume
        == pytest.approx(
            300.0
        )
    )


def test_insufficient_prior_sessions_returns_none():
    baseline = (
        average_prior_cumulative_volume(
            prior_sessions=[
                [
                    {
                        "timestamp": datetime(
                            2026,
                            8,
                            12,
                            9,
                            30,
                            tzinfo=EASTERN,
                        ),
                        "volume": 100,
                    }
                ]
            ],
            cutoff_time=datetime(
                2026,
                8,
                13,
                9,
                45,
            ).time(),
            minimum_sessions=5,
        )
    )

    assert baseline is None


def test_invalid_previous_close_rejected():
    with pytest.raises(
        ValueError
    ):
        build_momentum_snapshot(
            symbol="TEST",
            current_price=10,
            previous_close=0,
            cumulative_volume_today=100,
            average_cumulative_volume=50,
        )
