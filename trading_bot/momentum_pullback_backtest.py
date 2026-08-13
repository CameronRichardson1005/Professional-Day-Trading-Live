from __future__ import annotations

from dataclasses import dataclass
from datetime import time

from .momentum_pullback_scanner import (
    MomentumPullbackScanner,
    MomentumStockSnapshot,
)
from .momentum_pullback_strategy import (
    MomentumCandle,
    MomentumPullbackSignal,
    MomentumPullbackStrategy,
)


@dataclass(frozen=True)
class MomentumBacktestTrade:
    symbol: str
    date: str

    pattern: str

    entry_time: str
    exit_time: str

    entry_price: float
    stop_price: float
    target_price: float
    exit_price: float

    percent_gain_at_entry: float
    relative_volume_at_entry: float

    outcome: str
    return_pct: float
    r_multiple: float

    hold_minutes: float


def build_snapshot(
    *,
    symbol: str,
    candle: MomentumCandle,
    cumulative_volume: float,
    previous_close: float,
    average_volume_30d: float,
) -> MomentumStockSnapshot:
    if previous_close <= 0:
        raise ValueError(
            "previous_close must be positive."
        )

    if average_volume_30d <= 0:
        raise ValueError(
            "average_volume_30d must be positive."
        )

    percent_gain = (
        (
            candle.close
            - previous_close
        )
        / previous_close
        * 100
    )

    # Literal market-data research interpretation of
    # the source's daily relative-volume definition.
    relative_volume = (
        cumulative_volume
        / average_volume_30d
    )

    return MomentumStockSnapshot(
        symbol=symbol,
        price=candle.close,
        percent_gain=percent_gain,
        relative_volume=relative_volume,
        current_volume=cumulative_volume,
        average_volume_30d=(
            average_volume_30d
        ),
        float_shares=None,
        catalyst=None,
    )


def evaluate_trade_outcome(
    *,
    candles: list[MomentumCandle],
    trigger_index: int,
    signal: MomentumPullbackSignal,
    cutoff: time = time(11, 0),
) -> tuple[
    str,
    float,
    str,
    float,
    float,
]:
    """
    Evaluate bars AFTER the trigger candle.

    This deliberately avoids pretending we know the
    intrabar ordering of entry/target/stop inside the
    same OHLC trigger candle.

    If stop and target are both touched in one later bar,
    STOP wins as the conservative assumption.
    """
    if (
        signal.entry_price is None
        or signal.stop_price is None
        or signal.target_price is None
        or signal.risk_per_share is None
    ):
        raise ValueError(
            "Signal must contain complete trade levels."
        )

    entry = signal.entry_price
    stop = signal.stop_price
    target = signal.target_price
    risk = signal.risk_per_share

    last_candle = candles[
        trigger_index
    ]

    for candle in candles[
        trigger_index + 1:
    ]:
        clock = (
            candle.timestamp
            .time()
            .replace(tzinfo=None)
        )

        if clock > cutoff:
            break

        last_candle = candle

        touched_stop = (
            candle.low <= stop
        )

        touched_target = (
            candle.high >= target
        )

        if touched_stop:
            return_pct = (
                (stop - entry)
                / entry
                * 100
            )

            return (
                "STOP",
                stop,
                candle.timestamp.isoformat(),
                return_pct,
                -1.0,
            )

        if touched_target:
            return_pct = (
                (target - entry)
                / entry
                * 100
            )

            r_multiple = (
                (target - entry)
                / risk
            )

            return (
                "TARGET",
                target,
                candle.timestamp.isoformat(),
                return_pct,
                r_multiple,
            )

    exit_price = last_candle.close

    return_pct = (
        (exit_price - entry)
        / entry
        * 100
    )

    r_multiple = (
        (exit_price - entry)
        / risk
    )

    return (
        "TIME_EXIT",
        exit_price,
        last_candle.timestamp.isoformat(),
        return_pct,
        r_multiple,
    )


def _front_side_impulse(
    *,
    candles: list[MomentumCandle],
    index: int,
) -> bool:
    """
    Mechanical research definition of "front side":

    the bullish impulse must establish or equal the
    highest high seen so far in the session.

    This is an implementation assumption, not a quoted
    rule from the source material.
    """
    candle = candles[index]

    if not candle.is_bullish:
        return False

    prior_high = max(
        (
            prior.high
            for prior in candles[:index]
        ),
        default=candle.high,
    )

    return candle.high >= prior_high


def backtest_symbol_day(
    *,
    symbol: str,
    date_str: str,
    candles: list[MomentumCandle],
    previous_close: float,
    average_volume_30d: float,
    scanner: MomentumPullbackScanner | None = None,
    strategy: MomentumPullbackStrategy | None = None,
) -> list[MomentumBacktestTrade]:
    """
    Research-only historical execution.

    Initial conservative rule:
    - maximum one Momentum Pullback trade per symbol/day
    - market-data scanner criteria must pass at entry
    - no historical catalyst/float is fabricated
    """
    scanner = (
        scanner
        or MomentumPullbackScanner()
    )

    strategy = (
        strategy
        or MomentumPullbackStrategy()
    )

    if len(candles) < 3:
        return []

    cumulative_volume = []
    running_volume = 0.0

    for candle in candles:
        running_volume += max(
            candle.volume,
            0.0,
        )

        cumulative_volume.append(
            running_volume
        )

    max_pullback = (
        strategy.max_pullback_candles
    )

    for impulse_index in range(
        0,
        len(candles) - 2,
    ):
        if not _front_side_impulse(
            candles=candles,
            index=impulse_index,
        ):
            continue

        for length in range(
            1,
            max_pullback + 1,
        ):
            trigger_index = (
                impulse_index
                + length
                + 1
            )

            if trigger_index >= len(
                candles
            ):
                break

            pullback = candles[
                impulse_index + 1:
                trigger_index
            ]

            trigger = candles[
                trigger_index
            ]

            snapshot = build_snapshot(
                symbol=symbol,
                candle=trigger,
                cumulative_volume=(
                    cumulative_volume[
                        trigger_index
                    ]
                ),
                previous_close=(
                    previous_close
                ),
                average_volume_30d=(
                    average_volume_30d
                ),
            )

            if not scanner.is_market_data_eligible(
                snapshot
            ):
                continue

            signal = (
                strategy
                .evaluate_micro_pullback(
                    symbol=symbol,
                    impulse=candles[
                        impulse_index
                    ],
                    pullback=pullback,
                    trigger=trigger,
                )
            )

            if signal.signal != "INVEST":
                continue

            (
                outcome,
                exit_price,
                exit_time,
                return_pct,
                r_multiple,
            ) = evaluate_trade_outcome(
                candles=candles,
                trigger_index=trigger_index,
                signal=signal,
            )

            entry_dt = (
                signal.trigger_time
            )

            exit_dt = (
                candles[
                    trigger_index
                ].timestamp
            )

            try:
                from datetime import datetime

                parsed_exit = (
                    datetime.fromisoformat(
                        exit_time
                    )
                )

                hold_minutes = (
                    (
                        parsed_exit
                        - entry_dt
                    ).total_seconds()
                    / 60
                )
            except Exception:
                hold_minutes = 0.0

            return [
                MomentumBacktestTrade(
                    symbol=symbol,
                    date=date_str,
                    pattern=signal.pattern,
                    entry_time=(
                        entry_dt.isoformat()
                        if entry_dt
                        else ""
                    ),
                    exit_time=exit_time,
                    entry_price=(
                        signal.entry_price
                    ),
                    stop_price=(
                        signal.stop_price
                    ),
                    target_price=(
                        signal.target_price
                    ),
                    exit_price=exit_price,
                    percent_gain_at_entry=(
                        snapshot.percent_gain
                    ),
                    relative_volume_at_entry=(
                        snapshot.relative_volume
                    ),
                    outcome=outcome,
                    return_pct=return_pct,
                    r_multiple=r_multiple,
                    hold_minutes=(
                        hold_minutes
                    ),
                )
            ]

    return []
