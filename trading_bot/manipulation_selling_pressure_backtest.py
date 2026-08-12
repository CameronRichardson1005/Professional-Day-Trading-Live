from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from .config import STOP_BUFFER


@dataclass(frozen=True)
class EntryOutcome:
    adjustment: float
    entry: float
    target: float
    trading_stop: float
    filled: bool
    outcome: str
    exit_price: float | None
    return_pct: float | None


def calculate_research_trading_stop(
    *,
    entry: float,
    target: float,
) -> float:
    """
    Recalculate the preserved Manipulation trading stop
    relative to a research entry.

    Target remains the original Manipulation target.
    """
    entry = float(entry)
    target = float(target)

    stop_loss = entry - (
        (target - entry) / 2
    )

    if (
        entry - STOP_BUFFER
    ) < stop_loss:
        stop_loss -= STOP_BUFFER

    return round(
        stop_loss - STOP_BUFFER,
        4,
    )


def _bar_time_et(bar: dict) -> datetime:
    text = str(bar["t"]).strip()

    if text.endswith("Z"):
        text = text[:-1] + "+00:00"

    return (
        datetime
        .fromisoformat(text)
        .astimezone(
            ZoneInfo("America/New_York")
        )
    )


def filter_post_opening_bars(
    bars: list[dict],
) -> list[dict]:
    """
    Only evaluate completed bars beginning at 09:45 ET
    or later.

    The 09:30 opening candle itself can never fill the
    research entry.
    """
    result = []

    for bar in bars:
        local = _bar_time_et(bar)

        if (
            local.hour > 9
            or (
                local.hour == 9
                and local.minute >= 45
            )
        ):
            result.append(bar)

    return result


def evaluate_entry_outcome(
    *,
    bars: list[dict],
    adjustment: float,
    entry: float,
    target: float,
    trading_stop: float,
) -> EntryOutcome:
    """
    Evaluate one research entry using chronological 5Min bars.

    Fill:
      bar low <= entry

    After fill:
      target if bar high >= target
      stop if bar low <= trading_stop

    If target and stop occur inside the same 5Min candle,
    STOP is assumed first. This is deliberately conservative
    because OHLC data cannot reveal the intrabar sequence.
    """
    filled = False

    for bar in filter_post_opening_bars(
        bars
    ):
        high = float(bar["h"])
        low = float(bar["l"])

        if not filled:
            if low > entry:
                continue

            filled = True

            # On the entry candle, prices below entry may
            # have occurred before or after the fill.
            # Conservatively treat a stop touch as STOP.
            if low <= trading_stop:
                return EntryOutcome(
                    adjustment=adjustment,
                    entry=entry,
                    target=target,
                    trading_stop=trading_stop,
                    filled=True,
                    outcome="STOP",
                    exit_price=trading_stop,
                    return_pct=round(
                        (
                            trading_stop
                            - entry
                        )
                        / entry
                        * 100,
                        4,
                    ),
                )

            if high >= target:
                return EntryOutcome(
                    adjustment=adjustment,
                    entry=entry,
                    target=target,
                    trading_stop=trading_stop,
                    filled=True,
                    outcome="TARGET",
                    exit_price=target,
                    return_pct=round(
                        (
                            target - entry
                        )
                        / entry
                        * 100,
                        4,
                    ),
                )

            continue

        stop_hit = (
            low <= trading_stop
        )
        target_hit = (
            high >= target
        )

        if stop_hit:
            return EntryOutcome(
                adjustment=adjustment,
                entry=entry,
                target=target,
                trading_stop=trading_stop,
                filled=True,
                outcome="STOP",
                exit_price=trading_stop,
                return_pct=round(
                    (
                        trading_stop
                        - entry
                    )
                    / entry
                    * 100,
                    4,
                ),
            )

        if target_hit:
            return EntryOutcome(
                adjustment=adjustment,
                entry=entry,
                target=target,
                trading_stop=trading_stop,
                filled=True,
                outcome="TARGET",
                exit_price=target,
                return_pct=round(
                    (
                        target - entry
                    )
                    / entry
                    * 100,
                    4,
                ),
            )

    return EntryOutcome(
        adjustment=adjustment,
        entry=entry,
        target=target,
        trading_stop=trading_stop,
        filled=filled,
        outcome=(
            "OPEN"
            if filled
            else "NOT_FILLED"
        ),
        exit_price=None,
        return_pct=None,
    )
