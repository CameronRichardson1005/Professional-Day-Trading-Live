from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from .manipulation_selling_pressure_backtest import (
    evaluate_entry_outcome,
)
from .models import Stock
from .quick_flip_strategy import QuickFlipSignal


EASTERN = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")


@dataclass(frozen=True)
class ManipulationRealizedOutcome:
    symbol: str
    entry: float
    target: float
    trading_stop: float
    filled: bool
    outcome: str
    exit_price: float | None
    return_pct: float | None


@dataclass(frozen=True)
class QuickFlipRealizedOutcome:
    symbol: str
    entry: float
    take_profit_1: float
    take_profit_2: float

    filled: bool
    fill_time: datetime | None

    tp1_hit: bool
    tp2_hit: bool

    maximum_favorable_excursion_pct: float | None
    maximum_adverse_excursion_pct: float | None

    endpoint_price: float | None
    endpoint_return_pct: float | None


def evaluate_manipulation_realized_outcome(
    *,
    stock: Stock,
    bars: list[dict],
) -> ManipulationRealizedOutcome | None:
    """
    Evaluate the preserved Manipulation trade using the same
    entry/target/trading-stop geometry already produced by the
    strategy.

    This function does not modify Stock state.
    """
    if stock.signal != "INVEST":
        return None

    if (
        stock.limit_buy is None
        or stock.limit_sell is None
        or stock.trading_stop_loss is None
    ):
        return None

    entry = float(
        stock.limit_buy
    )

    target = float(
        stock.limit_sell
    )

    trading_stop = float(
        stock.trading_stop_loss
    )

    outcome = evaluate_entry_outcome(
        bars=bars,
        adjustment=0.0,
        entry=entry,
        target=target,
        trading_stop=trading_stop,
    )

    return ManipulationRealizedOutcome(
        symbol=stock.symbol,
        entry=entry,
        target=target,
        trading_stop=trading_stop,
        filled=outcome.filled,
        outcome=outcome.outcome,
        exit_price=outcome.exit_price,
        return_pct=outcome.return_pct,
    )


def _parse_bar_time(
    value: object,
) -> datetime:
    text = str(value).strip()

    if text.endswith("Z"):
        text = (
            text[:-1]
            + "+00:00"
        )

    timestamp = datetime.fromisoformat(
        text
    )

    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(
            tzinfo=UTC
        )

    return timestamp.astimezone(
        UTC
    )


def _normalize_signal_time(
    value: datetime,
) -> datetime:
    if value.tzinfo is None:
        value = value.replace(
            tzinfo=EASTERN
        )

    return value.astimezone(
        UTC
    )


def evaluate_quick_flip_realized_outcome(
    *,
    signal: QuickFlipSignal,
    minute_bars: list[dict],
) -> QuickFlipRealizedOutcome | None:
    """
    Evaluate a confirmed Quick Flip signal using chronological
    1-minute bars.

    Quick Flip intentionally has no automatic stop loss.

    Fill:
      first eligible minute whose high reaches the strategy entry.

    Eligibility starts at the confirmation time when available,
    otherwise at the reversal time.

    After fill:
      - record whether TP1 was touched;
      - record whether TP2 was touched;
      - calculate MFE and MAE;
      - calculate return using the final supplied minute close.

    The supplied bars determine the evaluation horizon. A future
    historical runner can therefore evaluate through 16:00 ET
    while still requiring the setup itself to occur before the
    existing 11:00 ET strategy cutoff.

    Because 1-minute OHLC cannot reveal intraminute sequencing,
    the fill minute is included in MFE/MAE. This makes MAE
    conservative when the minute traded below entry before the
    breakout actually occurred.
    """
    if signal.signal != "INVEST":
        return None

    if (
        signal.entry_price is None
        or signal.take_profit_1 is None
        or signal.take_profit_2 is None
    ):
        return None

    entry = float(
        signal.entry_price
    )

    tp1 = float(
        signal.take_profit_1
    )

    tp2 = float(
        signal.take_profit_2
    )

    if entry <= 0:
        return None

    start_time = (
        signal.confirmation_time
        or signal.reversal_time
    )

    if start_time is None:
        return None

    start_utc = _normalize_signal_time(
        start_time
    )

    parsed = []

    for bar in minute_bars:
        required = {
            "t",
            "o",
            "h",
            "l",
            "c",
        }

        if not required.issubset(
            bar
        ):
            continue

        try:
            timestamp = _parse_bar_time(
                bar["t"]
            )

            high = float(
                bar["h"]
            )

            low = float(
                bar["l"]
            )

            close = float(
                bar["c"]
            )

        except (
            TypeError,
            ValueError,
        ):
            continue

        if timestamp < start_utc:
            continue

        parsed.append(
            (
                timestamp,
                high,
                low,
                close,
            )
        )

    parsed.sort(
        key=lambda row: row[0]
    )

    fill_index = None

    for index, row in enumerate(
        parsed
    ):
        if row[1] >= entry:
            fill_index = index
            break

    if fill_index is None:
        return QuickFlipRealizedOutcome(
            symbol=signal.symbol,
            entry=entry,
            take_profit_1=tp1,
            take_profit_2=tp2,
            filled=False,
            fill_time=None,
            tp1_hit=False,
            tp2_hit=False,
            maximum_favorable_excursion_pct=None,
            maximum_adverse_excursion_pct=None,
            endpoint_price=None,
            endpoint_return_pct=None,
        )

    post_fill = parsed[
        fill_index:
    ]

    fill_time = post_fill[0][0]

    maximum_high = max(
        row[1]
        for row in post_fill
    )

    minimum_low = min(
        row[2]
        for row in post_fill
    )

    endpoint_price = float(
        post_fill[-1][3]
    )

    tp1_hit = any(
        row[1] >= tp1
        for row in post_fill
    )

    tp2_hit = any(
        row[1] >= tp2
        for row in post_fill
    )

    mfe_pct = (
        (
            maximum_high
            - entry
        )
        / entry
        * 100.0
    )

    mae_pct = (
        (
            minimum_low
            - entry
        )
        / entry
        * 100.0
    )

    endpoint_return_pct = (
        (
            endpoint_price
            - entry
        )
        / entry
        * 100.0
    )

    return QuickFlipRealizedOutcome(
        symbol=signal.symbol,
        entry=entry,
        take_profit_1=tp1,
        take_profit_2=tp2,
        filled=True,
        fill_time=fill_time,
        tp1_hit=tp1_hit,
        tp2_hit=tp2_hit,
        maximum_favorable_excursion_pct=round(
            mfe_pct,
            4,
        ),
        maximum_adverse_excursion_pct=round(
            mae_pct,
            4,
        ),
        endpoint_price=endpoint_price,
        endpoint_return_pct=round(
            endpoint_return_pct,
            4,
        ),
    )
