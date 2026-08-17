from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from trading_bot.webull_account_parser import (
    ParsedWebullOpenOrder,
    ParsedWebullPosition,
)
from trading_bot.webull_execution import (
    WebullExecutionError,
    WebullTradeIntent,
)
from trading_bot.webull_reduce_only_close import (
    WebullReduceOnlyCloseLedger,
    build_reduce_only_close_intent,
)
from trading_bot.webull_reduce_only_close_manager import (
    WebullReduceOnlyCloseManagerError,
    WebullSandboxReduceOnlyCloseManager,
)
from trading_bot.webull_sandbox_broker import (
    WebullSandboxBroker,
    WebullSandboxBrokerError,
)


NOW = datetime(
    2026,
    8,
    17,
    20,
    0,
    tzinfo=UTC,
)


class FakeResponse:
    def __init__(
        self,
        status_code=200,
        payload=None,
    ):
        self.status_code = status_code
        self.payload = (
            {} if payload is None else payload
        )

    def json(self):
        return self.payload


class FakeOrderV3:
    def __init__(self):
        self.place_calls = []
        self.detail_calls = []
        self.cancel_calls = []
        self.cancel_error = None

        self.detail_payload = {
            "client_order_id": "close-1",
            "order_id": "broker-close-1",
            "status": "SUBMITTED",
            "symbol": "SOUN",
            "side": "SELL",
            "quantity": "1",
            "limit_price": "6.9000",
            "filled_quantity": "0",
        }

    def place_order(
        self,
        account_id,
        orders,
        client_combo_order_id=None,
    ):
        self.place_calls.append(
            (account_id, orders)
        )

        return FakeResponse()

    def cancel_order(
        self,
        account_id,
        client_order_id,
    ):
        self.cancel_calls.append(
            (
                account_id,
                client_order_id,
            )
        )

        if self.cancel_error is not None:
            raise self.cancel_error

        self.detail_payload[
            "status"
        ] = "CANCELLED"

        return FakeResponse()

    def get_order_detail(
        self,
        account_id,
        client_order_id,
    ):
        self.detail_calls.append(
            (account_id, client_order_id)
        )

        return FakeResponse(
            payload=self.detail_payload
        )


class FakeTradeClient:
    def __init__(self):
        self.order_v3 = FakeOrderV3()


def position(quantity=1.0):
    return ParsedWebullPosition(
        symbol="SOUN",
        quantity=quantity,
        market_price=7.00,
        market_value=round(
            quantity * 7.00,
            2,
        ),
    )


def close_intent():
    return build_reduce_only_close_intent(
        client_order_id="close-1",
        positions=(position(),),
        symbol="SOUN",
        quantity=1,
        limit_price=6.90,
        created_at=NOW,
    )


class FakeSnapshotClient:
    def __init__(self):
        self.calls = 0
        self.value = SimpleNamespace(
            account_state=SimpleNamespace(
                account_type="CASH",
                data_is_current=True,
            ),
            positions=(
                position(),
            ),
            open_orders=(),
        )

    def get_snapshot(self):
        self.calls += 1
        return self.value


def make_manager(tmp_path):
    trade_client = FakeTradeClient()

    broker = WebullSandboxBroker(
        trade_client=trade_client,
        account_id="sandbox-account",
        execution_mode="SANDBOX",
        submission_enabled=False,
    )

    ledger = WebullReduceOnlyCloseLedger(
        tmp_path / "close.json",
        clock=lambda: NOW,
    )

    snapshot_client = FakeSnapshotClient()

    manager = (
        WebullSandboxReduceOnlyCloseManager(
            broker=broker,
            ledger=ledger,
            snapshot_client=snapshot_client,
            execution_mode="SANDBOX",
        )
    )

    return manager, broker, ledger, trade_client


def test_normal_trade_intent_remains_buy_only():
    with pytest.raises(
        WebullExecutionError,
        match="ONLY_BUY_INTENTS_SUPPORTED",
    ):
        WebullTradeIntent(
            client_order_id="bad-sell",
            strategy_name="QUICK_FLIP",
            symbol="SOUN",
            side="SELL",
            quantity=1,
            limit_price=6.90,
            created_at=NOW,
        )


def test_close_requires_management_arm(
    tmp_path,
):
    manager, broker, ledger, trade_client = (
        make_manager(tmp_path)
    )

    with pytest.raises(
        WebullReduceOnlyCloseManagerError,
        match="ORDER_MANAGEMENT_NOT_ARMED",
    ):
        manager.submit(
            intent=close_intent(),
            management_armed=False,
        )

    assert ledger.load() == {}
    assert trade_client.order_v3.place_calls == []


def test_broker_close_requires_management_arm(
    tmp_path,
):
    manager, broker, ledger, trade_client = (
        make_manager(tmp_path)
    )

    with pytest.raises(
        WebullSandboxBrokerError,
        match=(
            "SANDBOX_ORDER_MANAGEMENT_NOT_ENABLED"
        ),
    ):
        broker.place_reduce_only_close(
            close_intent(),
            management_enabled=False,
        )

    assert trade_client.order_v3.place_calls == []


def test_close_does_not_require_entry_arm(
    tmp_path,
):
    manager, broker, ledger, trade_client = (
        make_manager(tmp_path)
    )

    broker.place_reduce_only_close(
        close_intent(),
        management_enabled=True,
    )

    assert len(
        trade_client.order_v3.place_calls
    ) == 1

    _, orders = (
        trade_client.order_v3.place_calls[0]
    )

    assert orders[0]["side"] == "SELL"
    assert "SHORT" not in orders[0].values()


def test_close_is_durable_before_network_call(
    tmp_path,
):
    manager, broker, ledger, trade_client = (
        make_manager(tmp_path)
    )

    calls = []

    def timeout(
        account_id,
        orders,
        client_combo_order_id=None,
    ):
        calls.append((account_id, orders))

        stored = ledger.load()["close-1"]

        assert stored.status == "SUBMITTING"
        assert stored.side == "SELL"

        raise TimeoutError("simulated timeout")

    trade_client.order_v3.place_order = timeout

    with pytest.raises(
        WebullReduceOnlyCloseManagerError,
        match="CLOSE_SUBMISSION_FAILED",
    ):
        manager.submit(
            intent=close_intent(),
            management_armed=True,
        )

    assert len(calls) == 1

    stored = ledger.load()["close-1"]

    assert stored.status == "SUBMISSION_UNKNOWN"
    assert stored.side == "SELL"


def test_successful_close_reconciles(
    tmp_path,
):
    manager, broker, ledger, trade_client = (
        make_manager(tmp_path)
    )

    result = manager.submit(
        intent=close_intent(),
        management_armed=True,
    )

    assert result.status == "SUBMITTED"
    assert result.side == "SELL"
    assert result.quantity == 1
    assert result.filled_quantity == 0.0

    assert len(
        trade_client.order_v3.place_calls
    ) == 1

    assert len(
        trade_client.order_v3.detail_calls
    ) == 1


def test_filled_close_is_recorded(
    tmp_path,
):
    manager, broker, ledger, trade_client = (
        make_manager(tmp_path)
    )

    trade_client.order_v3.detail_payload = {
        "client_order_id": "close-1",
        "order_id": "broker-close-1",
        "status": "FILLED",
        "symbol": "SOUN",
        "side": "SELL",
        "quantity": "1",
        "limit_price": "6.9000",
        "filled_quantity": "1",
        "filled_price": "6.9100",
    }

    result = manager.submit(
        intent=close_intent(),
        management_armed=True,
    )

    assert result.status == "FILLED"
    assert result.filled_quantity == 1.0
    assert result.average_fill_price == 6.91


def test_short_broker_state_fails_closed(
    tmp_path,
):
    manager, broker, ledger, trade_client = (
        make_manager(tmp_path)
    )

    trade_client.order_v3.detail_payload[
        "side"
    ] = "SHORT"

    with pytest.raises(
        WebullReduceOnlyCloseManagerError,
        match="CLOSE_BROKER_SIDE_NOT_SELL",
    ):
        manager.submit(
            intent=close_intent(),
            management_armed=True,
        )

    stored = ledger.load()["close-1"]

    assert stored.status == "BROKER_STATE_UNKNOWN"


def test_missing_broker_side_fails_closed(
    tmp_path,
):
    manager, broker, ledger, trade_client = (
        make_manager(tmp_path)
    )

    trade_client.order_v3.detail_payload.pop(
        "side"
    )

    with pytest.raises(
        WebullReduceOnlyCloseManagerError,
        match="CLOSE_BROKER_SIDE_NOT_SELL",
    ):
        manager.submit(
            intent=close_intent(),
            management_armed=True,
        )


def test_quantity_mismatch_fails_closed(
    tmp_path,
):
    manager, broker, ledger, trade_client = (
        make_manager(tmp_path)
    )

    trade_client.order_v3.detail_payload[
        "quantity"
    ] = "2"

    with pytest.raises(
        WebullReduceOnlyCloseManagerError,
        match="CLOSE_BROKER_QUANTITY_MISMATCH",
    ):
        manager.submit(
            intent=close_intent(),
            management_armed=True,
        )


def test_price_mismatch_fails_closed(
    tmp_path,
):
    manager, broker, ledger, trade_client = (
        make_manager(tmp_path)
    )

    trade_client.order_v3.detail_payload[
        "limit_price"
    ] = "7.1000"

    with pytest.raises(
        WebullReduceOnlyCloseManagerError,
        match="CLOSE_BROKER_PRICE_MISMATCH",
    ):
        manager.submit(
            intent=close_intent(),
            management_armed=True,
        )



def test_full_fill_position_reconciles_to_zero(
    tmp_path,
):
    manager, broker, ledger, trade_client = (
        make_manager(tmp_path)
    )

    trade_client.order_v3.detail_payload = {
        "client_order_id": "close-1",
        "order_id": "broker-close-1",
        "status": "FILLED",
        "symbol": "SOUN",
        "side": "SELL",
        "quantity": "1",
        "limit_price": "6.9000",
        "filled_quantity": "1",
        "filled_price": "6.9100",
    }

    result = manager.submit(
        intent=close_intent(),
        management_armed=True,
    )

    assert result.status == "FILLED"

    reconciled = manager.reconcile_position(
        client_order_id="close-1",
        positions=(),
    )

    assert reconciled.position_reconciled is True
    assert reconciled.position_reconciled_at == NOW


def test_partial_position_reconciliation(
    tmp_path,
):
    manager, broker, ledger, trade_client = (
        make_manager(tmp_path)
    )

    manager.snapshot_client.value = SimpleNamespace(
        account_state=SimpleNamespace(
            account_type="CASH",
            data_is_current=True,
        ),
        positions=(
            position(quantity=3),
        ),
        open_orders=(),
    )

    intent = build_reduce_only_close_intent(
        client_order_id="close-1",
        positions=(position(quantity=3),),
        symbol="SOUN",
        quantity=2,
        limit_price=6.90,
        created_at=NOW,
    )

    trade_client.order_v3.detail_payload = {
        "client_order_id": "close-1",
        "order_id": "broker-close-1",
        "status": "PARTIALLY_FILLED",
        "symbol": "SOUN",
        "side": "SELL",
        "quantity": "2",
        "limit_price": "6.9000",
        "filled_quantity": "1",
        "filled_price": "6.9100",
    }

    result = manager.submit(
        intent=intent,
        management_armed=True,
    )

    assert result.status == "PARTIALLY_FILLED"

    reconciled = manager.reconcile_position(
        client_order_id="close-1",
        positions=(
            position(quantity=2),
        ),
    )

    assert reconciled.position_reconciled is True


def test_position_mismatch_fails_closed(
    tmp_path,
):
    manager, broker, ledger, trade_client = (
        make_manager(tmp_path)
    )

    trade_client.order_v3.detail_payload = {
        "client_order_id": "close-1",
        "order_id": "broker-close-1",
        "status": "FILLED",
        "symbol": "SOUN",
        "side": "SELL",
        "quantity": "1",
        "limit_price": "6.9000",
        "filled_quantity": "1",
        "filled_price": "6.9100",
    }

    manager.submit(
        intent=close_intent(),
        management_armed=True,
    )

    with pytest.raises(
        WebullReduceOnlyCloseManagerError,
        match="CLOSE_POSITION_QUANTITY_MISMATCH",
    ):
        manager.reconcile_position(
            client_order_id="close-1",
            positions=(
                position(quantity=1),
            ),
        )

    stored = ledger.load()["close-1"]

    assert (
        stored.status
        == "POSITION_STATE_UNKNOWN"
    )

    assert stored.position_reconciled is False


def test_position_reconcile_requires_fill(
    tmp_path,
):
    manager, broker, ledger, trade_client = (
        make_manager(tmp_path)
    )

    manager.submit(
        intent=close_intent(),
        management_armed=True,
    )

    with pytest.raises(
        WebullReduceOnlyCloseManagerError,
        match="CLOSE_HAS_NO_FILL_TO_RECONCILE",
    ):
        manager.reconcile_position(
            client_order_id="close-1",
            positions=(position(),),
        )


def test_unfilled_close_can_be_cancelled(
    tmp_path,
):
    manager, broker, ledger, trade_client = (
        make_manager(tmp_path)
    )

    manager.submit(
        intent=close_intent(),
        management_armed=True,
    )

    result = manager.cancel(
        client_order_id="close-1",
    )

    assert result.status == "CANCELLED"

    assert trade_client.order_v3.cancel_calls == [
        (
            "sandbox-account",
            "close-1",
        )
    ]


def test_partially_filled_close_can_be_cancelled(
    tmp_path,
):
    manager, broker, ledger, trade_client = (
        make_manager(tmp_path)
    )

    trade_client.order_v3.detail_payload = {
        "client_order_id": "close-1",
        "order_id": "broker-close-1",
        "status": "PARTIALLY_FILLED",
        "symbol": "SOUN",
        "side": "SELL",
        "quantity": "1",
        "limit_price": "6.9000",
        "filled_quantity": "0.5",
        "filled_price": "6.9100",
    }

    manager.submit(
        intent=close_intent(),
        management_armed=True,
    )

    result = manager.cancel(
        client_order_id="close-1",
    )

    assert result.status == "CANCELLED"
    assert result.filled_quantity == 0.5


def test_ambiguous_close_cancel_not_retried(
    tmp_path,
):
    manager, broker, ledger, trade_client = (
        make_manager(tmp_path)
    )

    manager.submit(
        intent=close_intent(),
        management_armed=True,
    )

    trade_client.order_v3.cancel_error = (
        TimeoutError(
            "simulated cancellation timeout"
        )
    )

    with pytest.raises(
        WebullReduceOnlyCloseManagerError,
        match="CLOSE_CANCELLATION_FAILED",
    ):
        manager.cancel(
            client_order_id="close-1",
        )

    assert len(
        trade_client.order_v3.cancel_calls
    ) == 1

    stored = ledger.load()["close-1"]

    assert (
        stored.status
        == "BROKER_STATE_UNKNOWN"
    )



def test_pre_submit_position_change_fails_closed(
    tmp_path,
):
    manager, broker, ledger, trade_client = (
        make_manager(tmp_path)
    )

    manager.snapshot_client.value = (
        SimpleNamespace(
            account_state=SimpleNamespace(
                account_type="CASH",
                data_is_current=True,
            ),
            positions=(
                position(
                    quantity=0.5
                ),
            ),
            open_orders=(),
        )
    )

    with pytest.raises(
        WebullReduceOnlyCloseManagerError,
        match=(
            "CLOSE_POSITION_CHANGED_BEFORE_SUBMIT"
        ),
    ):
        manager.submit(
            intent=close_intent(),
            management_armed=True,
        )

    assert (
        trade_client.order_v3.place_calls
        == []
    )

    assert (
        ledger.load()["close-1"].status
        == "REJECTED"
    )


def test_pre_submit_open_sell_fails_closed(
    tmp_path,
):
    manager, broker, ledger, trade_client = (
        make_manager(tmp_path)
    )

    existing_sell = ParsedWebullOpenOrder(
        symbol="SOUN",
        side="SELL",
        remaining_quantity=1.0,
        limit_price=7.00,
        reserved_exposure=0.0,
    )

    manager.snapshot_client.value = (
        SimpleNamespace(
            account_state=SimpleNamespace(
                account_type="CASH",
                data_is_current=True,
            ),
            positions=(
                position(),
            ),
            open_orders=(
                existing_sell,
            ),
        )
    )

    with pytest.raises(
        WebullReduceOnlyCloseManagerError,
        match=(
            "OPEN_SELL_ORDER_ALREADY_EXISTS"
        ),
    ):
        manager.submit(
            intent=close_intent(),
            management_armed=True,
        )

    assert (
        trade_client.order_v3.place_calls
        == []
    )


def test_pre_submit_stale_account_fails_closed(
    tmp_path,
):
    manager, broker, ledger, trade_client = (
        make_manager(tmp_path)
    )

    manager.snapshot_client.value = (
        SimpleNamespace(
            account_state=SimpleNamespace(
                account_type="CASH",
                data_is_current=False,
            ),
            positions=(
                position(),
            ),
            open_orders=(),
        )
    )

    with pytest.raises(
        WebullReduceOnlyCloseManagerError,
        match="CLOSE_ACCOUNT_DATA_STALE",
    ):
        manager.submit(
            intent=close_intent(),
            management_armed=True,
        )

    assert (
        trade_client.order_v3.place_calls
        == []
    )


def test_pre_submit_margin_account_fails_closed(
    tmp_path,
):
    manager, broker, ledger, trade_client = (
        make_manager(tmp_path)
    )

    manager.snapshot_client.value = (
        SimpleNamespace(
            account_state=SimpleNamespace(
                account_type="MARGIN",
                data_is_current=True,
            ),
            positions=(
                position(),
            ),
            open_orders=(),
        )
    )

    with pytest.raises(
        WebullReduceOnlyCloseManagerError,
        match="CLOSE_REQUIRES_CASH_ACCOUNT",
    ):
        manager.submit(
            intent=close_intent(),
            management_armed=True,
        )

    assert (
        trade_client.order_v3.place_calls
        == []
    )


def test_pre_submit_snapshot_runs_before_network(
    tmp_path,
):
    manager, broker, ledger, trade_client = (
        make_manager(tmp_path)
    )

    result = manager.submit(
        intent=close_intent(),
        management_armed=True,
    )

    assert result.status == "SUBMITTED"

    assert (
        manager.snapshot_client.calls
        == 1
    )

    assert len(
        trade_client.order_v3.place_calls
    ) == 1
