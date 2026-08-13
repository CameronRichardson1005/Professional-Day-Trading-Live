from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from typing import Iterable

from .momentum_pullback_scanner import (
    MomentumStockSnapshot,
)


@dataclass(frozen=True)
class IntradayVolumeBaseline:
    symbol: str

    # Average cumulative volume observed through the
    # same clock time over prior sessions.
    average_cumulative_volume: float

    sessions_used: int


def calculate_percent_gain(
    *,
    current_price: float,
    previous_close: float,
) -> float:
    if previous_close <= 0:
        raise ValueError(
            "previous_close must be positive."
        )

    return (
        (
            current_price
            - previous_close
        )
        / previous_close
        * 100
    )


def calculate_time_normalized_rvol(
    *,
    cumulative_volume_today: float,
    average_cumulative_volume: float,
) -> float:
    """
    Intraday RVOL research definition:

        today's cumulative volume through now
        ---------------------------------------
        average cumulative volume through the same
        clock time over prior sessions

    This is our implementation choice for morning
    momentum scanning. The source material requires
    high relative volume but does not define this
    exact intraday normalization formula.
    """

    if average_cumulative_volume <= 0:
        raise ValueError(
            "average_cumulative_volume "
            "must be positive."
        )

    return (
        cumulative_volume_today
        / average_cumulative_volume
    )


def build_momentum_snapshot(
    *,
    symbol: str,
    current_price: float,
    previous_close: float,
    cumulative_volume_today: float,
    average_cumulative_volume: float,
    float_shares: float | None = None,
    catalyst: str | None = None,
) -> MomentumStockSnapshot:
    if current_price <= 0:
        raise ValueError(
            "current_price must be positive."
        )

    if cumulative_volume_today < 0:
        raise ValueError(
            "cumulative_volume_today "
            "cannot be negative."
        )

    percent_gain = calculate_percent_gain(
        current_price=current_price,
        previous_close=previous_close,
    )

    relative_volume = (
        calculate_time_normalized_rvol(
            cumulative_volume_today=(
                cumulative_volume_today
            ),
            average_cumulative_volume=(
                average_cumulative_volume
            ),
        )
    )

    return MomentumStockSnapshot(
        symbol=symbol,
        price=current_price,
        percent_gain=percent_gain,
        relative_volume=relative_volume,
        current_volume=(
            cumulative_volume_today
        ),
        average_volume_30d=(
            average_cumulative_volume
        ),
        float_shares=float_shares,
        catalyst=catalyst,
    )


def cumulative_volume_through(
    *,
    bars: Iterable[dict],
    cutoff: datetime,
) -> float:
    total = 0.0

    for bar in bars:
        raw_time = bar.get("timestamp")

        if raw_time is None:
            raw_time = bar.get("t")

        if raw_time is None:
            continue

        if isinstance(
            raw_time,
            datetime,
        ):
            timestamp = raw_time
        else:
            text = str(
                raw_time
            ).strip()

            if text.endswith("Z"):
                text = (
                    text[:-1]
                    + "+00:00"
                )

            timestamp = (
                datetime.fromisoformat(
                    text
                )
            )

        if (
            timestamp.tzinfo is not None
            and cutoff.tzinfo is not None
        ):
            timestamp = (
                timestamp.astimezone(
                    cutoff.tzinfo
                )
            )

        if timestamp > cutoff:
            continue

        try:
            volume = float(
                bar.get(
                    "volume",
                    bar.get("v", 0),
                )
                or 0
            )
        except (
            TypeError,
            ValueError,
        ):
            continue

        if volume > 0:
            total += volume

    return total


def average_prior_cumulative_volume(
    *,
    prior_sessions: Iterable[
        Iterable[dict]
    ],
    cutoff_time: time,
    minimum_sessions: int = 5,
) -> IntradayVolumeBaseline | None:
    """
    Calculate average cumulative volume through the
    same clock time across prior sessions.

    Each session must contain timestamped intraday
    bars/ticks with a volume field.
    """

    totals = []

    symbol = ""

    for session in prior_sessions:
        session = list(
            session
        )

        if not session:
            continue

        running = 0.0

        for bar in session:
            raw_time = bar.get(
                "timestamp",
                bar.get("t"),
            )

            if raw_time is None:
                continue

            if isinstance(
                raw_time,
                datetime,
            ):
                timestamp = raw_time
            else:
                text = str(
                    raw_time
                ).strip()

                if text.endswith("Z"):
                    text = (
                        text[:-1]
                        + "+00:00"
                    )

                timestamp = (
                    datetime.fromisoformat(
                        text
                    )
                )

            clock = (
                timestamp
                .timetz()
                .replace(tzinfo=None)
            )

            if clock > cutoff_time:
                continue

            try:
                volume = float(
                    bar.get(
                        "volume",
                        bar.get("v", 0),
                    )
                    or 0
                )
            except (
                TypeError,
                ValueError,
            ):
                continue

            if volume > 0:
                running += volume

            if not symbol:
                symbol = str(
                    bar.get(
                        "symbol",
                        "",
                    )
                )

        if running > 0:
            totals.append(
                running
            )

    if len(totals) < minimum_sessions:
        return None

    return IntradayVolumeBaseline(
        symbol=symbol,
        average_cumulative_volume=(
            sum(totals)
            / len(totals)
        ),
        sessions_used=len(
            totals
        ),
    )
