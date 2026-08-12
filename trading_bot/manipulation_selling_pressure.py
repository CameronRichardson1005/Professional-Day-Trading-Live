from dataclasses import dataclass


DEFAULT_ENTRY_ADJUSTMENTS = (
    0.00,
    0.05,
    0.10,
    0.15,
    0.20,
    0.25,
)

STRONG_SELLING_CLOSE_LOCATION_MAX = 0.20
STRONG_SELLING_RELATIVE_VOLUME_MIN = 1.50


@dataclass(frozen=True)
class SellingPressureResult:
    close_location: float
    relative_volume: float | None
    strong_selling_pressure: bool
    entry_levels: dict[float, float]


def calculate_close_location(
    *,
    high: float,
    low: float,
    close: float,
) -> float:
    """
    Return where the close sits inside the candle range.

    0.0 = exactly at the low.
    1.0 = exactly at the high.
    """
    high = float(high)
    low = float(low)
    close = float(close)

    candle_range = high - low

    if candle_range <= 0:
        return 0.5

    location = (
        close - low
    ) / candle_range

    return max(
        0.0,
        min(1.0, location),
    )


def calculate_relative_volume(
    *,
    current_volume: float,
    average_opening_volume: float | None,
) -> float | None:
    """
    Compare today's opening 15-minute volume with the recent
    average opening 15-minute volume.
    """
    if average_opening_volume is None:
        return None

    current_volume = float(current_volume)
    average_opening_volume = float(
        average_opening_volume
    )

    if average_opening_volume <= 0:
        return None

    return (
        current_volume
        / average_opening_volume
    )


def has_strong_selling_pressure(
    *,
    close_location: float,
    relative_volume: float | None,
    close_location_max: float = (
        STRONG_SELLING_CLOSE_LOCATION_MAX
    ),
    relative_volume_min: float = (
        STRONG_SELLING_RELATIVE_VOLUME_MIN
    ),
) -> bool:
    """
    Strong selling pressure requires BOTH:

    1. Close in the bottom 20% of the opening range.
    2. Opening volume at least 1.5x its recent average.
    """
    if relative_volume is None:
        return False

    return (
        close_location <= close_location_max
        and relative_volume >= relative_volume_min
    )


def calculate_adjusted_entries(
    *,
    high: float,
    low: float,
    adjustments=DEFAULT_ENTRY_ADJUSTMENTS,
) -> dict[float, float]:
    """
    Generate research entry prices below the opening low.

    0.00 = existing strategy entry.
    0.15 = opening low minus 15% of opening range.
    """
    high = float(high)
    low = float(low)

    candle_range = high - low

    if candle_range < 0:
        raise ValueError(
            "Opening high cannot be below opening low."
        )

    return {
        float(adjustment): round(
            low - (
                candle_range
                * float(adjustment)
            ),
            4,
        )
        for adjustment in adjustments
    }


def evaluate_selling_pressure(
    *,
    opening_bar: dict,
    average_opening_volume: float | None,
) -> SellingPressureResult:
    """
    Evaluate selling pressure without changing the live
    Manipulation strategy.

    This function is research-only.
    """
    high = float(opening_bar["h"])
    low = float(opening_bar["l"])
    close = float(opening_bar["c"])
    volume = float(
        opening_bar.get("v", 0) or 0
    )

    close_location = (
        calculate_close_location(
            high=high,
            low=low,
            close=close,
        )
    )

    relative_volume = (
        calculate_relative_volume(
            current_volume=volume,
            average_opening_volume=(
                average_opening_volume
            ),
        )
    )

    strong_selling_pressure = (
        has_strong_selling_pressure(
            close_location=close_location,
            relative_volume=relative_volume,
        )
    )

    entry_levels = (
        calculate_adjusted_entries(
            high=high,
            low=low,
        )
    )

    return SellingPressureResult(
        close_location=round(
            close_location,
            6,
        ),
        relative_volume=(
            None
            if relative_volume is None
            else round(
                relative_volume,
                6,
            )
        ),
        strong_selling_pressure=(
            strong_selling_pressure
        ),
        entry_levels=entry_levels,
    )
