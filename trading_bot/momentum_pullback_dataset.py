from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from zoneinfo import ZoneInfo

from .momentum_pullback_strategy import (
    MomentumCandle,
)


EASTERN = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class MomentumDailyContext:
    date: str
    previous_close: float
    average_volume_30d: float
    prior_sessions: int


def timestamp_et(value) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()

        if text.endswith("Z"):
            text = text[:-1] + "+00:00"

        dt = datetime.fromisoformat(text)

    if dt.tzinfo is None:
        return dt.replace(
            tzinfo=EASTERN,
        )

    return dt.astimezone(EASTERN)


def bar_date_et(bar: dict) -> str:
    return timestamp_et(
        bar["t"]
    ).strftime("%Y-%m-%d")


def candle_from_bar(
    bar: dict,
) -> MomentumCandle:
    return MomentumCandle(
        timestamp=timestamp_et(
            bar["t"]
        ),
        open=float(bar["o"]),
        high=float(bar["h"]),
        low=float(bar["l"]),
        close=float(bar["c"]),
        volume=float(
            bar.get("v", 0) or 0
        ),
    )


def filter_trading_window(
    bars: list[dict],
    *,
    start_time: time = time(7, 0),
    end_time: time = time(11, 0),
) -> list[dict]:
    """
    Keep only bars in the source trading window.

    The sample plan specifies approximately
    07:00-11:00 ET.
    """
    filtered = []

    for bar in bars:
        dt = timestamp_et(
            bar["t"]
        )

        clock = dt.time().replace(
            tzinfo=None
        )

        if (
            start_time
            <= clock
            <= end_time
        ):
            filtered.append(bar)

    filtered.sort(
        key=lambda bar: str(bar["t"])
    )

    return filtered


def group_bars_by_date(
    bars: list[dict],
) -> dict[str, list[dict]]:
    grouped = {}

    for bar in bars:
        date_str = bar_date_et(bar)

        grouped.setdefault(
            date_str,
            [],
        ).append(bar)

    for date_bars in grouped.values():
        date_bars.sort(
            key=lambda bar: str(bar["t"])
        )

    return grouped


def build_daily_context(
    *,
    daily_bars: list[dict],
    test_dates: list[str],
    lookback_sessions: int = 30,
    minimum_sessions: int = 20,
) -> dict[str, MomentumDailyContext]:
    """
    Build previous-close and average-volume values using
    ONLY sessions before each test date.

    No current-day or future information is used.
    """
    sorted_bars = sorted(
        daily_bars,
        key=lambda bar: str(bar["t"]),
    )

    result = {}

    for test_date in sorted(
        set(test_dates)
    ):
        prior = [
            bar
            for bar in sorted_bars
            if bar_date_et(bar)
            < test_date
        ]

        if len(prior) < minimum_sessions:
            continue

        previous = prior[-1]

        volume_window = prior[
            -lookback_sessions:
        ]

        valid_volumes = []

        for bar in volume_window:
            try:
                volume = float(
                    bar["v"]
                )
            except (
                KeyError,
                TypeError,
                ValueError,
            ):
                continue

            if volume >= 0:
                valid_volumes.append(
                    volume
                )

        if (
            len(valid_volumes)
            < minimum_sessions
        ):
            continue

        previous_close = float(
            previous["c"]
        )

        if previous_close <= 0:
            continue

        average_volume = (
            sum(valid_volumes)
            / len(valid_volumes)
        )

        if average_volume <= 0:
            continue

        result[test_date] = (
            MomentumDailyContext(
                date=test_date,
                previous_close=previous_close,
                average_volume_30d=(
                    average_volume
                ),
                prior_sessions=len(
                    valid_volumes
                ),
            )
        )

    return result
