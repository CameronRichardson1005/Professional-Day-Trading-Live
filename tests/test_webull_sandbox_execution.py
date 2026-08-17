from datetime import UTC, datetime
from pathlib import Path

import pytest

from trading_bot.webull_execution import (
    WebullTradeIntent,
)
from trading_bot.webull_execution_ledger import (
    WebullExecutionLedger,
)
from trading_bot.webull_execution_manager import (
    WebullExecutionManagerError,
    WebullSandboxExecutionManager,
)
from trading_bot.webull_safety import (
    WebullAccountState,
)
from trading_bot.webull_sandbox_broker import (
    SANDBOX_ENDPOINT,
    WebullSandboxBroker,
    WebullSandboxBrokerError,
    parse_order_detail,
)


NOW = datetime(
    2026,
    8,
    17,
    19,
    0,
    tzinfo=UTC,
)


class FakeResponse:
    def __init__(
        self,
        *,
        status_code=200,
        payload=None,
    ):
        self.status_code = status_code
        self.payload = (
            {} if payload is None
            else payload
        )

    def json(self):
        return self.payload


class FakeOrderV3:
    def __init__(self):
        self.place_calls = []
        self.replace_calls = []
        self.cancel_calls = []
        self.detail_calls = []

        self.detail_payload = {
            "client_order_id": "order-1",
            "order_id": "broker-1",
            "status": "SUBMITTED",
            "quantity": "10",
            "limit_price": "6.2500",
            "filled_quantity": "0",
            "filled_price": None,
        }

    def place_order(
        self,
        account_id,
        new_orders,
    ):
        self.place_calls.append(
            (account_id, new_orders)
        )
        return FakeResponse()

    def replace_order(
        self,
        account_id,
        modify_orders,
    ):
        self.replace_calls.append(
            (account_id, modify_orders)
        )

        item = modify_orders[0]

        self.detail_payload[
            "quantity"
        ] = item["quantity"]

        self.detail_payload[
            "limit_price"
        ] = item["limit_price"]

        return FakeResponse()

    def cancel_order(
        self,
        account_id,
        client_order_id,
    ):
        self.cancel_calls.append(
            (account_id, client_order_id)
        )

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
            payload=dict(
                self.detail_payload
            )
        )


class FakeTradeClient:
    def __init__(self):
        self.order_v3 = FakeOrderV3()


def make_intent():
    return WebullTradeIntent(
        client_order_id="order-1",
        strategy_name="QUICK_FLIP",
        symbol="SOUN",
        side="BUY",
        quantity=10,
        limit_price=6.25,
        created_at=NOW,
    )


def make_account():
    return WebullAccountState(
        account_type="CASH",
        available_cash=500,
        position_exposure=0,
        open_buy_order_exposure=0,
        data_is_current=True,
    )


def make_manager(
    tmp_path: Path,
):
    trade_client = FakeTradeClient()

    broker = WebullSandboxBroker(
        trade_client=trade_client,
        account_id="sandbox-account",
        execution_mode="SANDBOX",
        submission_enabled=True,
    )

    ledger = WebullExecutionLedger(
        tmp_path / "execution.json",
        clock=lambda: NOW,
    )

    manager = (
        WebullSandboxExecutionManager(
            broker=broker,
            ledger=ledger,
        )
    )

    return (
        manager,
        broker,
        ledger,
        trade_client,
    )


def test_endpoint_is_hard_coded_to_sandbox():
    assert (
        SANDBOX_ENDPOINT
        == "api.sandbox.webull.com"
    )


def test_live_mode_cannot_construct_sandbox_broker():
    with pytest.raises(
        Exception,
        match="LIVE_EXECUTION_LOCKED",
    ):
        WebullSandboxBroker(
            trade_client=FakeTradeClient(),
            account_id="sandbox-account",
            execution_mode="LIVE_AUTO",
            submission_enabled=True,
        )


def test_disabled_mode_cannot_construct_broker():
    with pytest.raises(
        WebullSandboxBrokerError,
        match="SANDBOX_MODE_REQUIRED",
    ):
        WebullSandboxBroker(
            trade_client=FakeTradeClient(),
            account_id="sandbox-account",
            execution_mode="DISABLED",
        )


def test_submission_requires_second_arm():
    broker = WebullSandboxBroker(
        trade_client=FakeTradeClient(),
        account_id="sandbox-account",
        execution_mode="SANDBOX",
        submission_enabled=False,
    )

    with pytest.raises(
        WebullSandboxBrokerError,
        match="SANDBOX_SUBMISSION_NOT_ARMED",
    ):
        broker.place_order(
            make_intent()
        )


def test_place_uses_exact_v3_payload():
    trade_client = FakeTradeClient()

    broker = WebullSandboxBroker(
        trade_client=trade_client,
        account_id="sandbox-account",
        execution_mode="SANDBOX",
        submission_enabled=True,
    )

    broker.place_order(
        make_intent()
    )

    account_id, orders = (
        trade_client
        .order_v3
        .place_calls[0]
    )

    assert account_id == "sandbox-account"

    assert orders[0][
        "client_order_id"
    ] == "order-1"

    assert orders[0][
        "symbol"
    ] == "SOUN"

    assert orders[0][
        "quantity"
    ] == "10"


def test_replace_uses_minimal_modify_payload():
    trade_client = FakeTradeClient()

    broker = WebullSandboxBroker(
        trade_client=trade_client,
        account_id="sandbox-account",
        execution_mode="SANDBOX",
        submission_enabled=True,
    )

    broker.replace_order(
        client_order_id="order-1",
        quantity=12,
        limit_price=6.20,
    )

    _, payload = (
        trade_client
        .order_v3
        .replace_calls[0]
    )

    assert payload == [
        {
            "client_order_id": "order-1",
            "quantity": "12",
            "limit_price": "6.2000",
        }
    ]


def test_order_detail_parser_reads_fill_state():
    state = parse_order_detail(
        {
            "orders": [
                {
                    "client_order_id": "order-1",
                    "order_id": "broker-123",
                    "status": "PARTIAL_FILLED",
                    "total_quantity": "10",
                    "limit_price": "6.25",
                    "filled_quantity": "4.00000",
                    "filled_price": "6.24",
                }
            ]
        },
        client_order_id="order-1",
    )

    assert state.broker_order_id == "broker-123"
    assert state.quantity == 10
    assert state.filled_quantity == 4
    assert state.average_fill_price == 6.24


def test_submit_persists_then_reconciles(
    tmp_path,
):
    (
        manager,
        broker,
        ledger,
        trade_client,
    ) = make_manager(tmp_path)

    result = manager.submit(
        intent=make_intent(),
        account=make_account(),
    )

    assert result.status == "SUBMITTED"
    assert result.broker_order_id == "broker-1"

    assert len(
        trade_client.order_v3.place_calls
    ) == 1

    assert len(
        trade_client.order_v3.detail_calls
    ) == 1

    stored = ledger.load()["order-1"]

    assert stored.status == "SUBMITTED"
    assert stored.last_reconciled_at == NOW


def test_duplicate_submit_never_calls_broker_twice(
    tmp_path,
):
    (
        manager,
        broker,
        ledger,
        trade_client,
    ) = make_manager(tmp_path)

    manager.submit(
        intent=make_intent(),
        account=make_account(),
    )

    with pytest.raises(
        WebullExecutionManagerError,
        match="INTENT_NOT_ACCEPTED",
    ):
        manager.submit(
            intent=make_intent(),
            account=make_account(),
        )

    assert len(
        trade_client.order_v3.place_calls
    ) == 1


def test_manual_replace_sets_override(
    tmp_path,
):
    (
        manager,
        broker,
        ledger,
        trade_client,
    ) = make_manager(tmp_path)

    manager.submit(
        intent=make_intent(),
        account=make_account(),
    )

    result = manager.replace_manual(
        client_order_id="order-1",
        quantity=12,
        limit_price=6.20,
        reason="USER_CHANGED_ORDER",
    )

    assert result.manual_override is True
    assert result.quantity == 12
    assert result.limit_price == 6.20

    assert (
        result.manual_override_reason
        == "USER_CHANGED_ORDER"
    )


def test_manual_cancel_sets_override_and_cancel_flag(
    tmp_path,
):
    (
        manager,
        broker,
        ledger,
        trade_client,
    ) = make_manager(tmp_path)

    manager.submit(
        intent=make_intent(),
        account=make_account(),
    )

    result = manager.cancel_manual(
        client_order_id="order-1",
        reason="USER_CANCELLED_ORDER",
    )

    assert result.manual_override is True
    assert result.cancel_requested is True
    assert result.status == "CANCELLED"


def test_safety_gate_blocks_order_before_broker(
    tmp_path,
):
    (
        manager,
        broker,
        ledger,
        trade_client,
    ) = make_manager(tmp_path)

    bad_account = WebullAccountState(
        account_type="CASH",
        available_cash=10,
        position_exposure=0,
        open_buy_order_exposure=0,
        data_is_current=True,
    )

    with pytest.raises(
        WebullExecutionManagerError,
        match="INSUFFICIENT_AVAILABLE_CASH",
    ):
        manager.submit(
            intent=make_intent(),
            account=bad_account,
        )

    assert not trade_client.order_v3.place_calls
    assert ledger.load() == {}


def test_transport_uncertainty_is_not_retried(
    tmp_path,
):
    class BrokenOrderV3(FakeOrderV3):
        def place_order(
            self,
            account_id,
            new_orders,
        ):
            self.place_calls.append(
                (account_id, new_orders)
            )
            raise TimeoutError(
                "simulated timeout"
            )

    trade_client = FakeTradeClient()
    trade_client.order_v3 = BrokenOrderV3()

    broker = WebullSandboxBroker(
        trade_client=trade_client,
        account_id="sandbox-account",
        execution_mode="SANDBOX",
        submission_enabled=True,
    )

    ledger = WebullExecutionLedger(
        tmp_path / "execution.json",
        clock=lambda: NOW,
    )

    manager = WebullSandboxExecutionManager(
        broker=broker,
        ledger=ledger,
    )

    with pytest.raises(
        WebullExecutionManagerError,
        match="SUBMISSION_FAILED",
    ):
        manager.submit(
            intent=make_intent(),
            account=make_account(),
        )

    record = ledger.load()["order-1"]

    assert (
        record.status
        == "SUBMISSION_UNKNOWN"
    )

    # Critical: an uncertain placement is never
    # automatically submitted a second time.
    assert len(
        trade_client.order_v3.place_calls
    ) == 1



def test_cancel_available_when_submission_disarmed():
    trade_client = FakeTradeClient()

    broker = WebullSandboxBroker(
        trade_client=trade_client,
        account_id="sandbox-account",
        execution_mode="SANDBOX",
        submission_enabled=False,
    )

    broker.cancel_order(
        client_order_id="order-1"
    )

    assert (
        trade_client.order_v3.cancel_calls
        == [
            (
                "sandbox-account",
                "order-1",
            )
        ]
    )



def test_cancel_request_remains_pending_until_broker_confirms(
    tmp_path,
):
    (
        manager,
        broker,
        ledger,
        trade_client,
    ) = make_manager(tmp_path)

    manager.submit(
        intent=make_intent(),
        account=make_account(),
    )

    # Simulate Webull accepting the cancel request but Order
    # Detail still reporting the order as live.
    def cancel_without_immediate_status_change(
        account_id,
        client_order_id,
    ):
        trade_client.order_v3.cancel_calls.append(
            (account_id, client_order_id)
        )

        return FakeResponse()

    trade_client.order_v3.cancel_order = (
        cancel_without_immediate_status_change
    )

    result = manager.cancel_manual(
        client_order_id="order-1",
        reason="USER_CANCELLED_ORDER",
    )

    assert result.status == "CANCEL_PENDING"
    assert result.cancel_requested is True
    assert result.manual_override is True
    assert result.broker_status == "SUBMITTED"



def test_replace_waiting_for_broker_stays_pending(
    tmp_path,
):
    (
        manager,
        broker,
        ledger,
        trade_client,
    ) = make_manager(tmp_path)

    manager.submit(
        intent=make_intent(),
        account=make_account(),
    )

    def delayed_replace(
        account_id,
        modify_orders,
    ):
        trade_client.order_v3.replace_calls.append(
            (
                account_id,
                modify_orders,
            )
        )

        # Broker acknowledges the request, but Order Detail
        # intentionally remains on the old quantity/price.
        return FakeResponse()

    trade_client.order_v3.replace_order = (
        delayed_replace
    )

    result = manager.replace_manual(
        client_order_id="order-1",
        quantity=12,
        limit_price=6.20,
        reason="USER_CHANGED_ORDER",
    )

    assert result.status == "REPLACE_PENDING"

    stored = ledger.load()["order-1"]

    assert (
        stored.replace_requested_quantity
        == 12
    )

    assert (
        stored.replace_requested_limit_price
        == 6.20
    )


def test_replace_transport_uncertainty_preserves_request(
    tmp_path,
):
    (
        manager,
        broker,
        ledger,
        trade_client,
    ) = make_manager(tmp_path)

    manager.submit(
        intent=make_intent(),
        account=make_account(),
    )

    def broken_replace(
        account_id,
        modify_orders,
    ):
        trade_client.order_v3.replace_calls.append(
            (
                account_id,
                modify_orders,
            )
        )

        raise TimeoutError(
            "simulated replace timeout"
        )

    trade_client.order_v3.replace_order = (
        broken_replace
    )

    with pytest.raises(
        WebullExecutionManagerError,
        match="REPLACEMENT_FAILED",
    ):
        manager.replace_manual(
            client_order_id="order-1",
            quantity=12,
            limit_price=6.20,
            reason="USER_CHANGED_ORDER",
        )

    stored = ledger.load()["order-1"]

    assert (
        stored.status
        == "BROKER_STATE_UNKNOWN"
    )

    assert (
        stored.replace_requested_quantity
        == 12
    )

    assert (
        stored.replace_requested_limit_price
        == 6.20
    )

    # Critical: ambiguous replacement is not retried.
    assert len(
        trade_client.order_v3.replace_calls
    ) == 1
