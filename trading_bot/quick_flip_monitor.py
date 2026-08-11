from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable

from .quick_flip_strategy import (
    QuickFlipCandle,
    QuickFlipOpeningRange,
    QuickFlipSignal,
    QuickFlipStrategy,
)


@dataclass(frozen=True)
class QuickFlipMonitorResult:
    symbol: str
    status: str
    detail: str
    opening_range: QuickFlipOpeningRange
    atr_14: float
    liquidity_confirmed: bool
    completed_5m_candles: tuple[QuickFlipCandle, ...]
    signal: QuickFlipSignal | None = None
    pending_pattern: str | None = None


def _parse_bar_timestamp(value: object) -> datetime:
    text = str(value).strip()

    if text.endswith("Z"):
        text = text[:-1] + "+00:00"

    return datetime.fromisoformat(text)



def reconcile_minute_bars(
    existing_bars: Iterable[dict],
    fetched_bars: Iterable[dict],
) -> list[dict]:
    """
    Reconcile completed one-minute bars by Alpaca timestamp.

    Existing bars provide the current local history.

    The later reconciliation fetch is authoritative for any
    timestamp it also contains, so corrected OHLCV values replace
    the earlier version.

    Missing minutes are never fabricated.

    The returned history is always chronological.
    """
    unique_bars: dict[str, dict] = {}

    for bar in existing_bars:
        timestamp = str(
            bar.get("t", "")
        ).strip()

        if timestamp:
            unique_bars[timestamp] = dict(bar)

    # Reconciliation fetch comes second deliberately.
    # A later Alpaca representation replaces an older
    # representation for the same completed minute.
    for bar in fetched_bars:
        timestamp = str(
            bar.get("t", "")
        ).strip()

        if timestamp:
            unique_bars[timestamp] = dict(bar)

    return [
        unique_bars[timestamp]
        for timestamp in sorted(unique_bars)
    ]

def aggregate_completed_5m_candles(
    minute_bars: Iterable[dict],
    *,
    evaluation_end: datetime | None = None,
) -> list[QuickFlipCandle]:
    """
    Convert Alpaca 1-minute bars into completed 5-minute
    candles.

    A 5-minute candle is emitted only when all five
    individual minutes are present.

    Example:
        09:45, 09:46, 09:47, 09:48, 09:49
        -> completed 09:45 five-minute candle.

    evaluation_end is the exclusive completed-minute
    boundary used by the live monitor.
    """

    parsed: list[tuple[datetime, dict]] = []

    for bar in minute_bars:
        required = {"t", "o", "h", "l", "c"}

        if not required.issubset(bar):
            continue

        timestamp = _parse_bar_timestamp(
            bar["t"]
        )

        if (
            evaluation_end is not None
            and timestamp >= evaluation_end
        ):
            continue

        parsed.append(
            (timestamp, bar)
        )

    parsed.sort(
        key=lambda item: item[0]
    )

    buckets: dict[
        datetime,
        dict[datetime, dict],
    ] = {}

    for timestamp, bar in parsed:
        bucket_start = timestamp.replace(
            minute=timestamp.minute
            - (timestamp.minute % 5),
            second=0,
            microsecond=0,
        )

        bucket = buckets.setdefault(
            bucket_start,
            {},
        )

        # If Alpaca reconciliation gives us the same
        # minute twice, keep the latest representation.
        bucket[timestamp.replace(
            second=0,
            microsecond=0,
        )] = bar

    candles: list[QuickFlipCandle] = []

    for bucket_start in sorted(buckets):
        bucket = buckets[bucket_start]

        expected_times = [
            bucket_start + timedelta(minutes=offset)
            for offset in range(5)
        ]

        if not all(
            expected in bucket
            for expected in expected_times
        ):
            continue

        bars = [
            bucket[expected]
            for expected in expected_times
        ]

        candles.append(
            QuickFlipCandle(
                timestamp=bucket_start,
                open=float(bars[0]["o"]),
                high=max(
                    float(bar["h"])
                    for bar in bars
                ),
                low=min(
                    float(bar["l"])
                    for bar in bars
                ),
                close=float(bars[-1]["c"]),
                volume=sum(
                    float(bar.get("v", 0) or 0)
                    for bar in bars
                ),
            )
        )

    return candles


class QuickFlipMonitor:
    """
    Deterministic Quick Flip intraday monitor.

    This class does not:
    - fetch market data,
    - write Google Sheets,
    - send Webull previews,
    - submit orders,
    - calculate a stop loss.

    It only evaluates completed 5-minute candles.
    """

    def __init__(
        self,
        strategy: QuickFlipStrategy | None = None,
    ) -> None:
        self.strategy = (
            strategy or QuickFlipStrategy()
        )

    def evaluate_minute_bars(
        self,
        *,
        symbol: str,
        opening_bar: QuickFlipCandle,
        atr_14: float,
        minute_bars: Iterable[dict],
        evaluation_end: datetime | None = None,
        cutoff_reached: bool = False,
    ) -> QuickFlipMonitorResult:
        candles = aggregate_completed_5m_candles(
            minute_bars,
            evaluation_end=evaluation_end,
        )

        return self.evaluate_five_minute_candles(
            symbol=symbol,
            opening_bar=opening_bar,
            atr_14=atr_14,
            candles=candles,
            cutoff_reached=cutoff_reached,
        )

    def evaluate_five_minute_candles(
        self,
        *,
        symbol: str,
        opening_bar: QuickFlipCandle,
        atr_14: float,
        candles: Iterable[QuickFlipCandle],
        cutoff_reached: bool = False,
    ) -> QuickFlipMonitorResult:
        opening_range = (
            self.strategy.build_opening_range(
                opening_bar
            )
        )

        completed = tuple(candles)

        liquidity_confirmed = (
            self.strategy.is_liquidity_opening_candle(
                opening_range,
                atr_14,
            )
        )

        if not liquidity_confirmed:
            return QuickFlipMonitorResult(
                symbol=symbol,
                status="NO_LIQUIDITY",
                detail=(
                    "Opening 15-minute candle did not "
                    "reach 125% of ATR14."
                ),
                opening_range=opening_range,
                atr_14=atr_14,
                liquidity_confirmed=False,
                completed_5m_candles=completed,
            )

        for index, current in enumerate(
            completed
        ):
            previous = (
                completed[index - 1]
                if index >= 1
                else None
            )

            # -----------------------------------------
            # Hammer / inverted hammer
            # -----------------------------------------
            #
            # Hammer-family patterns take priority over
            # engulfing when one candle satisfies both
            # definitions. This keeps the entry rule
            # deterministic:
            #
            # - prior candle must be red
            # - reversal trades below box low
            # - following 5-minute candle must break
            #   the reversal candle high
            if previous is not None:
                pattern = (
                    self.strategy.hammer_pattern_name(
                        current
                    )
                )

                valid_hammer_setup = (
                    pattern is not None
                    and previous.is_bearish
                    and self.strategy.is_outside_lower_box(
                        current,
                        opening_range,
                    )
                )

                if valid_hammer_setup:
                    confirmation_index = index + 1

                    if confirmation_index >= len(
                        completed
                    ):
                        if cutoff_reached:
                            continue

                        return QuickFlipMonitorResult(
                            symbol=symbol,
                            status="WAITING_FOR_CONFIRMATION",
                            detail=(
                                f"{pattern} detected below the "
                                "opening-range low. Waiting for "
                                "the next completed 5-minute candle."
                            ),
                            opening_range=opening_range,
                            atr_14=atr_14,
                            liquidity_confirmed=True,
                            completed_5m_candles=completed,
                            pending_pattern=pattern,
                        )

                    confirmation = completed[
                        confirmation_index
                    ]

                    signal = (
                        self.strategy.evaluate_hammer_setup(
                            symbol=symbol,
                            atr_14=atr_14,
                            opening_range=opening_range,
                            previous=previous,
                            reversal=current,
                            confirmation=confirmation,
                        )
                    )

                    if signal.signal == "INVEST":
                        return QuickFlipMonitorResult(
                            symbol=symbol,
                            status="INVEST",
                            detail=signal.detail,
                            opening_range=opening_range,
                            atr_14=atr_14,
                            liquidity_confirmed=True,
                            completed_5m_candles=completed,
                            signal=signal,
                        )

                    # Do not reinterpret the same reversal
                    # candle as engulfing after it has already
                    # qualified as a hammer-family pattern.
                    continue

            # -----------------------------------------
            # Bullish engulfing
            # -----------------------------------------
            #
            # Checked only when the current reversal
            # candle did not qualify as hammer-family.
            #
            # Entry = previous red candle high.
            if previous is not None:
                outside_engulfing_setup = (
                    self.strategy.is_outside_lower_box(
                        previous,
                        opening_range,
                    )
                    or
                    self.strategy.is_outside_lower_box(
                        current,
                        opening_range,
                    )
                )

                if (
                    outside_engulfing_setup
                    and
                    self.strategy.is_bullish_engulfing(
                        previous,
                        current,
                    )
                ):
                    signal = (
                        self.strategy
                        .evaluate_engulfing_setup(
                            symbol=symbol,
                            atr_14=atr_14,
                            opening_range=opening_range,
                            previous=previous,
                            engulfing=current,
                        )
                    )

                    if signal.signal == "INVEST":
                        return QuickFlipMonitorResult(
                            symbol=symbol,
                            status="INVEST",
                            detail=signal.detail,
                            opening_range=opening_range,
                            atr_14=atr_14,
                            liquidity_confirmed=True,
                            completed_5m_candles=completed,
                            signal=signal,
                        )

            # A failed confirmation only invalidates
            # this specific hammer. Continue looking
            # for another valid reversal before cutoff.

        if cutoff_reached:
            return QuickFlipMonitorResult(
                symbol=symbol,
                status="EXPIRED",
                detail=(
                    "No confirmed Quick Flip reversal "
                    "was found before the cutoff."
                ),
                opening_range=opening_range,
                atr_14=atr_14,
                liquidity_confirmed=True,
                completed_5m_candles=completed,
            )

        return QuickFlipMonitorResult(
            symbol=symbol,
            status="WATCHING",
            detail=(
                "Liquidity confirmed. Watching completed "
                "5-minute candles for a reversal outside "
                "the lower opening-range box."
            ),
            opening_range=opening_range,
            atr_14=atr_14,
            liquidity_confirmed=True,
            completed_5m_candles=completed,
        )
