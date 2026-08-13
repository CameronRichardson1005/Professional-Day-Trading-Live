from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .momentum_pullback_backtest import (
    MomentumBacktestTrade,
    build_snapshot,
    evaluate_trade_outcome,
)
from .momentum_pullback_scanner import (
    MomentumPullbackScanner,
    MomentumStockSnapshot,
)
from .momentum_pullback_strategy import (
    MomentumCandle,
    MomentumPullbackSignal,
    MomentumPullbackStrategy,
)


MAX_FLAT_TOP_BASE_CANDLES = 4


@dataclass(frozen=True)
class RankedMomentumSnapshot:
    rank: int
    snapshot: MomentumStockSnapshot


def rank_snapshots(
    *,
    snapshots: list[MomentumStockSnapshot],
    scanner: MomentumPullbackScanner,
) -> list[RankedMomentumSnapshot]:
    eligible = [
        snapshot
        for snapshot in snapshots
        if scanner.is_market_data_eligible(
            snapshot
        )
    ]

    eligible.sort(
        key=lambda snapshot: (
            -snapshot.percent_gain,
            -snapshot.relative_volume,
            snapshot.symbol,
        )
    )

    return [
        RankedMomentumSnapshot(
            rank=index,
            snapshot=snapshot,
        )
        for index, snapshot in enumerate(
            eligible[
                :scanner.rules.candidate_limit
            ],
            start=1,
        )
    ]


def _is_front_side_impulse(
    *,
    candles: list[MomentumCandle],
    impulse_index: int,
) -> bool:
    impulse = candles[
        impulse_index
    ]

    if not impulse.is_bullish:
        return False

    previous_high = max(
        (
            candle.high
            for candle
            in candles[:impulse_index]
        ),
        default=impulse.high,
    )

    return (
        impulse.high
        >= previous_high
    )


def find_momentum_signal(
    *,
    symbol: str,
    candles: list[MomentumCandle],
    trigger_index: int,
    strategy: MomentumPullbackStrategy,
) -> MomentumPullbackSignal | None:
    """
    Find a source-inspired setup ending at trigger_index.

    Priority:
    1. Micro-pullback
    2. Flat-top breakout

    The source material defines the concepts but not exact
    candle-count thresholds. Those remain explicit research
    assumptions in the strategy implementation.
    """
    if trigger_index < 2:
        return None

    trigger = candles[
        trigger_index
    ]

    # Micro-pullback:
    # impulse + 1-3 pullback candles + trigger.
    for pullback_count in range(
        1,
        strategy.max_pullback_candles + 1,
    ):
        impulse_index = (
            trigger_index
            - pullback_count
            - 1
        )

        if impulse_index < 0:
            continue

        if not _is_front_side_impulse(
            candles=candles,
            impulse_index=impulse_index,
        ):
            continue

        pullback = candles[
            impulse_index + 1:
            trigger_index
        ]

        signal = (
            strategy.evaluate_micro_pullback(
                symbol=symbol,
                impulse=candles[
                    impulse_index
                ],
                pullback=pullback,
                trigger=trigger,
            )
        )

        if signal.signal == "INVEST":
            return signal

    # Flat-top breakout:
    # immediately preceding 2-4 candles form resistance.
    for base_count in range(
        2,
        MAX_FLAT_TOP_BASE_CANDLES + 1,
    ):
        start_index = (
            trigger_index
            - base_count
        )

        if start_index < 0:
            continue

        base = candles[
            start_index:
            trigger_index
        ]

        signal = (
            strategy.evaluate_flat_top(
                symbol=symbol,
                base=base,
                breakout=trigger,
            )
        )

        if signal.signal == "INVEST":
            return signal

    return None


def _trade_from_signal(
    *,
    symbol: str,
    date_str: str,
    candles: list[MomentumCandle],
    trigger_index: int,
    snapshot: MomentumStockSnapshot,
    signal: MomentumPullbackSignal,
) -> MomentumBacktestTrade:
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

    if (
        signal.entry_price is None
        or signal.stop_price is None
        or signal.target_price is None
        or signal.trigger_time is None
    ):
        raise ValueError(
            "Confirmed signal has incomplete levels."
        )

    try:
        parsed_exit = datetime.fromisoformat(
            exit_time
        )

        hold_minutes = (
            (
                parsed_exit
                - signal.trigger_time
            ).total_seconds()
            / 60
        )
    except Exception:
        hold_minutes = 0.0

    return MomentumBacktestTrade(
        symbol=symbol,
        date=date_str,
        pattern=signal.pattern,
        entry_time=(
            signal.trigger_time.isoformat()
        ),
        exit_time=exit_time,
        entry_price=signal.entry_price,
        stop_price=signal.stop_price,
        target_price=signal.target_price,
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
        hold_minutes=hold_minutes,
    )


def run_universe_day(
    *,
    date_str: str,
    candles_by_symbol: dict[
        str,
        list[MomentumCandle],
    ],
    previous_close_by_symbol: dict[
        str,
        float,
    ],
    average_volume_by_symbol: dict[
        str,
        float,
    ],
    scanner: MomentumPullbackScanner,
    strategy: MomentumPullbackStrategy,
) -> list[MomentumBacktestTrade]:
    """
    Historical source-style scanner + setup simulation.

    At each completed candle:
    1. Calculate % gain and RVOL for every stock.
    2. Apply scanner eligibility.
    3. Rank eligible stocks by percentage gain.
    4. Only the top N may generate a setup.
    5. Maximum one trade per symbol/day.

    No news or float values are fabricated.
    """
    index_by_symbol_time = {}
    cumulative_volume = {}

    all_times = set()

    for symbol, candles in (
        candles_by_symbol.items()
    ):
        mapping = {}
        running = 0.0
        volumes = []

        for index, candle in enumerate(
            candles
        ):
            mapping[
                candle.timestamp
            ] = index

            running += max(
                candle.volume,
                0.0,
            )

            volumes.append(
                running
            )

            all_times.add(
                candle.timestamp
            )

        index_by_symbol_time[
            symbol
        ] = mapping

        cumulative_volume[
            symbol
        ] = volumes

    traded_symbols = set()
    trades = []

    for timestamp in sorted(
        all_times
    ):
        snapshots = []
        snapshot_by_symbol = {}

        for symbol, candles in (
            candles_by_symbol.items()
        ):
            index = (
                index_by_symbol_time[
                    symbol
                ].get(timestamp)
            )

            if index is None:
                continue

            previous_close = (
                previous_close_by_symbol.get(
                    symbol
                )
            )

            average_volume = (
                average_volume_by_symbol.get(
                    symbol
                )
            )

            if (
                previous_close is None
                or average_volume is None
            ):
                continue

            snapshot = build_snapshot(
                symbol=symbol,
                candle=candles[index],
                cumulative_volume=(
                    cumulative_volume[
                        symbol
                    ][index]
                ),
                previous_close=(
                    previous_close
                ),
                average_volume_30d=(
                    average_volume
                ),
            )

            snapshots.append(
                snapshot
            )

            snapshot_by_symbol[
                symbol
            ] = snapshot

        ranked = rank_snapshots(
            snapshots=snapshots,
            scanner=scanner,
        )

        for ranked_item in ranked:
            symbol = (
                ranked_item
                .snapshot
                .symbol
            )

            if symbol in traded_symbols:
                continue

            candles = (
                candles_by_symbol[
                    symbol
                ]
            )

            trigger_index = (
                index_by_symbol_time[
                    symbol
                ].get(timestamp)
            )

            if trigger_index is None:
                continue

            signal = find_momentum_signal(
                symbol=symbol,
                candles=candles,
                trigger_index=trigger_index,
                strategy=strategy,
            )

            if (
                signal is None
                or signal.signal
                != "INVEST"
            ):
                continue

            trade = _trade_from_signal(
                symbol=symbol,
                date_str=date_str,
                candles=candles,
                trigger_index=trigger_index,
                snapshot=(
                    snapshot_by_symbol[
                        symbol
                    ]
                ),
                signal=signal,
            )

            trades.append(
                trade
            )

            traded_symbols.add(
                symbol
            )

    return trades
