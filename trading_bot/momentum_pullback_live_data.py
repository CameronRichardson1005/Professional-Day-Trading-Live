from __future__ import annotations

from collections import defaultdict
from datetime import datetime, time, timedelta
from typing import Iterable
from zoneinfo import ZoneInfo

from .config import MARKET_DATA_FEED
from .momentum_pullback_scanner import (
    MomentumStockSnapshot,
)
from .momentum_pullback_snapshot_builder import (
    build_momentum_snapshot,
)


EASTERN = ZoneInfo(
    "America/New_York"
)

UTC = ZoneInfo("UTC")


def _parse_timestamp(
    value,
) -> datetime:
    if isinstance(
        value,
        datetime,
    ):
        result = value
    else:
        text = str(
            value
        ).strip()

        if text.endswith("Z"):
            text = (
                text[:-1]
                + "+00:00"
            )

        result = datetime.fromisoformat(
            text
        )

    if result.tzinfo is None:
        result = result.replace(
            tzinfo=UTC
        )

    return result


def _bar_timestamp(
    bar: dict,
) -> datetime | None:
    raw = bar.get(
        "t",
        bar.get("timestamp"),
    )

    if raw is None:
        return None

    try:
        return _parse_timestamp(
            raw
        )
    except (
        TypeError,
        ValueError,
    ):
        return None


def _bar_volume(
    bar: dict,
) -> float | None:
    raw = bar.get(
        "v",
        bar.get("volume"),
    )

    try:
        value = float(
            raw
        )
    except (
        TypeError,
        ValueError,
    ):
        return None

    if value < 0:
        return None

    return value


def _bar_close(
    bar: dict,
) -> float | None:
    raw = bar.get(
        "c",
        bar.get("close"),
    )

    try:
        value = float(
            raw
        )
    except (
        TypeError,
        ValueError,
    ):
        return None

    if value <= 0:
        return None

    return value


class MomentumPullbackLiveDataAdapter:
    """
    Build live Momentum Pullback scanner snapshots
    from existing Alpaca minute and daily data.

    Research definition of intraday RVOL:

        today's cumulative volume from session_start
        through as_of
        /
        average cumulative volume over prior sessions
        through the same clock time.

    The adapter is market-data only.
    """

    def __init__(
        self,
        *,
        alpaca,
        feed: str = MARKET_DATA_FEED,
        baseline_sessions: int = 20,
        minimum_baseline_sessions: int = 5,
        session_start: time = time(
            hour=7,
            minute=0,
        ),
    ) -> None:
        if baseline_sessions < 1:
            raise ValueError(
                "baseline_sessions must "
                "be at least 1."
            )

        if minimum_baseline_sessions < 1:
            raise ValueError(
                "minimum_baseline_sessions "
                "must be at least 1."
            )

        if (
            minimum_baseline_sessions
            > baseline_sessions
        ):
            raise ValueError(
                "minimum_baseline_sessions "
                "cannot exceed "
                "baseline_sessions."
            )

        self.alpaca = alpaca
        self.feed = feed

        self.baseline_sessions = (
            baseline_sessions
        )

        self.minimum_baseline_sessions = (
            minimum_baseline_sessions
        )

        self.session_start = (
            session_start
        )

    def build_snapshots(
        self,
        *,
        symbols: Iterable[str],
        as_of: datetime,
    ) -> list[
        MomentumStockSnapshot
    ]:
        symbols = tuple(
            dict.fromkeys(
                str(symbol)
                .strip()
                .upper()
                for symbol in symbols
                if str(symbol).strip()
            )
        )

        if not symbols:
            return []

        if as_of.tzinfo is None:
            as_of = as_of.replace(
                tzinfo=EASTERN
            )
        else:
            as_of = as_of.astimezone(
                EASTERN
            )

        symbols_csv = ",".join(
            symbols
        )

        # Allow enough calendar history to obtain
        # the requested number of trading sessions.
        calendar_lookback = max(
            self.baseline_sessions * 3,
            30,
        )

        first_day = (
            as_of.date()
            - timedelta(
                days=calendar_lookback
            )
        )

        intraday_start = (
            datetime.combine(
                first_day,
                self.session_start,
                tzinfo=EASTERN,
            )
            .astimezone(UTC)
        )

        intraday_end = (
            as_of.astimezone(
                UTC
            )
        )

        minute_bars = (
            self.alpaca
            .get_historical_1min_bars(
                symbols_csv=symbols_csv,
                start_iso=(
                    intraday_start
                    .strftime(
                        "%Y-%m-%dT%H:%M:%SZ"
                    )
                ),
                end_iso=(
                    intraday_end
                    .strftime(
                        "%Y-%m-%dT%H:%M:%SZ"
                    )
                ),
                feed=self.feed,
            )
        )

        daily_bars = (
            self.alpaca
            .get_historical_daily_bars(
                symbols_csv=symbols_csv,
                start_date=(
                    first_day.isoformat()
                ),
                end_date=(
                    as_of.date()
                    .isoformat()
                ),
                feed=self.feed,
            )
        )

        snapshots = []

        for symbol in symbols:
            snapshot = (
                self._build_symbol_snapshot(
                    symbol=symbol,
                    minute_bars=(
                        minute_bars.get(
                            symbol,
                            [],
                        )
                    ),
                    daily_bars=(
                        daily_bars.get(
                            symbol,
                            [],
                        )
                    ),
                    as_of=as_of,
                )
            )

            if snapshot is not None:
                snapshots.append(
                    snapshot
                )

        return snapshots

    def _build_symbol_snapshot(
        self,
        *,
        symbol: str,
        minute_bars: list[dict],
        daily_bars: list[dict],
        as_of: datetime,
    ) -> MomentumStockSnapshot | None:
        grouped: dict[
            object,
            list[dict],
        ] = defaultdict(
            list
        )

        cutoff_clock = (
            as_of.timetz()
            .replace(
                tzinfo=None
            )
        )

        for bar in minute_bars:
            timestamp = (
                _bar_timestamp(
                    bar
                )
            )

            if timestamp is None:
                continue

            eastern_time = (
                timestamp.astimezone(
                    EASTERN
                )
            )

            clock = (
                eastern_time
                .timetz()
                .replace(
                    tzinfo=None
                )
            )

            if (
                clock
                < self.session_start
            ):
                continue

            if (
                clock
                > cutoff_clock
            ):
                continue

            if (
                eastern_time.date()
                > as_of.date()
            ):
                continue

            grouped[
                eastern_time.date()
            ].append(
                bar
            )

        today_bars = grouped.get(
            as_of.date(),
            [],
        )

        if not today_bars:
            return None

        today_bars.sort(
            key=lambda bar: (
                _bar_timestamp(
                    bar
                )
                or datetime.min.replace(
                    tzinfo=UTC
                )
            )
        )

        current_price = (
            _bar_close(
                today_bars[-1]
            )
        )

        if current_price is None:
            return None

        cumulative_today = 0.0

        for bar in today_bars:
            volume = _bar_volume(
                bar
            )

            if volume is not None:
                cumulative_today += (
                    volume
                )

        if cumulative_today <= 0:
            return None

        prior_dates = sorted(
            (
                day
                for day in grouped
                if day < as_of.date()
            ),
            reverse=True,
        )[
            :self.baseline_sessions
        ]

        prior_totals = []

        for day in prior_dates:
            total = 0.0

            for bar in grouped[day]:
                volume = _bar_volume(
                    bar
                )

                if volume is not None:
                    total += volume

            if total > 0:
                prior_totals.append(
                    total
                )

        if (
            len(prior_totals)
            < self.minimum_baseline_sessions
        ):
            return None

        average_cumulative_volume = (
            sum(
                prior_totals
            )
            / len(
                prior_totals
            )
        )

        previous_close = (
            self._previous_close(
                daily_bars=(
                    daily_bars
                ),
                trading_date=(
                    as_of.date()
                ),
            )
        )

        if previous_close is None:
            return None

        return build_momentum_snapshot(
            symbol=symbol,
            current_price=(
                current_price
            ),
            previous_close=(
                previous_close
            ),
            cumulative_volume_today=(
                cumulative_today
            ),
            average_cumulative_volume=(
                average_cumulative_volume
            ),
        )

    @staticmethod
    def _previous_close(
        *,
        daily_bars: list[dict],
        trading_date,
    ) -> float | None:
        candidates = []

        for bar in daily_bars:
            timestamp = (
                _bar_timestamp(
                    bar
                )
            )

            if timestamp is None:
                continue

            if (
                timestamp.date()
                >= trading_date
            ):
                continue

            close = _bar_close(
                bar
            )

            if close is None:
                continue

            candidates.append(
                (
                    timestamp,
                    close,
                )
            )

        if not candidates:
            return None

        candidates.sort(
            key=lambda item: item[0]
        )

        return candidates[-1][1]
