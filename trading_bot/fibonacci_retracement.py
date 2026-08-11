from __future__ import annotations

import csv
import math

from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


FIBONACCI_LEVELS = {
    "FIB_38_2": 0.382,
    "FIB_50_0": 0.500,
    "FIB_61_8": 0.618,
}

EASTERN = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")


@dataclass(frozen=True)
class RetracementSetup:
    date: str
    symbol: str
    data_feed: str
    fibonacci_level: str
    retracement_ratio: float

    setup_found: bool
    rejection_reason: str

    atr: float | None
    reference_price: float | None
    atr_pct: float | None

    impulse_start_time: str
    impulse_end_time: str
    impulse_start_price: float | None
    impulse_end_price: float | None
    impulse_size: float | None
    impulse_atr_multiple: float | None
    impulse_duration_minutes: int | None
    impulse_average_volume: float | None

    retracement_price: float | None
    retracement_touch_time: str
    retracement_touch_low: float | None
    retracement_depth_actual: float | None
    pullback_duration_minutes: int | None
    pullback_average_volume: float | None
    pullback_volume_ratio: float | None

    confirmation_time: str
    confirmation_open: float | None
    confirmation_high: float | None
    confirmation_low: float | None
    confirmation_close: float | None
    confirmation_body_pct: float | None

    session_vwap_at_confirmation: float | None
    confirmation_above_vwap: bool | None

    entry_price: float | None
    entry_time: str
    stop_price: float | None
    target_price: float | None
    reward_risk: float | None

    outcome: str
    exit_time: str
    exit_price: float | None
    exit_reason: str

    gross_return_pct: float | None
    net_return_pct: float | None
    maximum_favourable_excursion_pct: float | None
    maximum_adverse_excursion_pct: float | None

    detail: str


@dataclass(frozen=True)
class RetracementMetrics:
    setups: int
    entered_trades: int
    wins: int
    losses: int
    no_entry: int
    rejected_reward_risk: int
    win_rate_pct: float | None
    average_return_pct: float | None
    total_return_pct: float
    profit_factor: float | None
    expectancy_pct: float | None
    maximum_drawdown_pct_points: float


def _timestamp(bar: dict[str, Any]) -> datetime:
    value = datetime.fromisoformat(
        str(bar["t"]).replace("Z", "+00:00")
    )

    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)

    return value.astimezone(EASTERN)


def _time_label(bar: dict[str, Any]) -> str:
    return _timestamp(bar).strftime("%H:%M")


def _minutes_between(
    first: dict[str, Any],
    second: dict[str, Any],
) -> int:
    difference = _timestamp(second) - _timestamp(first)
    return max(0, int(difference.total_seconds() // 60))


def _average_volume(
    bars: list[dict[str, Any]],
) -> float | None:
    values = [
        float(bar["v"])
        for bar in bars
        if bar.get("v") is not None
    ]

    if not values:
        return None

    return sum(values) / len(values)


def _session_vwap(
    bars: list[dict[str, Any]],
) -> float | None:
    total_value = 0.0
    total_volume = 0.0

    for bar in bars:
        volume = bar.get("v")

        if volume is None:
            continue

        volume = float(volume)

        if volume <= 0:
            continue

        if bar.get("vw") is not None:
            price = float(bar["vw"])
        else:
            price = (
                float(bar["h"])
                + float(bar["l"])
                + float(bar["c"])
            ) / 3.0

        total_value += price * volume
        total_volume += volume

    if total_volume <= 0:
        return None

    return total_value / total_volume


def _maximum_drawdown(
    returns: list[float],
) -> float:
    cumulative = 0.0
    peak = 0.0
    maximum = 0.0

    for value in returns:
        cumulative += value
        peak = max(peak, cumulative)
        maximum = max(maximum, peak - cumulative)

    return maximum


def _empty_setup(
    *,
    date_str: str,
    symbol: str,
    data_feed: str,
    level_name: str,
    ratio: float,
    atr: float | None,
    reason: str,
) -> RetracementSetup:
    return RetracementSetup(
        date=date_str,
        symbol=symbol,
        data_feed=data_feed,
        fibonacci_level=level_name,
        retracement_ratio=ratio,
        setup_found=False,
        rejection_reason=reason,
        atr=atr,
        reference_price=None,
        atr_pct=None,
        impulse_start_time="",
        impulse_end_time="",
        impulse_start_price=None,
        impulse_end_price=None,
        impulse_size=None,
        impulse_atr_multiple=None,
        impulse_duration_minutes=None,
        impulse_average_volume=None,
        retracement_price=None,
        retracement_touch_time="",
        retracement_touch_low=None,
        retracement_depth_actual=None,
        pullback_duration_minutes=None,
        pullback_average_volume=None,
        pullback_volume_ratio=None,
        confirmation_time="",
        confirmation_open=None,
        confirmation_high=None,
        confirmation_low=None,
        confirmation_close=None,
        confirmation_body_pct=None,
        session_vwap_at_confirmation=None,
        confirmation_above_vwap=None,
        entry_price=None,
        entry_time="",
        stop_price=None,
        target_price=None,
        reward_risk=None,
        outcome="REJECTED",
        exit_time="",
        exit_price=None,
        exit_reason="",
        gross_return_pct=None,
        net_return_pct=None,
        maximum_favourable_excursion_pct=None,
        maximum_adverse_excursion_pct=None,
        detail=reason,
    )


def find_upward_impulse(
    bars: list[dict[str, Any]],
    *,
    atr: float,
    minimum_atr_multiple: float = 1.0,
) -> tuple[int, int] | None:
    """
    Find the first chronological low-to-later-high move that
    reaches the minimum ATR requirement by 10:30 ET.

    Selecting the first qualifying impulse prevents later
    pullback or recovery bars from being incorporated into
    the original impulse and avoids look-ahead bias.
    """
    candidates = [
        (index, bar)
        for index, bar in enumerate(bars)
        if (
            _timestamp(bar).hour < 10
            or (
                _timestamp(bar).hour == 10
                and _timestamp(bar).minute <= 30
            )
        )
    ]

    if len(candidates) < 2:
        return None

    running_low_index = candidates[0][0]
    running_low = float(candidates[0][1]["l"])
    required_move = atr * minimum_atr_multiple

    for index, bar in candidates[1:]:
        low = float(bar["l"])
        high = float(bar["h"])

        # A newly established low begins a new potential
        # impulse before the current bar is tested.
        if low < running_low:
            running_low = low
            running_low_index = index

        move = high - running_low

        if (
            index > running_low_index
            and move >= required_move
        ):
            return running_low_index, index

    return None


def find_upward_impulses(
    bars: list[dict[str, Any]],
    *,
    atr: float,
    minimum_atr_multiple: float = 1.0,
) -> list[tuple[int, int]]:
    """
    Find chronological, non-overlapping upward impulses.

    This is research-only. The active strategy continues to use
    find_upward_impulse(), which selects only the first qualifying
    impulse.

    After one impulse qualifies, the next search begins after that
    impulse's high bar. This avoids overlapping duplicate candidates
    while preserving chronological ordering and preventing look-ahead
    selection.
    """
    if atr <= 0 or minimum_atr_multiple <= 0:
        return []

    candidates = [
        (index, bar)
        for index, bar in enumerate(bars)
        if (
            _timestamp(bar).hour < 10
            or (
                _timestamp(bar).hour == 10
                and _timestamp(bar).minute <= 30
            )
        )
    ]

    if len(candidates) < 2:
        return []

    required_move = atr * minimum_atr_multiple
    impulses: list[tuple[int, int]] = []
    search_position = 0

    while search_position < len(candidates) - 1:
        running_low_index = candidates[search_position][0]
        running_low = float(
            candidates[search_position][1]["l"]
        )
        found_position = None

        for candidate_position in range(
            search_position + 1,
            len(candidates),
        ):
            index, bar = candidates[candidate_position]
            low = float(bar["l"])
            high = float(bar["h"])

            if low < running_low:
                running_low = low
                running_low_index = index

            move = high - running_low

            if (
                index > running_low_index
                and move >= required_move
            ):
                impulses.append(
                    (running_low_index, index)
                )
                found_position = candidate_position
                break

        if found_position is None:
            break

        # Begin the next independent search after the high bar
        # of the impulse that was just selected.
        search_position = found_position + 1

    return impulses


def _simulate_confirmed_trade(
    *,
    bars: list[dict[str, Any]],
    entry_price: float,
    stop_price: float,
    target_price: float,
    slippage_bps: float,
    commission_per_share: float,
) -> dict[str, Any]:
    entered = False
    entry_time = ""

    highest_after_entry = entry_price
    lowest_after_entry = entry_price

    for bar in bars:
        high = float(bar["h"])
        low = float(bar["l"])

        if not entered:
            if high < entry_price:
                continue

            entered = True
            entry_time = _time_label(bar)

        highest_after_entry = max(
            highest_after_entry,
            high,
        )
        lowest_after_entry = min(
            lowest_after_entry,
            low,
        )

        target_hit = high >= target_price
        stop_hit = low <= stop_price

        if stop_hit:
            return _closed_result(
                outcome="LOSS",
                entry_time=entry_time,
                exit_time=_time_label(bar),
                entry_price=entry_price,
                exit_price=stop_price,
                exit_reason="STOP",
                highest_price=highest_after_entry,
                lowest_price=lowest_after_entry,
                detail=(
                    "Target and stop touched in the same "
                    "minute; recorded conservatively as a loss."
                    if target_hit
                    else "Structural stop reached."
                ),
                slippage_bps=slippage_bps,
                commission_per_share=commission_per_share,
            )

        if target_hit:
            return _closed_result(
                outcome="WIN",
                entry_time=entry_time,
                exit_time=_time_label(bar),
                entry_price=entry_price,
                exit_price=target_price,
                exit_reason="IMPULSE_HIGH",
                highest_price=highest_after_entry,
                lowest_price=lowest_after_entry,
                detail="Previous impulse high was reached.",
                slippage_bps=slippage_bps,
                commission_per_share=commission_per_share,
            )

    if not entered:
        return {
            "outcome": "NO ENTRY",
            "entry_time": "",
            "exit_time": "",
            "exit_price": None,
            "exit_reason": "",
            "gross_return_pct": None,
            "net_return_pct": None,
            "mfe_pct": None,
            "mae_pct": None,
            "detail": (
                "Confirmation breakout entry was not reached."
            ),
        }

    if not bars:
        return {
            "outcome": "UNRESOLVED",
            "entry_time": entry_time,
            "exit_time": "",
            "exit_price": None,
            "exit_reason": "",
            "gross_return_pct": None,
            "net_return_pct": None,
            "mfe_pct": None,
            "mae_pct": None,
            "detail": "No bars were available after entry.",
        }

    final_bar = bars[-1]
    final_price = float(final_bar["c"])

    result = _closed_result(
        outcome="",
        entry_time=entry_time,
        exit_time=_time_label(final_bar),
        entry_price=entry_price,
        exit_price=final_price,
        exit_reason="EOD",
        highest_price=highest_after_entry,
        lowest_price=lowest_after_entry,
        detail="Closed at the final available session price.",
        slippage_bps=slippage_bps,
        commission_per_share=commission_per_share,
    )

    result["outcome"] = (
        "WIN"
        if float(result["net_return_pct"]) >= 0
        else "LOSS"
    )

    return result


def stopped_out_then_target(
    *,
    bars: list[dict[str, Any]],
    entry_price: float,
    stop_price: float,
    target_price: float,
) -> bool:
    """
    Return True when an entered trade reaches its stop first and
    later reaches the target during the remaining available bars.

    This is a research diagnostic only. It does not alter the
    conservative stop-first trade outcome.
    """
    entered = False
    stopped = False

    for bar in bars:
        high = float(bar["h"])
        low = float(bar["l"])

        if not entered:
            if high < entry_price:
                continue

            entered = True

        if not stopped:
            stop_hit = low <= stop_price
            target_hit = high >= target_price

            if stop_hit:
                stopped = True

                # Same-minute stop and target remains conservative.
                # A later bar must reach the target for this diagnostic.
                continue

            if target_hit:
                return False

        elif high >= target_price:
            return True

    return False


def _closed_result(
    *,
    outcome: str,
    entry_time: str,
    exit_time: str,
    entry_price: float,
    exit_price: float,
    exit_reason: str,
    highest_price: float,
    lowest_price: float,
    detail: str,
    slippage_bps: float,
    commission_per_share: float,
) -> dict[str, Any]:
    slippage_rate = slippage_bps / 10_000.0

    effective_entry = entry_price * (
        1.0 + slippage_rate
    )
    effective_exit = exit_price * (
        1.0 - slippage_rate
    )

    gross_return = (
        (exit_price - entry_price)
        / entry_price
        * 100.0
    )

    net_pnl = (
        effective_exit
        - effective_entry
        - commission_per_share * 2.0
    )

    net_return = (
        net_pnl / effective_entry * 100.0
    )

    mfe = (
        (highest_price - entry_price)
        / entry_price
        * 100.0
    )

    mae = (
        (lowest_price - entry_price)
        / entry_price
        * 100.0
    )

    return {
        "outcome": outcome,
        "entry_time": entry_time,
        "exit_time": exit_time,
        "exit_price": exit_price,
        "exit_reason": exit_reason,
        "gross_return_pct": round(
            gross_return,
            6,
        ),
        "net_return_pct": round(
            net_return,
            6,
        ),
        "mfe_pct": round(mfe, 6),
        "mae_pct": round(mae, 6),
        "detail": detail,
    }


def analyse_retracement_level(
    *,
    date_str: str,
    symbol: str,
    data_feed: str,
    bars: list[dict[str, Any]],
    atr: float | None,
    level_name: str,
    ratio: float,
    minimum_impulse_atr: float = 1.0,
    minimum_impulse_duration_minutes: int = 0,
    zone_tolerance_ratio: float = 0.02,
    minimum_reward_risk: float = 1.5,
    maximum_confirmation_minutes: int = 15,
    tick_size: float = 0.01,
    stop_buffer_atr: float | None = None,
    slippage_bps: float = 0.0,
    commission_per_share: float = 0.0,
    impulse_indices: tuple[int, int] | None = None,
) -> RetracementSetup:
    bars = sorted(bars, key=lambda bar: str(bar["t"]))

    if minimum_impulse_duration_minutes < 0:
        raise ValueError(
            "Minimum impulse duration cannot be negative."
        )

    if stop_buffer_atr is not None and stop_buffer_atr < 0:
        raise ValueError(
            "ATR stop buffer cannot be negative."
        )

    if atr is None or atr <= 0:
        return _empty_setup(
            date_str=date_str,
            symbol=symbol,
            data_feed=data_feed,
            level_name=level_name,
            ratio=ratio,
            atr=atr,
            reason="ATR_UNAVAILABLE",
        )

    impulse = (
        impulse_indices
        if impulse_indices is not None
        else find_upward_impulse(
            bars,
            atr=atr,
            minimum_atr_multiple=minimum_impulse_atr,
        )
    )

    if impulse is None:
        return _empty_setup(
            date_str=date_str,
            symbol=symbol,
            data_feed=data_feed,
            level_name=level_name,
            ratio=ratio,
            atr=atr,
            reason="NO_QUALIFYING_UPWARD_IMPULSE",
        )

    low_index, high_index = impulse

    if (
        low_index < 0
        or high_index >= len(bars)
        or high_index <= low_index
    ):
        return _empty_setup(
            date_str=date_str,
            symbol=symbol,
            data_feed=data_feed,
            level_name=level_name,
            ratio=ratio,
            atr=atr,
            reason="INVALID_IMPULSE_INDICES",
        )

    impulse_low_bar = bars[low_index]
    impulse_high_bar = bars[high_index]

    impulse_low = float(impulse_low_bar["l"])
    impulse_high = float(impulse_high_bar["h"])
    impulse_size = impulse_high - impulse_low
    impulse_duration_minutes = _minutes_between(
        impulse_low_bar,
        impulse_high_bar,
    )

    if (
        impulse_duration_minutes
        < minimum_impulse_duration_minutes
    ):
        return _empty_setup(
            date_str=date_str,
            symbol=symbol,
            data_feed=data_feed,
            level_name=level_name,
            ratio=ratio,
            atr=atr,
            reason=(
                "IMPULSE_DURATION_BELOW_"
                f"{minimum_impulse_duration_minutes}_MINUTES"
            ),
        )

    retracement_price = (
        impulse_high - impulse_size * ratio
    )
    tolerance = impulse_size * zone_tolerance_ratio

    touch_index = None

    for index in range(high_index + 1, len(bars)):
        bar = bars[index]
        low = float(bar["l"])
        high = float(bar["h"])

        if (
            low <= retracement_price + tolerance
            and high >= retracement_price - tolerance
        ):
            touch_index = index
            break

    if touch_index is None:
        return _empty_setup(
            date_str=date_str,
            symbol=symbol,
            data_feed=data_feed,
            level_name=level_name,
            ratio=ratio,
            atr=atr,
            reason="RETRACEMENT_ZONE_NOT_TOUCHED",
        )

    confirmation_index = None
    confirmation_limit = min(
        len(bars),
        touch_index + maximum_confirmation_minutes + 1,
    )

    for index in range(
        touch_index + 1,
        confirmation_limit,
    ):
        bar = bars[index]

        bullish = float(bar["c"]) > float(bar["o"])
        closes_above_level = (
            float(bar["c"]) > retracement_price
        )

        if bullish and closes_above_level:
            confirmation_index = index
            break

    if confirmation_index is None:
        return _empty_setup(
            date_str=date_str,
            symbol=symbol,
            data_feed=data_feed,
            level_name=level_name,
            ratio=ratio,
            atr=atr,
            reason="NO_BULLISH_CONFIRMATION",
        )

    touch_bar = bars[touch_index]
    confirmation_bar = bars[confirmation_index]

    pullback_bars = bars[
        high_index + 1:confirmation_index + 1
    ]
    impulse_bars = bars[
        low_index:high_index + 1
    ]

    pullback_low = min(
        float(bar["l"])
        for bar in bars[
            touch_index:confirmation_index + 1
        ]
    )

    entry_price = (
        float(confirmation_bar["h"]) + tick_size
    )

    stop_buffer = (
        tick_size
        if stop_buffer_atr is None
        else max(
            tick_size,
            atr * stop_buffer_atr,
        )
    )

    stop_price = pullback_low - stop_buffer
    target_price = impulse_high

    risk = entry_price - stop_price
    reward = target_price - entry_price

    reward_risk = (
        reward / risk
        if risk > 0
        else None
    )

    if (
        reward_risk is None
        or reward_risk < minimum_reward_risk
    ):
        result = {
            "outcome": "REJECTED_RR",
            "entry_time": "",
            "exit_time": "",
            "exit_price": None,
            "exit_reason": "",
            "gross_return_pct": None,
            "net_return_pct": None,
            "mfe_pct": None,
            "mae_pct": None,
            "detail": (
                "Reward-to-risk was below "
                f"{minimum_reward_risk:.2f}."
            ),
        }
        rejection_reason = "REWARD_RISK_BELOW_MINIMUM"
        setup_found = False
    else:
        result = _simulate_confirmed_trade(
            bars=bars[confirmation_index + 1:],
            entry_price=entry_price,
            stop_price=stop_price,
            target_price=target_price,
            slippage_bps=slippage_bps,
            commission_per_share=commission_per_share,
        )
        rejection_reason = ""
        setup_found = True

    impulse_volume = _average_volume(
        impulse_bars
    )
    pullback_volume = _average_volume(
        pullback_bars
    )

    volume_ratio = (
        pullback_volume / impulse_volume
        if (
            pullback_volume is not None
            and impulse_volume not in {None, 0.0}
        )
        else None
    )

    session_vwap = _session_vwap(
        bars[:confirmation_index + 1]
    )

    confirmation_open = float(
        confirmation_bar["o"]
    )
    confirmation_close = float(
        confirmation_bar["c"]
    )

    confirmation_body_pct = (
        (
            confirmation_close
            - confirmation_open
        )
        / confirmation_open
        * 100.0
        if confirmation_open
        else None
    )

    actual_depth = (
        (impulse_high - float(touch_bar["l"]))
        / impulse_size
        if impulse_size > 0
        else None
    )

    return RetracementSetup(
        date=date_str,
        symbol=symbol,
        data_feed=data_feed,
        fibonacci_level=level_name,
        retracement_ratio=ratio,
        setup_found=setup_found,
        rejection_reason=rejection_reason,
        atr=atr,
        reference_price=impulse_high,
        atr_pct=(
            atr / impulse_high * 100.0
            if impulse_high
            else None
        ),
        impulse_start_time=_time_label(
            impulse_low_bar
        ),
        impulse_end_time=_time_label(
            impulse_high_bar
        ),
        impulse_start_price=impulse_low,
        impulse_end_price=impulse_high,
        impulse_size=impulse_size,
        impulse_atr_multiple=(
            impulse_size / atr
        ),
        impulse_duration_minutes=(
            impulse_duration_minutes
        ),
        impulse_average_volume=impulse_volume,
        retracement_price=retracement_price,
        retracement_touch_time=_time_label(
            touch_bar
        ),
        retracement_touch_low=float(
            touch_bar["l"]
        ),
        retracement_depth_actual=actual_depth,
        pullback_duration_minutes=_minutes_between(
            impulse_high_bar,
            confirmation_bar,
        ),
        pullback_average_volume=pullback_volume,
        pullback_volume_ratio=volume_ratio,
        confirmation_time=_time_label(
            confirmation_bar
        ),
        confirmation_open=confirmation_open,
        confirmation_high=float(
            confirmation_bar["h"]
        ),
        confirmation_low=float(
            confirmation_bar["l"]
        ),
        confirmation_close=confirmation_close,
        confirmation_body_pct=(
            confirmation_body_pct
        ),
        session_vwap_at_confirmation=session_vwap,
        confirmation_above_vwap=(
            confirmation_close > session_vwap
            if session_vwap is not None
            else None
        ),
        entry_price=entry_price,
        entry_time=str(result["entry_time"]),
        stop_price=stop_price,
        target_price=target_price,
        reward_risk=reward_risk,
        outcome=str(result["outcome"]),
        exit_time=str(result["exit_time"]),
        exit_price=result["exit_price"],
        exit_reason=str(result["exit_reason"]),
        gross_return_pct=(
            result["gross_return_pct"]
        ),
        net_return_pct=result["net_return_pct"],
        maximum_favourable_excursion_pct=(
            result["mfe_pct"]
        ),
        maximum_adverse_excursion_pct=(
            result["mae_pct"]
        ),
        detail=str(result["detail"]),
    )


def analyse_symbol_day(
    *,
    date_str: str,
    symbol: str,
    data_feed: str,
    bars: list[dict[str, Any]],
    atr: float | None,
    minimum_impulse_atr: float = 1.0,
    minimum_impulse_duration_minutes: int = 0,
    stop_buffer_atr: float | None = None,
    slippage_bps: float = 0.0,
    commission_per_share: float = 0.0,
) -> list[RetracementSetup]:
    return [
        analyse_retracement_level(
            date_str=date_str,
            symbol=symbol,
            data_feed=data_feed,
            bars=bars,
            atr=atr,
            level_name=level_name,
            ratio=ratio,
            minimum_impulse_atr=minimum_impulse_atr,
            minimum_impulse_duration_minutes=(
                minimum_impulse_duration_minutes
            ),
            stop_buffer_atr=stop_buffer_atr,
            slippage_bps=slippage_bps,
            commission_per_share=commission_per_share,
        )
        for level_name, ratio in (
            FIBONACCI_LEVELS.items()
        )
    ]


def analyse_symbol_day_multiple_impulses(
    *,
    date_str: str,
    symbol: str,
    data_feed: str,
    bars: list[dict[str, Any]],
    atr: float | None,
    minimum_impulse_atr: float = 1.0,
    minimum_impulse_duration_minutes: int = 0,
    stop_buffer_atr: float | None = None,
    slippage_bps: float = 0.0,
    commission_per_share: float = 0.0,
) -> list[RetracementSetup]:
    """
    Evaluate each chronological non-overlapping impulse for every
    Fibonacci level.

    This function is research-only and is not used by the active
    live strategy, Google Sheets, dashboard publishing, Webull
    previews, or order generation.
    """
    sorted_bars = sorted(
        bars,
        key=lambda bar: str(bar["t"]),
    )

    if atr is None or atr <= 0:
        return [
            _empty_setup(
                date_str=date_str,
                symbol=symbol,
                data_feed=data_feed,
                level_name=level_name,
                ratio=ratio,
                atr=atr,
                reason="ATR_UNAVAILABLE",
            )
            for level_name, ratio
            in FIBONACCI_LEVELS.items()
        ]

    impulses = find_upward_impulses(
        sorted_bars,
        atr=atr,
        minimum_atr_multiple=minimum_impulse_atr,
    )

    if not impulses:
        return [
            _empty_setup(
                date_str=date_str,
                symbol=symbol,
                data_feed=data_feed,
                level_name=level_name,
                ratio=ratio,
                atr=atr,
                reason="NO_QUALIFYING_UPWARD_IMPULSE",
            )
            for level_name, ratio
            in FIBONACCI_LEVELS.items()
        ]

    records: list[RetracementSetup] = []

    for impulse_indices in impulses:
        for level_name, ratio in (
            FIBONACCI_LEVELS.items()
        ):
            records.append(
                analyse_retracement_level(
                    date_str=date_str,
                    symbol=symbol,
                    data_feed=data_feed,
                    bars=sorted_bars,
                    atr=atr,
                    level_name=level_name,
                    ratio=ratio,
                    minimum_impulse_atr=(
                        minimum_impulse_atr
                    ),
                    minimum_impulse_duration_minutes=(
                        minimum_impulse_duration_minutes
                    ),
                    stop_buffer_atr=stop_buffer_atr,
                    slippage_bps=slippage_bps,
                    commission_per_share=(
                        commission_per_share
                    ),
                    impulse_indices=impulse_indices,
                )
            )

    return records


def metrics_for(
    records: list[RetracementSetup],
) -> RetracementMetrics:
    entered = [
        record
        for record in records
        if record.outcome in {"WIN", "LOSS"}
    ]

    returns = [
        float(record.net_return_pct)
        for record in entered
        if record.net_return_pct is not None
    ]

    wins = sum(
        record.outcome == "WIN"
        for record in entered
    )
    losses = sum(
        record.outcome == "LOSS"
        for record in entered
    )

    positive = sum(
        value
        for value in returns
        if value > 0
    )
    negative = abs(
        sum(
            value
            for value in returns
            if value < 0
        )
    )

    return RetracementMetrics(
        setups=sum(
            record.setup_found
            for record in records
        ),
        entered_trades=len(entered),
        wins=wins,
        losses=losses,
        no_entry=sum(
            record.outcome == "NO ENTRY"
            for record in records
        ),
        rejected_reward_risk=sum(
            record.outcome == "REJECTED_RR"
            for record in records
        ),
        win_rate_pct=(
            wins / len(entered) * 100.0
            if entered
            else None
        ),
        average_return_pct=(
            sum(returns) / len(returns)
            if returns
            else None
        ),
        total_return_pct=sum(returns),
        profit_factor=(
            positive / negative
            if negative
            else None
        ),
        expectancy_pct=(
            sum(returns) / len(entered)
            if entered
            else None
        ),
        maximum_drawdown_pct_points=(
            _maximum_drawdown(returns)
        ),
    )


class FibonacciRetracementReport:
    def __init__(
        self,
        *,
        start_date: str,
        end_date: str,
        data_feed: str,
        slippage_bps: float,
        commission_per_share: float,
    ) -> None:
        self.start_date = start_date
        self.end_date = end_date
        self.data_feed = data_feed
        self.slippage_bps = slippage_bps
        self.commission_per_share = (
            commission_per_share
        )
        self.records: list[RetracementSetup] = []
        self.failed_sessions: list[
            tuple[str, str]
        ] = []

    def add_failure(
        self,
        date_str: str,
        error: Exception,
    ) -> None:
        self.failed_sessions.append(
            (date_str, str(error))
        )

    def summary_rows(
        self,
    ) -> list[dict[str, Any]]:
        rows = []

        for level_name in FIBONACCI_LEVELS:
            selected = [
                record
                for record in self.records
                if record.fibonacci_level == level_name
            ]

            rows.append({
                "scope": "LEVEL",
                "symbol": "",
                "fibonacci_level": level_name,
                **asdict(metrics_for(selected)),
            })

        symbols = sorted({
            record.symbol
            for record in self.records
        })

        for symbol in symbols:
            for level_name in FIBONACCI_LEVELS:
                selected = [
                    record
                    for record in self.records
                    if (
                        record.symbol == symbol
                        and record.fibonacci_level
                        == level_name
                    )
                ]

                rows.append({
                    "scope": "SYMBOL_LEVEL",
                    "symbol": symbol,
                    "fibonacci_level": level_name,
                    **asdict(metrics_for(selected)),
                })

        return rows

    def write_csv(
        self,
        output_directory: str | Path,
    ) -> tuple[Path, Path, Path]:
        output_directory = Path(output_directory)
        output_directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        stem = (
            f"fibonacci_retracement_"
            f"{self.start_date}_to_{self.end_date}"
        )

        detail_path = (
            output_directory
            / f"{stem}_details.csv"
        )
        summary_path = (
            output_directory
            / f"{stem}_summary.csv"
        )
        failures_path = (
            output_directory
            / f"{stem}_failures.csv"
        )

        fields = [
            field.name
            for field in (
                RetracementSetup
                .__dataclass_fields__
                .values()
            )
        ]

        with detail_path.open(
            "w",
            newline="",
            encoding="utf-8",
        ) as file:
            writer = csv.DictWriter(
                file,
                fieldnames=fields,
            )
            writer.writeheader()
            writer.writerows(
                asdict(record)
                for record in self.records
            )

        rows = self.summary_rows()

        with summary_path.open(
            "w",
            newline="",
            encoding="utf-8",
        ) as file:
            if rows:
                writer = csv.DictWriter(
                    file,
                    fieldnames=list(
                        rows[0].keys()
                    ),
                )
                writer.writeheader()
                writer.writerows(rows)

        with failures_path.open(
            "w",
            newline="",
            encoding="utf-8",
        ) as file:
            writer = csv.DictWriter(
                file,
                fieldnames=["date", "error"],
            )
            writer.writeheader()
            writer.writerows(
                {
                    "date": date_str,
                    "error": error,
                }
                for date_str, error
                in self.failed_sessions
            )

        return (
            detail_path,
            summary_path,
            failures_path,
        )
