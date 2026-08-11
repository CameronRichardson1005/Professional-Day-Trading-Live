from types import SimpleNamespace

from trading_bot.fibonacci_research import (
    FibonacciResearchReport,
    deterministic_control_ratio,
    metrics_for,
    rule_passes,
    simulate_trade,
)


def bar(
    timestamp: str,
    *,
    high: float,
    low: float,
    close: float,
):
    return {
        "t": timestamp,
        "o": close,
        "h": high,
        "l": low,
        "c": close,
    }


def test_control_ratio_is_deterministic_and_non_fibonacci():
    first = deterministic_control_ratio(
        "2026-07-30",
        "OPEN",
    )
    second = deterministic_control_ratio(
        "2026-07-30",
        "OPEN",
    )

    assert first == second
    assert 0.25 <= first <= 0.75

    for fibonacci in (0.382, 0.500, 0.618):
        assert abs(first - fibonacci) >= 0.035


def test_combined_rule_requires_all_conditions():
    assert rule_passes(
        "RED_MANIPULATION_MIN_8_RED",
        red_candle=True,
        manipulation_candle=True,
        red_minutes=8,
        new_lows=3,
        candle_atr_ratio=0.4,
    )

    assert not rule_passes(
        "RED_MANIPULATION_MIN_8_RED",
        red_candle=True,
        manipulation_candle=False,
        red_minutes=10,
        new_lows=6,
        candle_atr_ratio=0.5,
    )


def test_simulation_records_target_win():
    result = simulate_trade(
        bars=[
            bar(
                "2026-07-30T13:46:00Z",
                high=10.05,
                low=9.95,
                close=10.00,
            ),
            bar(
                "2026-07-30T13:47:00Z",
                high=10.50,
                low=10.00,
                close=10.40,
            ),
        ],
        entry_price=10.00,
        target_price=10.40,
        stop_price=9.80,
        slippage_bps=0,
        commission_per_share=0,
    )

    assert result["outcome"] == "WIN"
    assert result["exit_reason"] == "TARGET"


def test_same_minute_target_and_stop_is_loss():
    result = simulate_trade(
        bars=[
            bar(
                "2026-07-30T13:46:00Z",
                high=10.50,
                low=9.70,
                close=10.10,
            ),
        ],
        entry_price=10.00,
        target_price=10.40,
        stop_price=9.80,
        slippage_bps=0,
        commission_per_share=0,
    )

    assert result["outcome"] == "LOSS"
    assert result["exit_reason"] == "STOP"


def test_report_creates_all_rule_target_records():
    report = FibonacciResearchReport(
        start_date="2026-07-30",
        end_date="2026-07-30",
        data_feed="iex",
        slippage_bps=0,
        commission_per_share=0,
    )

    stock = SimpleNamespace(
        opening_bar={
            "o": 10.5,
            "h": 10.6,
            "l": 10.0,
            "c": 10.1,
            "v": 100000,
        },
        atr=1.0,
        is_red=True,
        is_manipulation=True,
        red_minutes=10,
        green_minutes=5,
        new_lows=6,
        new_highs=2,
    )

    report.add_stock(
        date_str="2026-07-30",
        symbol="OPEN",
        stock=stock,
        bars_processed=15,
        outcome_bars=[
            bar(
                "2026-07-30T13:46:00Z",
                high=10.7,
                low=9.99,
                close=10.5,
            )
        ],
    )

    assert len(report.records) == 28

    summary = report.summary_rows()
    assert len(summary) == 28
    assert metrics_for(report.records).observations == 28
