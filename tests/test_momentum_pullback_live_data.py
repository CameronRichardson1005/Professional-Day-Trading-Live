from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from trading_bot.momentum_pullback_live_data import (
    MomentumPullbackLiveDataAdapter,
)


EASTERN = ZoneInfo(
    "America/New_York"
)


def bar(
    day,
    hour,
    minute,
    *,
    close=10.0,
    volume=100,
):
    timestamp = datetime(
        2026,
        8,
        day,
        hour,
        minute,
        tzinfo=EASTERN,
    )

    return {
        "t": timestamp.isoformat(),
        "o": close,
        "h": close,
        "l": close,
        "c": close,
        "v": volume,
    }


class FakeAlpaca:
    def __init__(
        self,
        *,
        minute_bars,
        daily_bars,
    ):
        self.minute_bars = (
            minute_bars
        )

        self.daily_bars = (
            daily_bars
        )

        self.minute_calls = []
        self.daily_calls = []

    def get_historical_1min_bars(
        self,
        **kwargs,
    ):
        self.minute_calls.append(
            kwargs
        )
        return self.minute_bars

    def get_historical_daily_bars(
        self,
        **kwargs,
    ):
        self.daily_calls.append(
            kwargs
        )
        return self.daily_bars


def five_prior_sessions(
    symbol="TEST",
):
    bars = []

    for day in (
        6,
        7,
        10,
        11,
        12,
    ):
        bars.extend([
            bar(
                day,
                7,
                0,
                volume=50,
            ),
            bar(
                day,
                9,
                30,
                volume=50,
            ),
        ])

    return {
        symbol: bars
    }


def test_builds_live_snapshot_with_same_time_rvol():
    minute_data = (
        five_prior_sessions()
    )

    minute_data["TEST"].extend([
        bar(
            13,
            7,
            0,
            close=11.0,
            volume=300,
        ),
        bar(
            13,
            9,
            30,
            close=12.0,
            volume=300,
        ),
    ])

    daily_data = {
        "TEST": [
            bar(
                12,
                0,
                0,
                close=10.0,
                volume=1_000,
            )
        ]
    }

    alpaca = FakeAlpaca(
        minute_bars=minute_data,
        daily_bars=daily_data,
    )

    adapter = (
        MomentumPullbackLiveDataAdapter(
            alpaca=alpaca,
            baseline_sessions=5,
            minimum_baseline_sessions=5,
        )
    )

    snapshots = (
        adapter.build_snapshots(
            symbols=["TEST"],
            as_of=datetime(
                2026,
                8,
                13,
                9,
                30,
                tzinfo=EASTERN,
            ),
        )
    )

    assert len(snapshots) == 1

    snapshot = snapshots[0]

    assert (
        snapshot.price
        == pytest.approx(12.0)
    )

    assert (
        snapshot.percent_gain
        == pytest.approx(20.0)
    )

    # Today = 600.
    # Each prior session = 100.
    assert (
        snapshot.relative_volume
        == pytest.approx(6.0)
    )


def test_ignores_minutes_after_as_of():
    minute_data = (
        five_prior_sessions()
    )

    minute_data["TEST"].extend([
        bar(
            13,
            9,
            30,
            close=11,
            volume=600,
        ),
        bar(
            13,
            9,
            31,
            close=50,
            volume=10_000,
        ),
    ])

    alpaca = FakeAlpaca(
        minute_bars=minute_data,
        daily_bars={
            "TEST": [
                bar(
                    12,
                    0,
                    0,
                    close=10,
                )
            ]
        },
    )

    adapter = (
        MomentumPullbackLiveDataAdapter(
            alpaca=alpaca,
            baseline_sessions=5,
            minimum_baseline_sessions=5,
        )
    )

    result = (
        adapter.build_snapshots(
            symbols=["TEST"],
            as_of=datetime(
                2026,
                8,
                13,
                9,
                30,
                tzinfo=EASTERN,
            ),
        )
    )

    assert len(result) == 1
    assert result[0].price == 11


def test_requires_minimum_baseline_sessions():
    alpaca = FakeAlpaca(
        minute_bars={
            "TEST": [
                bar(
                    12,
                    9,
                    30,
                    volume=100,
                ),
                bar(
                    13,
                    9,
                    30,
                    volume=600,
                ),
            ]
        },
        daily_bars={
            "TEST": [
                bar(
                    12,
                    0,
                    0,
                    close=10,
                )
            ]
        },
    )

    adapter = (
        MomentumPullbackLiveDataAdapter(
            alpaca=alpaca,
            baseline_sessions=5,
            minimum_baseline_sessions=5,
        )
    )

    result = (
        adapter.build_snapshots(
            symbols=["TEST"],
            as_of=datetime(
                2026,
                8,
                13,
                9,
                30,
                tzinfo=EASTERN,
            ),
        )
    )

    assert result == []


def test_uses_latest_prior_daily_close():
    minute_data = (
        five_prior_sessions()
    )

    minute_data["TEST"].append(
        bar(
            13,
            9,
            30,
            close=12,
            volume=600,
        )
    )

    alpaca = FakeAlpaca(
        minute_bars=minute_data,
        daily_bars={
            "TEST": [
                bar(
                    11,
                    0,
                    0,
                    close=8,
                ),
                bar(
                    12,
                    0,
                    0,
                    close=10,
                ),
            ]
        },
    )

    adapter = (
        MomentumPullbackLiveDataAdapter(
            alpaca=alpaca,
            baseline_sessions=5,
            minimum_baseline_sessions=5,
        )
    )

    result = adapter.build_snapshots(
        symbols=["TEST"],
        as_of=datetime(
            2026,
            8,
            13,
            9,
            30,
            tzinfo=EASTERN,
        ),
    )

    assert (
        result[0].percent_gain
        == pytest.approx(20)
    )


def test_empty_symbols_makes_no_requests():
    alpaca = FakeAlpaca(
        minute_bars={},
        daily_bars={},
    )

    adapter = (
        MomentumPullbackLiveDataAdapter(
            alpaca=alpaca
        )
    )

    result = adapter.build_snapshots(
        symbols=[],
        as_of=datetime(
            2026,
            8,
            13,
            9,
            30,
            tzinfo=EASTERN,
        ),
    )

    assert result == []
    assert alpaca.minute_calls == []
    assert alpaca.daily_calls == []


def test_invalid_baseline_configuration():
    alpaca = FakeAlpaca(
        minute_bars={},
        daily_bars={},
    )

    with pytest.raises(
        ValueError
    ):
        MomentumPullbackLiveDataAdapter(
            alpaca=alpaca,
            baseline_sessions=4,
            minimum_baseline_sessions=5,
        )
