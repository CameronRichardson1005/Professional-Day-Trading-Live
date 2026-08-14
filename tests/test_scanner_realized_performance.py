from datetime import (
    date,
    datetime,
    timedelta,
)
from zoneinfo import ZoneInfo

from trading_bot.scanner_realized_performance import (
    aggregate_minute_bars_to_5m_dicts,
    evaluate_realized_strategy_observation,
    filter_quick_flip_monitor_minutes,
)


EASTERN = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")


def minute_bar(
    timestamp,
    *,
    open_price=10.20,
    high=10.20,
    low=10.20,
    close=10.20,
):
    return {
        "t": (
            timestamp
            .astimezone(UTC)
            .isoformat()
            .replace(
                "+00:00",
                "Z",
            )
        ),
        "o": open_price,
        "h": high,
        "l": low,
        "c": close,
        "v": 100,
    }


def complete_day():
    start = datetime(
        2026,
        3,
        2,
        9,
        30,
        tzinfo=EASTERN,
    )

    return [
        minute_bar(
            start
            + timedelta(
                minutes=offset
            )
        )
        for offset in range(390)
    ]


def set_bucket(
    bars,
    *,
    hour,
    minute,
    open_price,
    high,
    low,
    close,
):
    start = datetime(
        2026,
        3,
        2,
        hour,
        minute,
        tzinfo=EASTERN,
    )

    positions = {
        (
            datetime.fromisoformat(
                bar["t"].replace(
                    "Z",
                    "+00:00",
                )
            )
            .astimezone(EASTERN)
        ): index
        for index, bar in enumerate(
            bars
        )
    }

    timestamps = [
        start
        + timedelta(minutes=offset)
        for offset in range(5)
    ]

    for timestamp in timestamps:
        index = positions[
            timestamp
        ]

        bars[index] = minute_bar(
            timestamp,
            open_price=open_price,
            high=max(
                open_price,
                close,
            ),
            low=min(
                open_price,
                close,
            ),
            close=close,
        )

    middle = positions[
        timestamps[2]
    ]

    bars[middle]["h"] = high
    bars[middle]["l"] = low

    first = positions[
        timestamps[0]
    ]

    last = positions[
        timestamps[-1]
    ]

    bars[first]["o"] = open_price
    bars[last]["c"] = close


def opening_bar():
    return {
        "t": "2026-03-02T14:30:00Z",
        "o": 10.50,
        "h": 11.50,
        "l": 10.00,
        "c": 10.20,
        "v": 100000,
    }


def test_filter_quick_flip_minutes_is_0945_to_1100():
    bars = complete_day()

    selected = (
        filter_quick_flip_monitor_minutes(
            bars
        )
    )

    assert len(selected) == 75

    first = datetime.fromisoformat(
        selected[0]["t"].replace(
            "Z",
            "+00:00",
        )
    ).astimezone(EASTERN)

    last = datetime.fromisoformat(
        selected[-1]["t"].replace(
            "Z",
            "+00:00",
        )
    ).astimezone(EASTERN)

    assert (
        first.hour,
        first.minute,
    ) == (
        9,
        45,
    )

    assert (
        last.hour,
        last.minute,
    ) == (
        10,
        59,
    )


def test_five_minute_aggregation_requires_complete_bucket():
    bars = complete_day()

    aggregated = (
        aggregate_minute_bars_to_5m_dicts(
            bars
        )
    )

    assert len(aggregated) == 78

    bars = [
        bar
        for bar in bars
        if bar["t"]
        != "2026-03-02T15:01:00Z"
    ]

    aggregated = (
        aggregate_minute_bars_to_5m_dicts(
            bars
        )
    )

    assert len(aggregated) == 77


def test_realized_observation_uses_existing_strategies():
    bars = complete_day()

    # Previous red candle.
    set_bucket(
        bars,
        hour=9,
        minute=45,
        open_price=9.80,
        high=9.90,
        low=9.30,
        close=9.40,
    )

    # Bullish engulfing below the opening box.
    set_bucket(
        bars,
        hour=9,
        minute=50,
        open_price=9.35,
        high=9.95,
        low=9.20,
        close=9.90,
    )

    # Following candle confirms by breaking 9.95.
    set_bucket(
        bars,
        hour=9,
        minute=55,
        open_price=9.90,
        high=9.98,
        low=9.85,
        close=9.96,
    )

    observation = (
        evaluate_realized_strategy_observation(
            session=date(
                2026,
                3,
                2,
            ),
            symbol="TEST",
            opening_bar=opening_bar(),
            atr_14=1.0,
            minute_bars=bars,
        )
    )

    assert (
        observation.manipulation_signal
        == "INVEST"
    )

    # The early selloff fills Manipulation and
    # conservatively touches its trading stop.
    assert (
        observation.manipulation_outcome
        == "STOP"
    )

    assert (
        observation.quick_flip_signal
        == "INVEST"
    )

    assert (
        observation.quick_flip_pattern
        == "BULLISH_ENGULFING"
    )

    assert (
        observation.quick_flip_entry
        == 9.95
    )


    assert (
        observation.quick_flip_reversal_time
        is not None
    )

    reversal_time = (
        observation
        .quick_flip_reversal_time
        .astimezone(EASTERN)
    )

    assert (
        reversal_time.hour,
        reversal_time.minute,
    ) == (
        9,
        50,
    )

    assert (
        observation.quick_flip_confirmation_time
        is not None
    )

    confirmation_time = (
        observation
        .quick_flip_confirmation_time
        .astimezone(EASTERN)
    )

    assert (
        confirmation_time.hour,
        confirmation_time.minute,
    ) == (
        9,
        55,
    )

    assert (
        observation.quick_flip_filled
        is True
    )

    assert (
        observation.quick_flip_tp1_hit
        is True
    )

    assert (
        observation.quick_flip_tp2_hit
        is False
    )

    assert (
        observation.missing_minutes
        == 0
    )


def test_realized_observation_preserves_quality_flags():
    bars = complete_day()

    bars = [
        bar
        for bar in bars
        if bar["t"]
        != "2026-03-02T19:00:00Z"
    ]

    observation = (
        evaluate_realized_strategy_observation(
            session=date(
                2026,
                3,
                2,
            ),
            symbol="TEST",
            opening_bar=opening_bar(),
            atr_14=1.0,
            minute_bars=bars,
        )
    )

    assert (
        observation.missing_minutes
        == 1
    )

    assert (
        observation.missing_quick_flip_minutes
        == 0
    )

    assert (
        observation.quick_flip_signal_clean
        is True
    )

    assert (
        observation.post_opening_outcome_clean
        is False
    )
