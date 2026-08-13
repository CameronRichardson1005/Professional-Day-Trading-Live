from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from .manipulation_selling_pressure import (
    calculate_adjusted_entries,
    calculate_average_opening_volume,
    calculate_close_location,
    calculate_relative_volume,
)
from .manipulation_selling_pressure_backtest import (
    calculate_research_trading_stop,
    evaluate_entry_outcome,
)


ENTRY_ADJUSTMENTS = (
    0.00,
    0.05,
    0.10,
    0.15,
    0.20,
    0.25,
)

RELATIVE_VOLUME_THRESHOLDS = (
    1.25,
    1.50,
    2.00,
)

CLOSE_LOCATION_THRESHOLDS = (
    0.10,
    0.20,
    0.30,
)


@dataclass(frozen=True)
class ResearchTrade:
    symbol: str
    date: str
    close_location: float
    relative_volume: float
    close_threshold: float
    volume_threshold: float
    adjustment: float
    entry: float
    target: float
    trading_stop: float
    filled: bool
    outcome: str
    return_pct: float | None


def bar_date_et(bar: dict) -> str:
    text = str(bar["t"]).strip()

    if text.endswith("Z"):
        text = text[:-1] + "+00:00"

    return (
        datetime
        .fromisoformat(text)
        .astimezone(
            ZoneInfo("America/New_York")
        )
        .strftime("%Y-%m-%d")
    )


def group_bars_by_date(
    bars: list[dict],
) -> dict[str, list[dict]]:
    grouped = defaultdict(list)

    for bar in bars:
        grouped[
            bar_date_et(bar)
        ].append(bar)

    for date_bars in grouped.values():
        date_bars.sort(
            key=lambda bar: str(bar["t"])
        )

    return dict(grouped)


def prior_opening_average(
    *,
    opening_bars: list[dict],
    current_date: str,
    lookback_sessions: int = 20,
    minimum_sessions: int = 5,
) -> float | None:
    """
    Average only opening bars BEFORE current_date.

    This prevents look-ahead bias.
    """
    prior = [
        bar
        for bar in opening_bars
        if bar_date_et(bar) < current_date
    ]

    prior = prior[
        -lookback_sessions:
    ]

    return calculate_average_opening_volume(
        prior,
        minimum_sessions=minimum_sessions,
    )


def qualifies_manipulation(
    *,
    opening_bar: dict,
    atr: float,
    atr_multiplier: float,
) -> bool:
    """
    Preserve the current Manipulation qualification:

    1. Opening candle is manipulation-sized.
    2. Opening candle is red.
    """
    open_price = float(
        opening_bar["o"]
    )
    high = float(
        opening_bar["h"]
    )
    low = float(
        opening_bar["l"]
    )
    close = float(
        opening_bar["c"]
    )

    candle_range = high - low
    atr_threshold = (
        float(atr)
        * float(atr_multiplier)
    )

    exceeds_threshold = (
        candle_range > atr_threshold
    )

    within_margin = (
        atr_threshold - candle_range
    ) <= 0.005

    is_manipulation = (
        exceeds_threshold
        or within_margin
    )

    is_red = (
        open_price > close
    )

    return (
        is_manipulation
        and is_red
    )


def run_symbol_research(
    *,
    symbol: str,
    opening_bars: list[dict],
    intraday_bars: list[dict],
    atr_by_date: dict[str, float],
    atr_multiplier: float,
) -> list[ResearchTrade]:
    """
    Run all selling-pressure parameter combinations for
    one symbol.

    No live strategy state is modified.
    """
    intraday_by_date = (
        group_bars_by_date(
            intraday_bars
        )
    )

    results = []

    for opening_bar in opening_bars:
        date_str = bar_date_et(
            opening_bar
        )

        atr = atr_by_date.get(
            date_str
        )

        if atr is None:
            continue

        if not qualifies_manipulation(
            opening_bar=opening_bar,
            atr=atr,
            atr_multiplier=atr_multiplier,
        ):
            continue

        average_volume = (
            prior_opening_average(
                opening_bars=opening_bars,
                current_date=date_str,
            )
        )

        if average_volume is None:
            continue

        current_volume = float(
            opening_bar.get(
                "v",
                0,
            )
            or 0
        )

        relative_volume = (
            calculate_relative_volume(
                current_volume=current_volume,
                average_opening_volume=(
                    average_volume
                ),
            )
        )

        if relative_volume is None:
            continue

        high = float(
            opening_bar["h"]
        )
        low = float(
            opening_bar["l"]
        )
        close = float(
            opening_bar["c"]
        )

        close_location = (
            calculate_close_location(
                high=high,
                low=low,
                close=close,
            )
        )

        target = (
            low
            + (
                (high - low)
                * 0.382
            )
        )

        entry_levels = (
            calculate_adjusted_entries(
                high=high,
                low=low,
                adjustments=(
                    ENTRY_ADJUSTMENTS
                ),
            )
        )

        day_bars = (
            intraday_by_date.get(
                date_str,
                [],
            )
        )

        for close_threshold in (
            CLOSE_LOCATION_THRESHOLDS
        ):
            if (
                close_location
                > close_threshold
            ):
                continue

            for volume_threshold in (
                RELATIVE_VOLUME_THRESHOLDS
            ):
                if (
                    relative_volume
                    < volume_threshold
                ):
                    continue

                for adjustment in (
                    ENTRY_ADJUSTMENTS
                ):
                    entry = (
                        entry_levels[
                            adjustment
                        ]
                    )

                    trading_stop = (
                        calculate_research_trading_stop(
                            entry=entry,
                            target=target,
                        )
                    )

                    outcome = (
                        evaluate_entry_outcome(
                            bars=day_bars,
                            adjustment=(
                                adjustment
                            ),
                            entry=entry,
                            target=target,
                            trading_stop=(
                                trading_stop
                            ),
                        )
                    )

                    results.append(
                        ResearchTrade(
                            symbol=symbol,
                            date=date_str,
                            close_location=round(
                                close_location,
                                6,
                            ),
                            relative_volume=round(
                                relative_volume,
                                6,
                            ),
                            close_threshold=(
                                close_threshold
                            ),
                            volume_threshold=(
                                volume_threshold
                            ),
                            adjustment=(
                                adjustment
                            ),
                            entry=round(
                                entry,
                                4,
                            ),
                            target=round(
                                target,
                                4,
                            ),
                            trading_stop=(
                                trading_stop
                            ),
                            filled=(
                                outcome.filled
                            ),
                            outcome=(
                                outcome.outcome
                            ),
                            return_pct=(
                                outcome.return_pct
                            ),
                        )
                    )

    return results


def summarize_results(
    trades: list[ResearchTrade],
) -> list[dict]:
    grouped = defaultdict(list)

    for trade in trades:
        key = (
            trade.close_threshold,
            trade.volume_threshold,
            trade.adjustment,
        )

        grouped[key].append(
            trade
        )

    summaries = []

    for key, group in sorted(
        grouped.items()
    ):
        (
            close_threshold,
            volume_threshold,
            adjustment,
        ) = key

        total = len(group)

        filled = [
            trade
            for trade in group
            if trade.filled
        ]

        targets = [
            trade
            for trade in group
            if trade.outcome
            == "TARGET"
        ]

        stops = [
            trade
            for trade in group
            if trade.outcome
            == "STOP"
        ]

        closed_returns = [
            trade.return_pct
            for trade in group
            if trade.return_pct
            is not None
        ]

        summaries.append(
            {
                "close_threshold": (
                    close_threshold
                ),
                "volume_threshold": (
                    volume_threshold
                ),
                "adjustment": adjustment,
                "signals": total,
                "filled": len(
                    filled
                ),
                "fill_rate": (
                    len(filled) / total
                    if total
                    else 0.0
                ),
                "targets": len(
                    targets
                ),
                "stops": len(
                    stops
                ),
                "target_rate_filled": (
                    len(targets)
                    / len(filled)
                    if filled
                    else 0.0
                ),
                "average_return_pct": (
                    sum(
                        closed_returns
                    )
                    / len(
                        closed_returns
                    )
                    if closed_returns
                    else None
                ),
            }
        )

    return summaries
