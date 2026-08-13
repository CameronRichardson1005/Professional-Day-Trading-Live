from dataclasses import dataclass

from .manipulation_selling_pressure_backtest import (
    filter_post_opening_bars,
)


@dataclass(frozen=True)
class NoStopOutcome:
    adjustment: float
    entry: float
    target: float

    filled: bool
    outcome: str

    exit_price: float | None
    return_pct: float | None

    # Negative percentage represents drawdown below entry.
    maximum_adverse_excursion_pct: float | None


def evaluate_no_stop_outcome(
    *,
    bars: list[dict],
    adjustment: float,
    entry: float,
    target: float,
) -> NoStopOutcome:
    """
    Evaluate a Manipulation entry without a stop loss.

    Rules
    -----
    - Entry fills when price trades at or below the entry.
    - Target may resolve the trade after entry.
    - If target is never reached, exit at the final
      regular-session bar close.
    - No automatic stop loss exists.

    Same-bar ambiguity
    ------------------
    If a bar trades both below entry and above target while
    opening ABOVE entry, the OHLC bar cannot tell us whether
    target occurred before entry.

    Therefore that entry candle does NOT automatically count
    as a target.

    If the bar opens at or below entry, the position is treated
    as filled from the open and a target touch during that bar
    is valid.
    """
    regular_bars = filter_post_opening_bars(
        bars
    )

    filled = False
    minimum_price_after_fill = None
    final_close = None

    for bar in regular_bars:
        open_price = float(bar["o"])
        high = float(bar["h"])
        low = float(bar["l"])
        close = float(bar["c"])

        if not filled:
            if low > entry:
                continue

            filled = True

            minimum_price_after_fill = low
            final_close = close

            # If the candle opens at/below entry, the limit
            # would already be executable at the beginning
            # of the candle. A later target touch is valid.
            if (
                open_price <= entry
                and high >= target
            ):
                mae = (
                    (
                        minimum_price_after_fill
                        - entry
                    )
                    / entry
                    * 100
                )

                return NoStopOutcome(
                    adjustment=adjustment,
                    entry=entry,
                    target=target,
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
                    maximum_adverse_excursion_pct=round(
                        mae,
                        4,
                    ),
                )

            # Otherwise continue to the next completed bar.
            # This avoids assuming the order of high and low
            # inside an ambiguous 5-minute entry candle.
            continue

        minimum_price_after_fill = min(
            minimum_price_after_fill,
            low,
        )

        final_close = close

        if high >= target:
            mae = (
                (
                    minimum_price_after_fill
                    - entry
                )
                / entry
                * 100
            )

            return NoStopOutcome(
                adjustment=adjustment,
                entry=entry,
                target=target,
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
                maximum_adverse_excursion_pct=round(
                    mae,
                    4,
                ),
            )

    if not filled:
        return NoStopOutcome(
            adjustment=adjustment,
            entry=entry,
            target=target,
            filled=False,
            outcome="NOT_FILLED",
            exit_price=None,
            return_pct=None,
            maximum_adverse_excursion_pct=None,
        )

    mae = (
        (
            minimum_price_after_fill
            - entry
        )
        / entry
        * 100
    )

    return NoStopOutcome(
        adjustment=adjustment,
        entry=entry,
        target=target,
        filled=True,
        outcome="EOD_EXIT",
        exit_price=final_close,
        return_pct=round(
            (
                final_close - entry
            )
            / entry
            * 100,
            4,
        ),
        maximum_adverse_excursion_pct=round(
            mae,
            4,
        ),
    )
