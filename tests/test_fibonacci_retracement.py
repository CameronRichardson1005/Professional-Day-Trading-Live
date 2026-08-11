from trading_bot.fibonacci_retracement import (
    analyse_retracement_level,
    analyse_symbol_day_multiple_impulses,
    find_upward_impulse,
    find_upward_impulses,
    metrics_for,
    stopped_out_then_target,
)


def bar(
    minute: int,
    *,
    open_price: float,
    high: float,
    low: float,
    close: float,
    volume: float = 1000,
):
    hour = 13 + (30 + minute) // 60
    minute_value = (30 + minute) % 60

    return {
        "t": (
            f"2026-07-30T{hour:02d}:"
            f"{minute_value:02d}:00Z"
        ),
        "o": open_price,
        "h": high,
        "l": low,
        "c": close,
        "v": volume,
        "vw": close,
    }


def test_finds_chronological_upward_impulse():
    bars = [
        bar(
            0,
            open_price=10.00,
            high=10.05,
            low=9.95,
            close=10.02,
        ),
        bar(
            1,
            open_price=10.02,
            high=10.40,
            low=10.00,
            close=10.35,
        ),
        bar(
            2,
            open_price=10.35,
            high=11.10,
            low=10.30,
            close=11.00,
        ),
    ]

    result = find_upward_impulse(
        bars,
        atr=1.0,
        minimum_atr_multiple=1.0,
    )

    assert result == (0, 2)


def test_rejects_impulse_below_atr_requirement():
    bars = [
        bar(
            0,
            open_price=10.00,
            high=10.10,
            low=10.00,
            close=10.05,
        ),
        bar(
            1,
            open_price=10.05,
            high=10.40,
            low=10.03,
            close=10.30,
        ),
    ]

    assert find_upward_impulse(
        bars,
        atr=1.0,
        minimum_atr_multiple=1.0,
    ) is None


def test_detects_confirmed_50_percent_retracement():
    bars = [
        bar(
            0,
            open_price=10.00,
            high=10.10,
            low=10.00,
            close=10.08,
            volume=2000,
        ),
        bar(
            1,
            open_price=10.08,
            high=10.60,
            low=10.05,
            close=10.55,
            volume=2200,
        ),
        bar(
            2,
            open_price=10.55,
            high=11.20,
            low=10.50,
            close=11.10,
            volume=2500,
        ),
        bar(
            3,
            open_price=11.10,
            high=11.12,
            low=10.62,
            close=10.70,
            volume=1000,
        ),
        bar(
            4,
            open_price=10.68,
            high=10.85,
            low=10.60,
            close=10.82,
            volume=900,
        ),
        bar(
            5,
            open_price=10.82,
            high=10.90,
            low=10.75,
            close=10.88,
        ),
        bar(
            6,
            open_price=10.88,
            high=11.25,
            low=10.85,
            close=11.20,
        ),
    ]

    result = analyse_retracement_level(
        date_str="2026-07-30",
        symbol="TEST",
        data_feed="iex",
        bars=bars,
        atr=1.0,
        level_name="FIB_50_0",
        ratio=0.500,
        minimum_reward_risk=1.0,
    )

    assert result.setup_found
    assert result.confirmation_time == "09:34"
    assert result.entry_price == 10.86
    assert result.outcome == "WIN"
    assert result.exit_reason == "IMPULSE_HIGH"
    assert result.pullback_volume_ratio is not None
    assert result.pullback_volume_ratio < 1.0


def test_rejects_setup_without_confirmation():
    bars = [
        bar(
            0,
            open_price=10.00,
            high=10.10,
            low=10.00,
            close=10.05,
        ),
        bar(
            1,
            open_price=10.05,
            high=11.10,
            low=10.03,
            close=11.00,
        ),
        bar(
            2,
            open_price=11.00,
            high=11.02,
            low=10.50,
            close=10.55,
        ),
        bar(
            3,
            open_price=10.55,
            high=10.60,
            low=10.40,
            close=10.45,
        ),
    ]

    result = analyse_retracement_level(
        date_str="2026-07-30",
        symbol="TEST",
        data_feed="iex",
        bars=bars,
        atr=1.0,
        level_name="FIB_50_0",
        ratio=0.500,
    )

    assert not result.setup_found
    assert result.rejection_reason == (
        "NO_BULLISH_CONFIRMATION"
    )


def test_metrics_cover_profitable_and_losing_trades():
    winning_bars = [
        bar(
            0,
            open_price=10.00,
            high=10.10,
            low=10.00,
            close=10.08,
        ),
        bar(
            1,
            open_price=10.08,
            high=11.20,
            low=10.05,
            close=11.10,
        ),
        bar(
            2,
            open_price=11.10,
            high=11.12,
            low=10.60,
            close=10.65,
        ),
        bar(
            3,
            open_price=10.65,
            high=10.85,
            low=10.60,
            close=10.82,
        ),
        bar(
            4,
            open_price=10.82,
            high=11.25,
            low=10.80,
            close=11.20,
        ),
    ]

    result = analyse_retracement_level(
        date_str="2026-07-30",
        symbol="TEST",
        data_feed="iex",
        bars=winning_bars,
        atr=1.0,
        level_name="FIB_50_0",
        ratio=0.500,
        minimum_reward_risk=1.0,
    )

    metrics = metrics_for([result])

    assert metrics.setups == 1
    assert metrics.entered_trades == 1
    assert metrics.wins == 1
    assert metrics.losses == 0
    assert metrics.win_rate_pct == 100.0



def test_finds_multiple_non_overlapping_upward_impulses():
    bars = [
        bar(
            0,
            open_price=10.00,
            high=10.05,
            low=10.00,
            close=10.03,
        ),
        bar(
            1,
            open_price=10.03,
            high=10.60,
            low=10.02,
            close=10.55,
        ),
        bar(
            2,
            open_price=10.55,
            high=10.58,
            low=10.40,
            close=10.45,
        ),
        bar(
            3,
            open_price=10.45,
            high=10.48,
            low=10.40,
            close=10.44,
        ),
        bar(
            4,
            open_price=10.44,
            high=11.05,
            low=10.42,
            close=11.00,
        ),
    ]

    result = find_upward_impulses(
        bars,
        atr=1.0,
        minimum_atr_multiple=0.50,
    )

    assert result == [
        (0, 1),
        (2, 4),
    ]


def test_multiple_impulse_search_returns_independent_later_move():
    bars = [
        bar(
            0,
            open_price=10.00,
            high=10.05,
            low=10.00,
            close=10.04,
        ),
        bar(
            1,
            open_price=10.04,
            high=10.55,
            low=10.02,
            close=10.50,
        ),
        bar(
            2,
            open_price=10.50,
            high=10.90,
            low=10.45,
            close=10.85,
        ),
        bar(
            3,
            open_price=10.85,
            high=11.20,
            low=10.80,
            close=11.15,
        ),
    ]

    result = find_upward_impulses(
        bars,
        atr=1.0,
        minimum_atr_multiple=0.50,
    )

    assert result == [
        (0, 1),
        (2, 3),
    ]


def test_multiple_impulse_analysis_evaluates_each_impulse():
    bars = [
        bar(
            0,
            open_price=10.00,
            high=10.05,
            low=10.00,
            close=10.03,
            volume=2000,
        ),
        bar(
            1,
            open_price=10.03,
            high=10.60,
            low=10.02,
            close=10.55,
            volume=2200,
        ),
        bar(
            2,
            open_price=10.55,
            high=10.58,
            low=10.25,
            close=10.30,
            volume=900,
        ),
        bar(
            3,
            open_price=10.30,
            high=10.42,
            low=10.25,
            close=10.40,
            volume=800,
        ),
        bar(
            4,
            open_price=10.40,
            high=10.45,
            low=10.40,
            close=10.43,
            volume=1800,
        ),
        bar(
            5,
            open_price=10.43,
            high=11.05,
            low=10.42,
            close=11.00,
            volume=2000,
        ),
        bar(
            6,
            open_price=11.00,
            high=11.02,
            low=10.65,
            close=10.70,
            volume=700,
        ),
        bar(
            7,
            open_price=10.70,
            high=10.82,
            low=10.65,
            close=10.80,
            volume=650,
        ),
    ]

    records = analyse_symbol_day_multiple_impulses(
        date_str="2026-07-30",
        symbol="TEST",
        data_feed="iex",
        bars=bars,
        atr=1.0,
        minimum_impulse_atr=0.50,
    )

    # Two impulses multiplied by the three configured
    # Fibonacci retracement levels.
    assert len(records) == 6

    detected_impulses = find_upward_impulses(
        bars,
        atr=1.0,
        minimum_atr_multiple=0.50,
    )

    assert detected_impulses == [
        (0, 1),
        (2, 5),
    ]

    # Rejected retracement records currently use _empty_setup(),
    # which intentionally leaves impulse timestamps blank. Records
    # that progress far enough retain their selected impulse times.
    populated_impulse_pairs = {
        (
            record.impulse_start_time,
            record.impulse_end_time,
        )
        for record in records
        if record.impulse_start_time
    }

    assert populated_impulse_pairs == {
        ("09:30", "09:31"),
        ("09:32", "09:35"),
    }


def test_existing_single_impulse_behavior_is_unchanged():
    bars = [
        bar(
            0,
            open_price=10.00,
            high=10.05,
            low=10.00,
            close=10.03,
        ),
        bar(
            1,
            open_price=10.03,
            high=10.60,
            low=10.02,
            close=10.55,
        ),
        bar(
            2,
            open_price=10.55,
            high=10.58,
            low=10.40,
            close=10.45,
        ),
        bar(
            3,
            open_price=10.45,
            high=10.48,
            low=10.40,
            close=10.44,
        ),
        bar(
            4,
            open_price=10.44,
            high=11.05,
            low=10.42,
            close=11.00,
        ),
    ]

    assert find_upward_impulse(
        bars,
        atr=1.0,
        minimum_atr_multiple=0.50,
    ) == (0, 1)

    assert find_upward_impulses(
        bars,
        atr=1.0,
        minimum_atr_multiple=0.50,
    ) == [
        (0, 1),
        (2, 4),
    ]



def test_research_rejects_impulse_below_duration_requirement():
    bars = [
        bar(
            0,
            open_price=10.00,
            high=10.05,
            low=10.00,
            close=10.03,
        ),
        bar(
            5,
            open_price=10.03,
            high=10.65,
            low=10.02,
            close=10.60,
        ),
        bar(
            6,
            open_price=10.60,
            high=10.62,
            low=10.25,
            close=10.30,
        ),
        bar(
            7,
            open_price=10.30,
            high=10.45,
            low=10.25,
            close=10.42,
        ),
    ]

    result = analyse_retracement_level(
        date_str="2026-07-30",
        symbol="TEST",
        data_feed="iex",
        bars=bars,
        atr=1.0,
        level_name="FIB_61_8",
        ratio=0.618,
        minimum_impulse_atr=0.50,
        minimum_impulse_duration_minutes=10,
    )

    assert not result.setup_found
    assert result.rejection_reason == (
        "IMPULSE_DURATION_BELOW_10_MINUTES"
    )


def test_research_accepts_impulse_at_duration_requirement():
    bars = [
        bar(
            0,
            open_price=10.00,
            high=10.05,
            low=10.00,
            close=10.03,
        ),
        bar(
            10,
            open_price=10.03,
            high=10.65,
            low=10.02,
            close=10.60,
        ),
        bar(
            11,
            open_price=10.60,
            high=10.62,
            low=10.25,
            close=10.30,
        ),
        bar(
            12,
            open_price=10.30,
            high=10.45,
            low=10.25,
            close=10.42,
        ),
    ]

    result = analyse_retracement_level(
        date_str="2026-07-30",
        symbol="TEST",
        data_feed="iex",
        bars=bars,
        atr=1.0,
        level_name="FIB_61_8",
        ratio=0.618,
        minimum_impulse_atr=0.50,
        minimum_impulse_duration_minutes=10,
        minimum_reward_risk=0.0,
    )

    assert result.rejection_reason != (
        "IMPULSE_DURATION_BELOW_10_MINUTES"
    )
    assert result.impulse_duration_minutes == 10


def test_research_atr_stop_buffer_widens_stop():
    bars = [
        bar(
            0,
            open_price=10.00,
            high=10.05,
            low=10.00,
            close=10.03,
            volume=2000,
        ),
        bar(
            15,
            open_price=10.03,
            high=11.00,
            low=10.02,
            close=10.95,
            volume=2200,
        ),
        bar(
            16,
            open_price=10.95,
            high=10.97,
            low=10.35,
            close=10.40,
            volume=800,
        ),
        bar(
            17,
            open_price=10.40,
            high=10.55,
            low=10.35,
            close=10.52,
            volume=700,
        ),
        bar(
            18,
            open_price=10.52,
            high=10.70,
            low=10.50,
            close=10.68,
            volume=700,
        ),
    ]

    fixed = analyse_retracement_level(
        date_str="2026-07-30",
        symbol="TEST",
        data_feed="iex",
        bars=bars,
        atr=1.0,
        level_name="FIB_61_8",
        ratio=0.618,
        minimum_impulse_atr=0.50,
        minimum_impulse_duration_minutes=10,
        minimum_reward_risk=0.0,
    )

    atr_buffered = analyse_retracement_level(
        date_str="2026-07-30",
        symbol="TEST",
        data_feed="iex",
        bars=bars,
        atr=1.0,
        level_name="FIB_61_8",
        ratio=0.618,
        minimum_impulse_atr=0.50,
        minimum_impulse_duration_minutes=10,
        minimum_reward_risk=0.0,
        stop_buffer_atr=0.10,
    )

    assert fixed.stop_price is not None
    assert atr_buffered.stop_price is not None
    assert fixed.stop_price == 10.34
    assert atr_buffered.stop_price == 10.25
    assert atr_buffered.stop_price < fixed.stop_price


def test_research_rejects_invalid_stop_buffer():
    try:
        analyse_retracement_level(
            date_str="2026-07-30",
            symbol="TEST",
            data_feed="iex",
            bars=[],
            atr=1.0,
            level_name="FIB_61_8",
            ratio=0.618,
            stop_buffer_atr=-0.10,
        )
    except ValueError as error:
        assert str(error) == (
            "ATR stop buffer cannot be negative."
        )
    else:
        raise AssertionError(
            "Negative stop buffer should be rejected."
        )



def test_detects_stopped_out_then_later_target():
    bars = [
        bar(
            0,
            open_price=10.00,
            high=10.15,
            low=9.95,
            close=10.10,
        ),
        bar(
            1,
            open_price=10.10,
            high=10.12,
            low=9.80,
            close=9.90,
        ),
        bar(
            2,
            open_price=9.90,
            high=10.60,
            low=9.88,
            close=10.55,
        ),
    ]

    assert stopped_out_then_target(
        bars=bars,
        entry_price=10.00,
        stop_price=9.85,
        target_price=10.50,
    )


def test_does_not_flag_target_reached_before_stop():
    bars = [
        bar(
            0,
            open_price=10.00,
            high=10.55,
            low=9.95,
            close=10.50,
        ),
        bar(
            1,
            open_price=10.50,
            high=10.52,
            low=9.80,
            close=9.90,
        ),
    ]

    assert not stopped_out_then_target(
        bars=bars,
        entry_price=10.00,
        stop_price=9.85,
        target_price=10.50,
    )


def test_same_minute_stop_and_target_is_not_later_target():
    bars = [
        bar(
            0,
            open_price=10.00,
            high=10.55,
            low=9.80,
            close=10.10,
        ),
    ]

    assert not stopped_out_then_target(
        bars=bars,
        entry_price=10.00,
        stop_price=9.85,
        target_price=10.50,
    )


def test_does_not_flag_trade_that_never_enters():
    bars = [
        bar(
            0,
            open_price=9.80,
            high=9.95,
            low=9.70,
            close=9.90,
        ),
        bar(
            1,
            open_price=9.90,
            high=9.98,
            low=9.75,
            close=9.80,
        ),
    ]

    assert not stopped_out_then_target(
        bars=bars,
        entry_price=10.00,
        stop_price=9.70,
        target_price=10.50,
    )
