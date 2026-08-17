from datetime import UTC, datetime

import pytest

from trading_bot.historical_execution_simulator import (
    HistoricalBar,
    HistoricalExecutionError,
    HistoricalExecutionSimulator,
)
from trading_bot.webull_execution import (
    WebullTradeIntent,
)
from trading_bot.webull_reduce_only_close import (
    WebullReduceOnlyCloseIntent,
)


NOW = datetime(
    2026,
    3,
    2,
    14,
    45,
    tzinfo=UTC,
)


def buy_intent(
    *,
    client_order_id="buy-1",
    quantity=1,
    limit_price=10.0,
):
    return WebullTradeIntent(
        client_order_id=client_order_id,
        strategy_name="QUICK_FLIP",
        symbol="SOUN",
        side="BUY",
        quantity=quantity,
        limit_price=limit_price,
        created_at=NOW,
    )


def close_intent(
    simulator,
    *,
    client_order_id="close-1",
    quantity=1,
    limit_price=11.0,
):
    return WebullReduceOnlyCloseIntent(
        client_order_id=client_order_id,
        symbol="SOUN",
        quantity=quantity,
        limit_price=limit_price,
        confirmed_position_quantity=(
            simulator.held_quantity(
                "SOUN"
            )
        ),
        created_at=NOW,
    )


def bar(
    *,
    timestamp=NOW,
    open_price=10.0,
    high=11.5,
    low=9.5,
    close=10.5,
):
    return HistoricalBar(
        symbol="SOUN",
        timestamp=timestamp,
        open=open_price,
        high=high,
        low=low,
        close=close,
        volume=100000,
    )


def fill_one_share(
    simulator,
):
    simulator.place_buy(
        buy_intent()
    )

    simulator.process_bar(
        bar()
    )

    assert (
        simulator.held_quantity(
            "SOUN"
        )
        == 1
    )


def test_buy_fill_changes_cash_and_position_once():
    simulator = HistoricalExecutionSimulator(
        starting_cash=1000
    )

    simulator.place_buy(
        buy_intent()
    )

    changed = simulator.process_bar(
        bar()
    )

    assert len(changed) == 1
    assert changed[0].status == "FILLED"
    assert simulator.cash == 990
    assert (
        simulator.held_quantity(
            "SOUN"
        )
        == 1
    )

    second = simulator.process_bar(
        bar()
    )

    assert second == ()
    assert simulator.cash == 990
    assert (
        simulator.held_quantity(
            "SOUN"
        )
        == 1
    )


def test_duplicate_client_order_id_rejected():
    simulator = HistoricalExecutionSimulator(
        starting_cash=1000
    )

    simulator.place_buy(
        buy_intent()
    )

    with pytest.raises(
        HistoricalExecutionError,
        match="DUPLICATE_CLIENT_ORDER_ID",
    ):
        simulator.place_buy(
            buy_intent()
        )


def test_pending_buy_reserves_cash():
    simulator = HistoricalExecutionSimulator(
        starting_cash=100
    )

    simulator.place_buy(
        buy_intent(
            client_order_id="buy-1",
            quantity=6,
            limit_price=10,
        )
    )

    assert simulator.available_cash == 40

    with pytest.raises(
        HistoricalExecutionError,
        match="INSUFFICIENT_AVAILABLE_CASH",
    ):
        simulator.place_buy(
            buy_intent(
                client_order_id="buy-2",
                quantity=5,
                limit_price=10,
            )
        )


def test_partial_buy_fill_then_final_fill():
    simulator = HistoricalExecutionSimulator(
        starting_cash=1000
    )

    simulator.place_buy(
        buy_intent(
            quantity=3
        )
    )

    simulator.process_bar(
        bar(),
        max_fill_quantity=1,
    )

    order = simulator.orders[
        "buy-1"
    ]

    assert (
        order.status
        == "PARTIALLY_FILLED"
    )

    assert order.filled_quantity == 1
    assert simulator.cash == 990
    assert (
        simulator.held_quantity(
            "SOUN"
        )
        == 1
    )

    simulator.process_bar(
        bar()
    )

    assert order.status == "FILLED"
    assert order.filled_quantity == 3
    assert simulator.cash == 970
    assert (
        simulator.held_quantity(
            "SOUN"
        )
        == 3
    )


def test_reduce_only_close_cannot_exceed_position():
    simulator = HistoricalExecutionSimulator(
        starting_cash=1000
    )

    fill_one_share(simulator)

    with pytest.raises(
        Exception,
    ):
        WebullReduceOnlyCloseIntent(
            client_order_id="close-1",
            symbol="SOUN",
            quantity=2,
            limit_price=11,
            confirmed_position_quantity=1,
            created_at=NOW,
        )


def test_close_fill_never_creates_short():
    simulator = HistoricalExecutionSimulator(
        starting_cash=1000
    )

    fill_one_share(simulator)

    simulator.place_reduce_only_close(
        close_intent(
            simulator
        )
    )

    simulator.process_bar(
        bar()
    )

    assert (
        simulator.held_quantity(
            "SOUN"
        )
        == 0
    )

    assert simulator.cash == 1001

    simulator.assert_invariants()


def test_second_active_close_is_rejected():
    simulator = HistoricalExecutionSimulator(
        starting_cash=1000
    )

    simulator.place_buy(
        buy_intent(
            quantity=2
        )
    )

    simulator.process_bar(
        bar()
    )

    simulator.place_reduce_only_close(
        close_intent(
            simulator,
            client_order_id="close-1",
            quantity=1,
        )
    )

    with pytest.raises(
        HistoricalExecutionError,
        match="ACTIVE_CLOSE_ALREADY_EXISTS",
    ):
        simulator.place_reduce_only_close(
            close_intent(
                simulator,
                client_order_id="close-2",
                quantity=1,
            )
        )


def test_partial_close_reserves_remaining_shares():
    simulator = HistoricalExecutionSimulator(
        starting_cash=1000
    )

    simulator.place_buy(
        buy_intent(
            quantity=3
        )
    )

    simulator.process_bar(
        bar()
    )

    simulator.place_reduce_only_close(
        close_intent(
            simulator,
            quantity=2,
        )
    )

    simulator.process_bar(
        bar(),
        max_fill_quantity=1,
    )

    assert (
        simulator.held_quantity(
            "SOUN"
        )
        == 2
    )

    assert (
        simulator.reserved_sell_quantity(
            "SOUN"
        )
        == 1
    )

    assert (
        simulator.available_to_close(
            "SOUN"
        )
        == 1
    )

    simulator.process_bar(
        bar()
    )

    assert (
        simulator.held_quantity(
            "SOUN"
        )
        == 1
    )


def test_cancel_releases_buy_reservation():
    simulator = HistoricalExecutionSimulator(
        starting_cash=100
    )

    simulator.place_buy(
        buy_intent(
            quantity=5,
            limit_price=10,
        )
    )

    assert simulator.available_cash == 50

    simulator.cancel(
        "buy-1"
    )

    assert simulator.available_cash == 100


def test_cancel_releases_close_reservation():
    simulator = HistoricalExecutionSimulator(
        starting_cash=1000
    )

    simulator.place_buy(
        buy_intent(
            quantity=2
        )
    )

    simulator.process_bar(
        bar()
    )

    simulator.place_reduce_only_close(
        close_intent(
            simulator,
            quantity=2,
        )
    )

    assert (
        simulator.available_to_close(
            "SOUN"
        )
        == 0
    )

    simulator.cancel(
        "close-1"
    )

    assert (
        simulator.available_to_close(
            "SOUN"
        )
        == 2
    )


def test_ambiguous_submission_is_not_blindly_retried():
    simulator = HistoricalExecutionSimulator(
        starting_cash=1000
    )

    with pytest.raises(
        HistoricalExecutionError,
        match="SUBMISSION_UNKNOWN",
    ):
        simulator.place_buy(
            buy_intent(),
            ambiguous_after_accept=True,
        )

    assert (
        simulator.orders[
            "buy-1"
        ].status
        == "SUBMISSION_UNKNOWN"
    )

    with pytest.raises(
        HistoricalExecutionError,
        match="DUPLICATE_CLIENT_ORDER_ID",
    ):
        simulator.place_buy(
            buy_intent()
        )

    simulator.resolve_submission(
        "buy-1",
        accepted=True,
    )

    simulator.process_bar(
        bar()
    )

    assert (
        simulator.held_quantity(
            "SOUN"
        )
        == 1
    )


def test_rejected_ambiguous_submission_releases_cash():
    simulator = HistoricalExecutionSimulator(
        starting_cash=100
    )

    with pytest.raises(
        HistoricalExecutionError,
        match="SUBMISSION_UNKNOWN",
    ):
        simulator.place_buy(
            buy_intent(
                quantity=10,
                limit_price=10,
            ),
            ambiguous_after_accept=True,
        )

    assert simulator.available_cash == 0

    simulator.resolve_submission(
        "buy-1",
        accepted=False,
    )

    assert simulator.available_cash == 100


def test_bar_before_order_creation_cannot_fill():
    simulator = HistoricalExecutionSimulator(
        starting_cash=1000
    )

    simulator.place_buy(
        buy_intent()
    )

    old_bar = bar(
        timestamp=datetime(
            2026,
            3,
            2,
            14,
            44,
            tzinfo=UTC,
        )
    )

    assert (
        simulator.process_bar(
            old_bar
        )
        == ()
    )

    assert (
        simulator.held_quantity(
            "SOUN"
        )
        == 0
    )


def test_wrong_symbol_bar_cannot_fill():
    simulator = HistoricalExecutionSimulator(
        starting_cash=1000
    )

    simulator.place_buy(
        buy_intent()
    )

    other = HistoricalBar(
        symbol="AAPL",
        timestamp=NOW,
        open=100,
        high=101,
        low=99,
        close=100,
        volume=1000,
    )

    assert (
        simulator.process_bar(
            other
        )
        == ()
    )


def test_changed_confirmed_position_rejected():
    simulator = HistoricalExecutionSimulator(
        starting_cash=1000
    )

    fill_one_share(simulator)

    intent = WebullReduceOnlyCloseIntent(
        client_order_id="close-1",
        symbol="SOUN",
        quantity=1,
        limit_price=11,
        confirmed_position_quantity=1,
        created_at=NOW,
    )

    simulator.holdings[
        "SOUN"
    ] = 2

    with pytest.raises(
        HistoricalExecutionError,
        match="CONFIRMED_POSITION_CHANGED",
    ):
        simulator.place_reduce_only_close(
            intent
        )


def test_restart_round_trip_preserves_state(
    tmp_path,
):
    simulator = HistoricalExecutionSimulator(
        starting_cash=1000
    )

    simulator.place_buy(
        buy_intent(
            quantity=3
        )
    )

    simulator.process_bar(
        bar(),
        max_fill_quantity=1,
    )

    state_file = (
        tmp_path
        / "historical-state.json"
    )

    simulator.save_state(
        state_file
    )

    restarted = (
        HistoricalExecutionSimulator
        .load_state(
            state_file
        )
    )

    assert restarted.cash == simulator.cash
    assert (
        restarted.holdings
        == simulator.holdings
    )

    assert (
        restarted.orders[
            "buy-1"
        ].filled_quantity
        == 1
    )

    restarted.process_bar(
        bar()
    )

    assert (
        restarted.orders[
            "buy-1"
        ].status
        == "FILLED"
    )

    assert (
        restarted.held_quantity(
            "SOUN"
        )
        == 3
    )

    assert restarted.cash == 970


def test_state_file_permissions_are_private(
    tmp_path,
):
    simulator = HistoricalExecutionSimulator(
        starting_cash=1000
    )

    path = (
        tmp_path
        / "state.json"
    )

    simulator.save_state(path)

    mode = (
        path.stat().st_mode
        & 0o777
    )

    assert mode == 0o600
