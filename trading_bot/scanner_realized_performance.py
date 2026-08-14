from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from .models import Stock
from .quick_flip_monitor import (
    QuickFlipMonitor,
    aggregate_completed_5m_candles,
)
from .quick_flip_strategy import QuickFlipCandle
from .scanner_data_quality import (
    analyze_minute_session,
)
from .scanner_outcome_research import (
    evaluate_manipulation_realized_outcome,
    evaluate_quick_flip_realized_outcome,
)
from .strategy import ManipulationStrategy


EASTERN = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")


@dataclass(frozen=True)
class RealizedStrategyObservation:
    date: str
    symbol: str
    atr_14: float

    opening_open: float
    opening_high: float
    opening_low: float
    opening_close: float

    minute_bars: int
    missing_minutes: int
    missing_opening_minutes: int
    missing_quick_flip_minutes: int
    missing_post_1100_minutes: int

    quick_flip_signal_clean: bool
    post_opening_outcome_clean: bool

    manipulation_signal: str
    manipulation_entry: float | None
    manipulation_target: float | None
    manipulation_trading_stop: float | None
    manipulation_filled: bool | None
    manipulation_outcome: str | None
    manipulation_return_pct: float | None

    quick_flip_status: str
    quick_flip_signal: str
    quick_flip_pattern: str | None
    quick_flip_entry: float | None
    quick_flip_tp1: float | None
    quick_flip_tp2: float | None
    quick_flip_filled: bool | None
    quick_flip_fill_time: datetime | None
    quick_flip_tp1_hit: bool | None
    quick_flip_tp2_hit: bool | None
    quick_flip_mfe_pct: float | None
    quick_flip_mae_pct: float | None
    quick_flip_endpoint_price: float | None
    quick_flip_endpoint_return_pct: float | None

    # Optional causal timestamps added for realized research.
    #
    # Defaults preserve compatibility with older callers that
    # construct RealizedStrategyObservation directly.
    quick_flip_reversal_time: datetime | None = None
    quick_flip_confirmation_time: datetime | None = None


def _parse_timestamp(
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


def _quick_flip_opening_candle(
    opening_bar: dict,
) -> QuickFlipCandle:
    return QuickFlipCandle(
        timestamp=_parse_timestamp(
            opening_bar["t"]
        ),
        open=float(
            opening_bar["o"]
        ),
        high=float(
            opening_bar["h"]
        ),
        low=float(
            opening_bar["l"]
        ),
        close=float(
            opening_bar["c"]
        ),
        volume=float(
            opening_bar.get(
                "v",
                0,
            )
            or 0
        ),
    )


def filter_quick_flip_monitor_minutes(
    minute_bars: list[dict],
) -> list[dict]:
    """
    Quick Flip monitors only completed data from
    09:45 ET up to, but not including, 11:00 ET.

    The native Webull 15-minute opening candle is supplied
    separately and is not reconstructed from this list.
    """
    selected = []

    for bar in minute_bars:
        if "t" not in bar:
            continue

        try:
            local = (
                _parse_timestamp(
                    bar["t"]
                )
                .astimezone(
                    EASTERN
                )
            )
        except (
            TypeError,
            ValueError,
        ):
            continue

        minute_of_day = (
            local.hour * 60
            + local.minute
        )

        if (
            585
            <= minute_of_day
            < 660
        ):
            selected.append(
                bar
            )

    selected.sort(
        key=lambda bar: str(
            bar["t"]
        )
    )

    return selected


def aggregate_minute_bars_to_5m_dicts(
    minute_bars: list[dict],
) -> list[dict]:
    """
    Reuse the production Quick Flip five-minute aggregator.

    Only complete five-minute buckets are returned. This is
    deliberately conservative when historical minute data has
    a gap.
    """
    candles = (
        aggregate_completed_5m_candles(
            minute_bars
        )
    )

    return [
        {
            "t": (
                candle.timestamp
                .astimezone(UTC)
                .isoformat()
                .replace(
                    "+00:00",
                    "Z",
                )
            ),
            "o": candle.open,
            "h": candle.high,
            "l": candle.low,
            "c": candle.close,
            "v": candle.volume,
        }
        for candle in candles
    ]


def evaluate_realized_strategy_observation(
    *,
    session: date,
    symbol: str,
    opening_bar: dict,
    atr_14: float,
    minute_bars: list[dict],
    manipulation_strategy: (
        ManipulationStrategy | None
    ) = None,
    quick_flip_monitor: (
        QuickFlipMonitor | None
    ) = None,
) -> RealizedStrategyObservation:
    """
    Evaluate both preserved strategies for one symbol/session.

    This is research-only:
    - no Sheets writes;
    - no dashboard publishing;
    - no Webull previews;
    - no order submission;
    - no production scanner changes.

    Strategy logic is delegated to the existing production
    strategy classes so research does not maintain a second
    implementation of the trading rules.
    """
    if atr_14 <= 0:
        raise ValueError(
            "ATR14 must be positive."
        )

    manipulation_strategy = (
        manipulation_strategy
        or ManipulationStrategy()
    )

    quick_flip_monitor = (
        quick_flip_monitor
        or QuickFlipMonitor()
    )

    quality = analyze_minute_session(
        session=session,
        bars=minute_bars,
    )

    stock = Stock(
        symbol=symbol
    )

    stock = (
        manipulation_strategy.evaluate(
            stock,
            opening_bar,
            float(atr_14),
        )
    )

    five_minute_bars = (
        aggregate_minute_bars_to_5m_dicts(
            minute_bars
        )
    )

    manipulation_outcome = (
        evaluate_manipulation_realized_outcome(
            stock=stock,
            bars=five_minute_bars,
        )
    )

    quick_flip_minutes = (
        filter_quick_flip_monitor_minutes(
            minute_bars
        )
    )

    quick_flip_result = (
        quick_flip_monitor.evaluate_minute_bars(
            symbol=symbol,
            opening_bar=(
                _quick_flip_opening_candle(
                    opening_bar
                )
            ),
            atr_14=float(
                atr_14
            ),
            minute_bars=(
                quick_flip_minutes
            ),
            cutoff_reached=True,
        )
    )

    quick_flip_signal = (
        quick_flip_result.signal
    )

    quick_flip_outcome = None

    if quick_flip_signal is not None:
        quick_flip_outcome = (
            evaluate_quick_flip_realized_outcome(
                signal=quick_flip_signal,
                minute_bars=minute_bars,
            )
        )

    return RealizedStrategyObservation(
        date=session.isoformat(),
        symbol=symbol,
        atr_14=float(
            atr_14
        ),
        opening_open=float(
            opening_bar["o"]
        ),
        opening_high=float(
            opening_bar["h"]
        ),
        opening_low=float(
            opening_bar["l"]
        ),
        opening_close=float(
            opening_bar["c"]
        ),
        minute_bars=(
            quality.observed_regular_minutes
        ),
        missing_minutes=(
            quality.missing_total
        ),
        missing_opening_minutes=(
            quality.missing_opening_minutes
        ),
        missing_quick_flip_minutes=(
            quality.missing_quick_flip_minutes
        ),
        missing_post_1100_minutes=(
            quality.missing_post_1100_minutes
        ),
        quick_flip_signal_clean=(
            quality.quick_flip_signal_clean
        ),
        post_opening_outcome_clean=(
            quality.post_opening_outcome_clean
        ),
        manipulation_signal=(
            stock.signal
        ),
        manipulation_entry=(
            stock.limit_buy
        ),
        manipulation_target=(
            stock.limit_sell
        ),
        manipulation_trading_stop=(
            stock.trading_stop_loss
        ),
        manipulation_filled=(
            manipulation_outcome.filled
            if manipulation_outcome
            is not None
            else None
        ),
        manipulation_outcome=(
            manipulation_outcome.outcome
            if manipulation_outcome
            is not None
            else None
        ),
        manipulation_return_pct=(
            manipulation_outcome.return_pct
            if manipulation_outcome
            is not None
            else None
        ),
        quick_flip_status=(
            quick_flip_result.status
        ),
        quick_flip_signal=(
            quick_flip_signal.signal
            if quick_flip_signal
            is not None
            else "NO INVEST"
        ),
        quick_flip_pattern=(
            quick_flip_signal.pattern
            if quick_flip_signal
            is not None
            else None
        ),
        quick_flip_entry=(
            quick_flip_signal.entry_price
            if quick_flip_signal
            is not None
            else None
        ),
        quick_flip_tp1=(
            quick_flip_signal.take_profit_1
            if quick_flip_signal
            is not None
            else None
        ),
        quick_flip_tp2=(
            quick_flip_signal.take_profit_2
            if quick_flip_signal
            is not None
            else None
        ),
        quick_flip_reversal_time=(
            quick_flip_signal.reversal_time
            if quick_flip_signal
            is not None
            else None
        ),
        quick_flip_confirmation_time=(
            quick_flip_signal.confirmation_time
            if quick_flip_signal
            is not None
            else None
        ),
        quick_flip_filled=(
            quick_flip_outcome.filled
            if quick_flip_outcome
            is not None
            else None
        ),
        quick_flip_fill_time=(
            quick_flip_outcome.fill_time
            if quick_flip_outcome
            is not None
            else None
        ),
        quick_flip_tp1_hit=(
            quick_flip_outcome.tp1_hit
            if quick_flip_outcome
            is not None
            else None
        ),
        quick_flip_tp2_hit=(
            quick_flip_outcome.tp2_hit
            if quick_flip_outcome
            is not None
            else None
        ),
        quick_flip_mfe_pct=(
            quick_flip_outcome
            .maximum_favorable_excursion_pct
            if quick_flip_outcome
            is not None
            else None
        ),
        quick_flip_mae_pct=(
            quick_flip_outcome
            .maximum_adverse_excursion_pct
            if quick_flip_outcome
            is not None
            else None
        ),
        quick_flip_endpoint_price=(
            quick_flip_outcome.endpoint_price
            if quick_flip_outcome
            is not None
            else None
        ),
        quick_flip_endpoint_return_pct=(
            quick_flip_outcome
            .endpoint_return_pct
            if quick_flip_outcome
            is not None
            else None
        ),
    )
