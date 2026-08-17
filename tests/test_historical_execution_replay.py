from datetime import UTC, datetime

import pytest

from trading_bot.historical_execution_replay import (
    HistoricalReplayError,
    replay_master_row_strategy,
)
from trading_bot.historical_execution_simulator import (
    HistoricalExecutionSimulator,
)


def minute(
    hour,
    minute_value,
    *,
    open_price,
    high,
    low,
    close,
):
    timestamp = datetime(
        2026,
        3,
        2,
        hour,
        minute_value,
        tzinfo=UTC,
    )

    return {
        "t": (
            timestamp.isoformat()
            .replace(
                "+00:00",
                "Z",
            )
        ),
        "o": open_price,
        "h": high,
        "l": low,
        "c": close,
        "v": 100000,
    }


def base_row():
    return {
        "date": "2026-03-02",
        "symbol": "SOUN",
        "evaluation_status": "OK",

        "manipulation_signal": "",
        "manipulation_entry": "",
        "manipulation_target": "",
        "manipulation_trading_stop": "",
        "manipulation_filled": "NO",
        "manipulation_outcome": "",

        "quick_flip_signal": "",
        "quick_flip_entry": "",
        "quick_flip_reversal_time": "",
        "quick_flip_confirmation_time": "",
        "quick_flip_filled": "NO",
        "quick_flip_endpoint_price": "",
    }


def test_manipulation_target_replays_buy_and_close():
    row = base_row()

    row.update({
        "manipulation_signal": "INVEST",
        "manipulation_entry": 10.0,
        "manipulation_target": 11.0,
        "manipulation_trading_stop": 9.0,
        "manipulation_filled": "YES",
        "manipulation_outcome": "TARGET",
    })

    bars = [
        minute(
            14,
            44,
            open_price=10.5,
            high=10.6,
            low=9.8,
            close=10.2,
        ),
        minute(
            14,
            45,
            open_price=10.2,
            high=10.4,
            low=9.9,
            close=10.1,
        ),
        minute(
            14,
            46,
            open_price=10.4,
            high=11.2,
            low=10.3,
            close=11.0,
        ),
    ]

    simulator = HistoricalExecutionSimulator(
        starting_cash=1000
    )

    result = replay_master_row_strategy(
        simulator=simulator,
        row=row,
        minute_bars=bars,
        strategy="MANIPULATION",
    )

    assert result.status == "COMPLETED"
    assert result.entry_filled is True
    assert result.exit_reason == "TARGET"
    assert result.exit_price == 11.0
    assert result.realized_pnl == 1.0

    assert simulator.cash == 1001

    assert (
        simulator.held_quantity(
            "SOUN"
        )
        == 0
    )


def test_manipulation_trading_stop_replays_reduce_only_close():
    row = base_row()

    row.update({
        "manipulation_signal": "INVEST",
        "manipulation_entry": 10.0,
        "manipulation_target": 12.0,
        "manipulation_trading_stop": 9.5,
        "manipulation_filled": "YES",
        "manipulation_outcome": "TRADING_STOP",
    })

    bars = [
        minute(
            14,
            45,
            open_price=10.1,
            high=10.2,
            low=9.9,
            close=10.0,
        ),
        minute(
            14,
            46,
            open_price=9.8,
            high=10.0,
            low=9.4,
            close=9.5,
        ),
    ]

    simulator = HistoricalExecutionSimulator(
        starting_cash=1000
    )

    result = replay_master_row_strategy(
        simulator=simulator,
        row=row,
        minute_bars=bars,
        strategy="MANIPULATION",
    )

    assert result.status == "COMPLETED"
    assert (
        result.exit_reason
        == "TRADING_STOP"
    )

    assert result.exit_price == 9.5
    assert result.realized_pnl == -0.5

    assert (
        simulator.held_quantity(
            "SOUN"
        )
        == 0
    )


def test_manipulation_gap_below_stop_uses_bar_open():
    row = base_row()

    row.update({
        "manipulation_signal": "INVEST",
        "manipulation_entry": 10.0,
        "manipulation_target": 12.0,
        "manipulation_trading_stop": 9.5,
        "manipulation_filled": "YES",
        "manipulation_outcome": "STOP",
    })

    bars = [
        minute(
            14,
            45,
            open_price=10.0,
            high=10.2,
            low=9.9,
            close=10.1,
        ),
        minute(
            14,
            46,
            open_price=9.2,
            high=9.4,
            low=9.0,
            close=9.1,
        ),
    ]

    simulator = HistoricalExecutionSimulator(
        starting_cash=1000
    )

    result = replay_master_row_strategy(
        simulator=simulator,
        row=row,
        minute_bars=bars,
        strategy="MANIPULATION",
    )

    assert result.exit_price == 9.2
    assert result.realized_pnl == -0.8


def test_historical_no_fill_cancels_entry_order():
    row = base_row()

    row.update({
        "manipulation_signal": "INVEST",
        "manipulation_entry": 9.0,
        "manipulation_target": 11.0,
        "manipulation_trading_stop": 8.0,
        "manipulation_filled": "NO",
        "manipulation_outcome": "NOT_FILLED",
    })

    bars = [
        minute(
            14,
            45,
            open_price=10.0,
            high=10.5,
            low=9.5,
            close=10.1,
        ),
        minute(
            14,
            46,
            open_price=10.1,
            high=10.4,
            low=9.6,
            close=10.2,
        ),
    ]

    simulator = HistoricalExecutionSimulator(
        starting_cash=1000
    )

    result = replay_master_row_strategy(
        simulator=simulator,
        row=row,
        minute_bars=bars,
        strategy="MANIPULATION",
    )

    assert (
        result.status
        == "ENTRY_NOT_FILLED"
    )

    assert result.entry_filled is False
    assert result.realized_pnl == 0

    order = simulator.orders[
        result.entry_order_id
    ]

    assert order.status == "CANCELLED"
    assert simulator.cash == 1000


def test_replay_detects_fill_disagreement():
    row = base_row()

    row.update({
        "manipulation_signal": "INVEST",
        "manipulation_entry": 10.0,
        "manipulation_target": 11.0,
        "manipulation_trading_stop": 9.0,
        "manipulation_filled": "NO",
        "manipulation_outcome": "NOT_FILLED",
    })

    bars = [
        minute(
            14,
            45,
            open_price=10.1,
            high=10.2,
            low=9.9,
            close=10.0,
        ),
    ]

    simulator = HistoricalExecutionSimulator(
        starting_cash=1000
    )

    with pytest.raises(
        HistoricalReplayError,
        match=(
            "REPLAY_FILL_DISAGREES_WITH_HISTORY"
        ),
    ):
        replay_master_row_strategy(
            simulator=simulator,
            row=row,
            minute_bars=bars,
            strategy="MANIPULATION",
        )


def test_quick_flip_confirmation_controls_entry_eligibility():
    row = base_row()

    row.update({
        "quick_flip_signal": "INVEST",
        "quick_flip_entry": 10.0,
        "quick_flip_confirmation_time": (
            "2026-03-02T09:46:00-05:00"
        ),
        "quick_flip_filled": "YES",
        "quick_flip_endpoint_price": 10.8,
    })

    bars = [
        minute(
            14,
            45,
            open_price=10.2,
            high=10.3,
            low=9.8,
            close=10.1,
        ),
        minute(
            14,
            46,
            open_price=10.2,
            high=10.4,
            low=9.9,
            close=10.2,
        ),
        minute(
            20,
            59,
            open_price=10.7,
            high=10.9,
            low=10.6,
            close=10.8,
        ),
    ]

    simulator = HistoricalExecutionSimulator(
        starting_cash=1000
    )

    result = replay_master_row_strategy(
        simulator=simulator,
        row=row,
        minute_bars=bars,
        strategy="QUICK_FLIP",
    )

    assert result.status == "COMPLETED"

    assert (
        result.entry_fill_time
        == datetime(
            2026,
            3,
            2,
            14,
            46,
            tzinfo=UTC,
        )
    )

    assert (
        result.exit_reason
        == "SESSION_ENDPOINT"
    )

    assert result.exit_price == 10.8
    assert result.realized_pnl == 0.8


def test_quick_flip_has_no_automatic_stop_in_replay():
    row = base_row()

    row.update({
        "quick_flip_signal": "INVEST",
        "quick_flip_entry": 10.0,
        "quick_flip_confirmation_time": (
            "2026-03-02T09:45:00-05:00"
        ),
        "quick_flip_filled": "YES",
        "quick_flip_endpoint_price": 10.5,
    })

    bars = [
        minute(
            14,
            45,
            open_price=10.0,
            high=10.2,
            low=9.0,
            close=9.2,
        ),
        minute(
            20,
            59,
            open_price=10.4,
            high=10.6,
            low=10.3,
            close=10.5,
        ),
    ]

    simulator = HistoricalExecutionSimulator(
        starting_cash=1000
    )

    result = replay_master_row_strategy(
        simulator=simulator,
        row=row,
        minute_bars=bars,
        strategy="QUICK_FLIP",
    )

    assert (
        result.exit_reason
        == "SESSION_ENDPOINT"
    )

    assert result.realized_pnl == 0.5


def test_quantity_scales_realized_pnl():
    row = base_row()

    row.update({
        "manipulation_signal": "INVEST",
        "manipulation_entry": 10.0,
        "manipulation_target": 11.0,
        "manipulation_trading_stop": 9.0,
        "manipulation_filled": "YES",
        "manipulation_outcome": "TARGET",
    })

    bars = [
        minute(
            14,
            45,
            open_price=10.0,
            high=10.1,
            low=9.9,
            close=10.0,
        ),
        minute(
            14,
            46,
            open_price=10.5,
            high=11.2,
            low=10.4,
            close=11.0,
        ),
    ]

    simulator = HistoricalExecutionSimulator(
        starting_cash=1000
    )

    result = replay_master_row_strategy(
        simulator=simulator,
        row=row,
        minute_bars=bars,
        strategy="MANIPULATION",
        quantity=3,
    )

    assert result.realized_pnl == 3.0
    assert simulator.cash == 1003


def test_no_signal_does_not_create_order():
    row = base_row()

    simulator = HistoricalExecutionSimulator(
        starting_cash=1000
    )

    result = replay_master_row_strategy(
        simulator=simulator,
        row=row,
        minute_bars=[
            minute(
                14,
                45,
                open_price=10,
                high=11,
                low=9,
                close=10,
            )
        ],
        strategy="QUICK_FLIP",
    )

    assert result.status == "NO_SIGNAL"
    assert simulator.orders == {}


def test_bad_data_quality_is_skipped_before_execution():
    row = base_row()

    row[
        "evaluation_status"
    ] = "MISSING_ATR"

    simulator = HistoricalExecutionSimulator(
        starting_cash=1000
    )

    result = replay_master_row_strategy(
        simulator=simulator,
        row=row,
        minute_bars=[],
        strategy="MANIPULATION",
    )

    assert (
        result.status
        == "SKIPPED_DATA_QUALITY"
    )

    assert simulator.orders == {}


def test_active_order_prevents_isolated_replay():
    row = base_row()

    row.update({
        "manipulation_signal": "INVEST",
        "manipulation_entry": 10.0,
        "manipulation_target": 11.0,
        "manipulation_trading_stop": 9.0,
        "manipulation_filled": "YES",
        "manipulation_outcome": "TARGET",
    })

    simulator = HistoricalExecutionSimulator(
        starting_cash=1000
    )

    from trading_bot.webull_execution import (
        WebullTradeIntent,
    )

    simulator.place_buy(
        WebullTradeIntent(
            client_order_id="existing",
            strategy_name="TEST",
            symbol="AAPL",
            side="BUY",
            quantity=1,
            limit_price=100,
            created_at=datetime(
                2026,
                3,
                2,
                14,
                45,
                tzinfo=UTC,
            ),
        )
    )

    with pytest.raises(
        HistoricalReplayError,
        match="ACTIVE_ORDER_ALREADY_EXISTS",
    ):
        replay_master_row_strategy(
            simulator=simulator,
            row=row,
            minute_bars=[
                minute(
                    14,
                    45,
                    open_price=10,
                    high=11,
                    low=9,
                    close=10,
                )
            ],
            strategy="MANIPULATION",
        )


def test_completed_replay_leaves_no_position_and_no_active_order():
    row = base_row()

    row.update({
        "quick_flip_signal": "INVEST",
        "quick_flip_entry": 10.0,
        "quick_flip_confirmation_time": (
            "2026-03-02T09:45:00-05:00"
        ),
        "quick_flip_filled": "YES",
        "quick_flip_endpoint_price": 10.5,
    })

    simulator = HistoricalExecutionSimulator(
        starting_cash=1000
    )

    replay_master_row_strategy(
        simulator=simulator,
        row=row,
        minute_bars=[
            minute(
                14,
                45,
                open_price=10.0,
                high=10.2,
                low=9.9,
                close=10.0,
            ),
            minute(
                20,
                59,
                open_price=10.5,
                high=10.6,
                low=10.4,
                close=10.5,
            ),
        ],
        strategy="QUICK_FLIP",
    )

    assert (
        simulator.held_quantity(
            "SOUN"
        )
        == 0
    )

    assert not any(
        order.active
        for order
        in simulator.orders.values()
    )

    simulator.assert_invariants()


def test_unsupported_strategy_rejected():
    simulator = HistoricalExecutionSimulator(
        starting_cash=1000
    )

    with pytest.raises(
        HistoricalReplayError,
        match="UNSUPPORTED_HISTORICAL_STRATEGY",
    ):
        replay_master_row_strategy(
            simulator=simulator,
            row=base_row(),
            minute_bars=[],
            strategy="OTHER",
        )
