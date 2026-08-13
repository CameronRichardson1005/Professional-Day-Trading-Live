from dataclasses import dataclass

from .manipulation_selling_pressure import (
    calculate_close_location,
    calculate_relative_volume,
)
from .manipulation_selling_pressure_backtest import (
    calculate_research_trading_stop,
)


SELLING_PRESSURE_CLOSE_THRESHOLD = 0.20
SELLING_PRESSURE_RELATIVE_VOLUME_THRESHOLD = 2.00
SELLING_PRESSURE_ENTRY_ADJUSTMENT = 0.05

VARIANT_A_STOP_MULTIPLIER = 1.00
VARIANT_B_STOP_MULTIPLIER = 1.25


@dataclass(frozen=True)
class ManipulationSellingPressureShadow:
    symbol: str

    close_location: float
    relative_volume: float

    normal_entry: float
    adaptive_entry: float
    target: float

    variant_a_stop: float
    variant_b_stop: float

    variant_a_outcome: str = "PENDING"
    variant_b_outcome: str = "PENDING"


def build_selling_pressure_shadow(
    *,
    stock,
    average_opening_volume: float,
) -> ManipulationSellingPressureShadow | None:
    """
    Build a research-only selling-pressure shadow setup.

    This function NEVER modifies the Stock object.

    Trigger:
    - active Manipulation INVEST signal
    - Close Location <= 20%
    - Relative opening volume >= 2.00x

    Research variants:
    A:
        adaptive entry 5% of opening range below normal
        current 1.00x stop distance

    B:
        same adaptive entry
        1.25x current stop distance
    """
    if stock.signal != "INVEST":
        return None

    opening_bar = stock.opening_bar

    if not isinstance(opening_bar, dict):
        return None

    high = float(opening_bar["h"])
    low = float(opening_bar["l"])
    close = float(opening_bar["c"])
    volume = float(
        opening_bar.get("v", 0)
        or 0
    )

    candle_range = high - low

    if candle_range <= 0:
        return None

    close_location = calculate_close_location(
        high=high,
        low=low,
        close=close,
    )

    relative_volume = calculate_relative_volume(
        current_volume=volume,
        average_opening_volume=average_opening_volume,
    )

    if relative_volume is None:
        return None

    triggered = (
        close_location
        <= SELLING_PRESSURE_CLOSE_THRESHOLD
        and relative_volume
        >= SELLING_PRESSURE_RELATIVE_VOLUME_THRESHOLD
    )

    if not triggered:
        return None

    normal_entry = float(stock.limit_buy)
    target = float(stock.limit_sell)

    adaptive_entry = (
        normal_entry
        - (
            candle_range
            * SELLING_PRESSURE_ENTRY_ADJUSTMENT
        )
    )

    variant_a_stop = (
        calculate_research_trading_stop(
            entry=adaptive_entry,
            target=target,
        )
    )

    risk_distance = (
        adaptive_entry
        - variant_a_stop
    )

    variant_b_stop = (
        adaptive_entry
        - (
            risk_distance
            * VARIANT_B_STOP_MULTIPLIER
        )
    )

    return ManipulationSellingPressureShadow(
        symbol=stock.symbol,
        close_location=round(
            close_location,
            6,
        ),
        relative_volume=round(
            relative_volume,
            6,
        ),
        normal_entry=round(
            normal_entry,
            4,
        ),
        adaptive_entry=round(
            adaptive_entry,
            4,
        ),
        target=round(
            target,
            4,
        ),
        variant_a_stop=round(
            variant_a_stop,
            4,
        ),
        variant_b_stop=round(
            variant_b_stop,
            4,
        ),
    )
