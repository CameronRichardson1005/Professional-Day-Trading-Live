from dataclasses import dataclass

from .manipulation_selling_pressure import (
    calculate_adjusted_entries,
    calculate_close_location,
    calculate_relative_volume,
)
from .manipulation_selling_pressure_backtest import (
    EntryOutcome,
    calculate_research_trading_stop,
    evaluate_entry_outcome,
)
from .manipulation_selling_pressure_runner import (
    bar_date_et,
    group_bars_by_date,
    prior_opening_average,
    qualifies_manipulation,
)


ADAPTIVE_CLOSE_THRESHOLD = 0.20
ADAPTIVE_RELATIVE_VOLUME_THRESHOLD = 2.00
ADAPTIVE_ENTRY_ADJUSTMENT = 0.05


@dataclass(frozen=True)
class PairedValidationSignal:
    symbol: str
    date: str

    close_location: float
    relative_volume: float
    adaptive_triggered: bool

    control: EntryOutcome
    adaptive: EntryOutcome


def validate_symbol(
    *,
    symbol: str,
    opening_bars: list[dict],
    intraday_bars: list[dict],
    atr_by_date: dict[str, float],
    atr_multiplier: float,
    close_threshold: float = ADAPTIVE_CLOSE_THRESHOLD,
    relative_volume_threshold: float = (
        ADAPTIVE_RELATIVE_VOLUME_THRESHOLD
    ),
    adaptive_adjustment: float = ADAPTIVE_ENTRY_ADJUSTMENT,
) -> list[PairedValidationSignal]:

    intraday_by_date = group_bars_by_date(
        intraday_bars
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

        average_opening_volume = (
            prior_opening_average(
                opening_bars=opening_bars,
                current_date=date_str,
            )
        )

        if average_opening_volume is None:
            continue

        current_volume = float(
            opening_bar.get("v", 0)
            or 0
        )

        relative_volume = (
            calculate_relative_volume(
                current_volume=current_volume,
                average_opening_volume=(
                    average_opening_volume
                ),
            )
        )

        if relative_volume is None:
            continue

        high = float(opening_bar["h"])
        low = float(opening_bar["l"])
        close = float(opening_bar["c"])

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

        levels = calculate_adjusted_entries(
            high=high,
            low=low,
            adjustments=(
                0.00,
                adaptive_adjustment,
            ),
        )

        control_entry = levels[0.00]

        adaptive_triggered = (
            close_location
            <= close_threshold
            and relative_volume
            >= relative_volume_threshold
        )

        adaptive_entry = (
            levels[adaptive_adjustment]
            if adaptive_triggered
            else control_entry
        )

        day_bars = intraday_by_date.get(
            date_str,
            [],
        )

        control_stop = (
            calculate_research_trading_stop(
                entry=control_entry,
                target=target,
            )
        )

        adaptive_stop = (
            calculate_research_trading_stop(
                entry=adaptive_entry,
                target=target,
            )
        )

        control = evaluate_entry_outcome(
            bars=day_bars,
            adjustment=0.00,
            entry=control_entry,
            target=target,
            trading_stop=control_stop,
        )

        adaptive = evaluate_entry_outcome(
            bars=day_bars,
            adjustment=(
                adaptive_adjustment
                if adaptive_triggered
                else 0.00
            ),
            entry=adaptive_entry,
            target=target,
            trading_stop=adaptive_stop,
        )

        results.append(
            PairedValidationSignal(
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
                adaptive_triggered=(
                    adaptive_triggered
                ),
                control=control,
                adaptive=adaptive,
            )
        )

    return results


def summarize_side(
    outcomes: list[EntryOutcome],
) -> dict:
    total = len(outcomes)

    filled = [
        outcome
        for outcome in outcomes
        if outcome.filled
    ]

    targets = [
        outcome
        for outcome in outcomes
        if outcome.outcome == "TARGET"
    ]

    stops = [
        outcome
        for outcome in outcomes
        if outcome.outcome == "STOP"
    ]

    unresolved = [
        outcome
        for outcome in outcomes
        if outcome.outcome == "OPEN"
    ]

    not_filled = [
        outcome
        for outcome in outcomes
        if outcome.outcome == "NOT_FILLED"
    ]

    closed_returns = [
        outcome.return_pct
        for outcome in outcomes
        if outcome.return_pct is not None
    ]

    realized_return_sum = sum(
        closed_returns
    )

    return {
        "signals": total,
        "filled": len(filled),
        "not_filled": len(not_filled),
        "targets": len(targets),
        "stops": len(stops),
        "unresolved": len(unresolved),
        "fill_rate": (
            len(filled) / total
            if total
            else 0.0
        ),
        "target_rate_filled": (
            len(targets) / len(filled)
            if filled
            else 0.0
        ),
        "realized_return_sum": (
            realized_return_sum
        ),
        # Conservative strategy-level comparison:
        # unfilled and unresolved signals contribute 0.
        "realized_return_per_signal": (
            realized_return_sum / total
            if total
            else 0.0
        ),
        "average_closed_return": (
            realized_return_sum
            / len(closed_returns)
            if closed_returns
            else None
        ),
    }


def summarize_paired(
    signals: list[PairedValidationSignal],
) -> dict:
    control = summarize_side(
        [
            signal.control
            for signal in signals
        ]
    )

    adaptive = summarize_side(
        [
            signal.adaptive
            for signal in signals
        ]
    )

    triggered = [
        signal
        for signal in signals
        if signal.adaptive_triggered
    ]

    return {
        "signals": len(signals),
        "adaptive_trigger_count": (
            len(triggered)
        ),
        "control": control,
        "adaptive": adaptive,
    }
