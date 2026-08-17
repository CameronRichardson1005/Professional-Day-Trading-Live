from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from trading_bot.webull_sandbox_manual_order import (
    CANCEL_CONFIRMATION_PHRASE,
    CONFIRMATION_PHRASE,
    REPLACE_CONFIRMATION_PHRASE,
    WebullSandboxManualOrderError,
    WebullSandboxManualOrderRequest,
    WebullSandboxManualOrderService,
)


NOW = datetime(
    2026,
    8,
    17,
    19,
    30,
    tzinfo=UTC,
)


class FakePreflight:
    def __init__(self):
        self.calls = 0

    def run(self):
        self.calls += 1

        return SimpleNamespace(
            allowed=True
        )


class FakeSnapshotClient:
    def __init__(self):
        self.calls = 0
        self.account_state = (
            SimpleNamespace(
                account_type="CASH",
                available_cash=1000000.0,
                position_exposure=0.0,
                open_buy_order_exposure=0.0,
                data_is_current=True,
                buying_power=1000000.0,
            )
        )

    def get_snapshot(self):
        self.calls += 1

        return SimpleNamespace(
            account_state=(
                self.account_state
            )
        )


class FakeManager:
    def __init__(self):
        self.calls = []
        self.cancel_calls = []
        self.reconcile_calls = []
        self.reconcile_results = []
        self.cancel_result = SimpleNamespace(
            client_order_id="order-1",
            symbol="SOUN",
            quantity=1,
            limit_price=5.25,
            status="CANCELLED",
            broker_order_id="broker-1",
            broker_status="CANCELLED",
            manual_override=True,
        )
        self.mark_pending_calls = []
        self.replace_calls = []
        self.replace_reconcile_calls = []
        self.replace_reconcile_results = []

        self.replace_result = SimpleNamespace(
            client_order_id="order-1",
            symbol="SOUN",
            quantity=2,
            limit_price=5.10,
            status="SUBMITTED",
            broker_order_id="broker-1",
            broker_status="SUBMITTED",
            manual_override=True,
        )

    def submit(
        self,
        *,
        intent,
        account,
    ):
        self.calls.append(
            (intent, account)
        )

        return SimpleNamespace(
            client_order_id=(
                intent.client_order_id
            ),
            symbol=intent.symbol,
            quantity=intent.quantity,
            limit_price=intent.limit_price,
            status="SUBMITTED",
            broker_order_id="broker-1",
            broker_status="SUBMITTED",
        )

    def replace_manual(
        self,
        *,
        client_order_id,
        quantity,
        limit_price,
        reason,
        account,
        management_armed,
    ):
        self.replace_calls.append(
            (
                client_order_id,
                quantity,
                limit_price,
                reason,
                account,
                management_armed,
            )
        )

        return self.replace_result

    def reconcile_replacement(
        self,
        *,
        client_order_id,
        quantity,
        limit_price,
    ):
        self.replace_reconcile_calls.append(
            (
                client_order_id,
                quantity,
                limit_price,
            )
        )

        if self.replace_reconcile_results:
            return self.replace_reconcile_results.pop(0)

        return self.replace_result

    def cancel_manual(
        self,
        *,
        client_order_id,
        reason,
    ):
        self.cancel_calls.append(
            (
                client_order_id,
                reason,
            )
        )

        return self.cancel_result

    def reconcile(
        self,
        *,
        client_order_id,
    ):
        self.reconcile_calls.append(
            client_order_id
        )

        if self.reconcile_results:
            return self.reconcile_results.pop(0)

        return SimpleNamespace(
            client_order_id=client_order_id,
            symbol="SOUN",
            status="SUBMITTED",
            broker_status="SUBMITTED",
            manual_override=False,
        )

    def mark_cancel_pending(
        self,
        *,
        client_order_id,
    ):
        self.mark_pending_calls.append(
            client_order_id
        )

        return SimpleNamespace(
            client_order_id=client_order_id,
            status="CANCEL_PENDING",
        )


def make_service(
    *,
    armed=True,
    management_armed=False,
):
    preflight = FakePreflight()
    snapshot = FakeSnapshotClient()
    manager = FakeManager()

    service = (
        WebullSandboxManualOrderService(
            preflight=preflight,
            snapshot_client=snapshot,
            execution_manager=manager,
            submission_armed=armed,
            management_armed=management_armed,
            clock=lambda: NOW,
            client_order_id_factory=(
                lambda: "manual-order-1"
            ),
            sleeper=lambda seconds: None,
            cancel_poll_attempts=3,
            cancel_poll_interval_seconds=1.1,
            cancel_stabilization_seconds=2.1,
        )
    )

    return (
        service,
        preflight,
        snapshot,
        manager,
    )


def make_request():
    return WebullSandboxManualOrderRequest(
        symbol="soun",
        quantity=1,
        limit_price=5.25,
        confirmation=(
            CONFIRMATION_PHRASE
        ),
    )


def test_request_normalizes_symbol_and_price():
    request = make_request()

    assert request.symbol == "SOUN"
    assert request.quantity == 1
    assert request.limit_price == 5.25


def test_wrong_confirmation_is_rejected():
    with pytest.raises(
        WebullSandboxManualOrderError,
        match="SANDBOX_CONFIRMATION_REQUIRED",
    ):
        WebullSandboxManualOrderRequest(
            symbol="SOUN",
            quantity=1,
            limit_price=5.25,
            confirmation="NO",
        )


def test_unarmed_service_fails_before_preflight():
    (
        service,
        preflight,
        snapshot,
        manager,
    ) = make_service(
        armed=False
    )

    with pytest.raises(
        WebullSandboxManualOrderError,
        match="SANDBOX_ORDER_SUBMISSION_NOT_ARMED",
    ):
        service.place(
            make_request()
        )

    assert preflight.calls == 0
    assert snapshot.calls == 0
    assert manager.calls == []


def test_manual_order_runs_preflight_and_safety_path():
    (
        service,
        preflight,
        snapshot,
        manager,
    ) = make_service()

    result = service.place(
        make_request()
    )

    assert preflight.calls == 1
    assert snapshot.calls == 1
    assert len(manager.calls) == 1

    intent, account = manager.calls[0]

    assert (
        intent.client_order_id
        == "manual-order-1"
    )

    assert (
        intent.strategy_name
        == "MANUAL_SANDBOX_TEST"
    )

    assert intent.symbol == "SOUN"
    assert intent.side == "BUY"
    assert intent.quantity == 1
    assert intent.limit_price == 5.25

    assert (
        account
        is snapshot.account_state
    )

    assert result.status == "SUBMITTED"



def test_cancel_requires_confirmation():
    (
        service,
        preflight,
        snapshot,
        manager,
    ) = make_service(
        armed=False
    )

    with pytest.raises(
        WebullSandboxManualOrderError,
        match=(
            "SANDBOX_CANCEL_CONFIRMATION_REQUIRED"
        ),
    ):
        service.cancel(
            client_order_id="order-1",
            confirmation="WRONG",
        )

    assert preflight.calls == 0
    assert manager.cancel_calls == []


def test_cancel_does_not_require_new_order_arm():
    (
        service,
        preflight,
        snapshot,
        manager,
    ) = make_service(
        armed=False
    )

    result = service.cancel(
        client_order_id="order-1",
        confirmation=(
            CANCEL_CONFIRMATION_PHRASE
        ),
    )

    # Rescue cancellation bypasses entry preflight.
    assert preflight.calls == 0

    assert manager.cancel_calls == [
        (
            "order-1",
            "MANUAL_SANDBOX_TEST_CANCEL",
        )
    ]

    assert result.status == "CANCELLED"
    assert result.manual_override is True



def test_cancel_polls_until_cancelled():
    (
        service,
        preflight,
        snapshot,
        manager,
    ) = make_service(
        armed=False
    )

    manager.cancel_result = SimpleNamespace(
        client_order_id="order-1",
        symbol="SOUN",
        status="CANCEL_PENDING",
        broker_status="SUBMITTED",
        manual_override=True,
    )

    manager.reconcile_results = [
        SimpleNamespace(
            client_order_id="order-1",
            symbol="SOUN",
            status="SUBMITTED",
            broker_status="SUBMITTED",
            manual_override=True,
        ),
        SimpleNamespace(
            client_order_id="order-1",
            symbol="SOUN",
            status="CANCELLED",
            broker_status="CANCELLED",
            manual_override=True,
        ),
    ]

    result = service.cancel(
        client_order_id="order-1",
        confirmation=(
            CANCEL_CONFIRMATION_PHRASE
        ),
    )

    assert result.status == "CANCELLED"

    assert manager.reconcile_calls == [
        "order-1",
        "order-1",
    ]


def test_cancel_reports_fill_race():
    (
        service,
        preflight,
        snapshot,
        manager,
    ) = make_service(
        armed=False
    )

    manager.cancel_result = SimpleNamespace(
        client_order_id="order-1",
        symbol="SOUN",
        status="CANCEL_PENDING",
        broker_status="SUBMITTED",
        manual_override=True,
    )

    manager.reconcile_results = [
        SimpleNamespace(
            client_order_id="order-1",
            symbol="SOUN",
            status="FILLED",
            broker_status="FILLED",
            manual_override=True,
        ),
    ]

    with pytest.raises(
        WebullSandboxManualOrderError,
        match="SANDBOX_CANCEL_ORDER_FILLED",
    ):
        service.cancel(
            client_order_id="order-1",
            confirmation=(
                CANCEL_CONFIRMATION_PHRASE
            ),
        )


def test_cancel_timeout_stays_cancel_pending():
    (
        service,
        preflight,
        snapshot,
        manager,
    ) = make_service(
        armed=False
    )

    manager.cancel_result = SimpleNamespace(
        client_order_id="order-1",
        symbol="SOUN",
        status="CANCEL_PENDING",
        broker_status="SUBMITTED",
        manual_override=True,
    )

    manager.reconcile_results = [
        SimpleNamespace(
            client_order_id="order-1",
            symbol="SOUN",
            status="SUBMITTED",
            broker_status="SUBMITTED",
            manual_override=True,
        ),
        SimpleNamespace(
            client_order_id="order-1",
            symbol="SOUN",
            status="SUBMITTED",
            broker_status="SUBMITTED",
            manual_override=True,
        ),
        SimpleNamespace(
            client_order_id="order-1",
            symbol="SOUN",
            status="SUBMITTED",
            broker_status="SUBMITTED",
            manual_override=True,
        ),
    ]

    with pytest.raises(
        WebullSandboxManualOrderError,
        match="SANDBOX_CANCEL_PENDING",
    ):
        service.cancel(
            client_order_id="order-1",
            confirmation=(
                CANCEL_CONFIRMATION_PHRASE
            ),
        )

    assert manager.mark_pending_calls == [
        "order-1"
    ]



def test_cancel_stabilizes_before_request():
    sleeps = []

    preflight = FakePreflight()
    snapshot = FakeSnapshotClient()
    manager = FakeManager()

    service = WebullSandboxManualOrderService(
        preflight=preflight,
        snapshot_client=snapshot,
        execution_manager=manager,
        submission_armed=False,
        clock=lambda: NOW,
        client_order_id_factory=(
            lambda: "manual-order-1"
        ),
        sleeper=sleeps.append,
        cancel_poll_attempts=3,
        cancel_poll_interval_seconds=1.1,
        cancel_stabilization_seconds=2.1,
    )

    result = service.cancel(
        client_order_id="order-1",
        confirmation=(
            CANCEL_CONFIRMATION_PHRASE
        ),
    )

    assert result.status == "CANCELLED"

    # First sleep is the pre-cancel stabilization window.
    assert sleeps[0] == 2.1

    assert manager.cancel_calls == [
        (
            "order-1",
            "MANUAL_SANDBOX_TEST_CANCEL",
        )
    ]


def test_terminal_order_is_not_cancelled_again():
    (
        service,
        preflight,
        snapshot,
        manager,
    ) = make_service(
        armed=False
    )

    manager.reconcile_results = [
        SimpleNamespace(
            client_order_id="order-1",
            symbol="SOUN",
            status="CANCELLED",
            broker_status="CANCELLED",
            manual_override=True,
        )
    ]

    result = service.cancel(
        client_order_id="order-1",
        confirmation=(
            CANCEL_CONFIRMATION_PHRASE
        ),
    )

    assert result.status == "CANCELLED"
    assert manager.cancel_calls == []



def test_replace_requires_management_arm():
    (
        service,
        preflight,
        snapshot,
        manager,
    ) = make_service(
        armed=False,
        management_armed=False,
    )

    with pytest.raises(
        WebullSandboxManualOrderError,
        match="SANDBOX_ORDER_MANAGEMENT_NOT_ARMED",
    ):
        service.replace(
            client_order_id="order-1",
            quantity=2,
            limit_price=5.10,
            confirmation=(
                REPLACE_CONFIRMATION_PHRASE
            ),
        )

    assert preflight.calls == 0
    assert snapshot.calls == 0
    assert manager.replace_calls == []


def test_replace_uses_preflight_snapshot_and_manager():
    (
        service,
        preflight,
        snapshot,
        manager,
    ) = make_service(
        armed=False,
        management_armed=True,
    )

    result = service.replace(
        client_order_id="order-1",
        quantity=2,
        limit_price=5.10,
        confirmation=(
            REPLACE_CONFIRMATION_PHRASE
        ),
    )

    assert preflight.calls == 1
    assert snapshot.calls == 1
    assert len(manager.replace_calls) == 1

    call = manager.replace_calls[0]

    assert call[0] == "order-1"
    assert call[1] == 2
    assert call[2] == 5.10

    assert (
        call[3]
        == "MANUAL_SANDBOX_TEST_REPLACE"
    )

    assert (
        call[4]
        is snapshot.account_state
    )

    assert call[5] is True
    assert result.status == "SUBMITTED"


def test_replace_polls_until_requested_state_visible():
    (
        service,
        preflight,
        snapshot,
        manager,
    ) = make_service(
        armed=False,
        management_armed=True,
    )

    manager.replace_result = SimpleNamespace(
        client_order_id="order-1",
        symbol="SOUN",
        quantity=1,
        limit_price=5.00,
        status="REPLACE_PENDING",
        broker_order_id="broker-1",
        broker_status="SUBMITTED",
        manual_override=True,
    )

    manager.replace_reconcile_results = [
        SimpleNamespace(
            client_order_id="order-1",
            symbol="SOUN",
            quantity=1,
            limit_price=5.00,
            status="REPLACE_PENDING",
            broker_order_id="broker-1",
            broker_status="SUBMITTED",
            manual_override=True,
        ),
        SimpleNamespace(
            client_order_id="order-1",
            symbol="SOUN",
            quantity=2,
            limit_price=5.10,
            status="SUBMITTED",
            broker_order_id="broker-1",
            broker_status="SUBMITTED",
            manual_override=True,
        ),
    ]

    result = service.replace(
        client_order_id="order-1",
        quantity=2,
        limit_price=5.10,
        confirmation=(
            REPLACE_CONFIRMATION_PHRASE
        ),
    )

    assert result.quantity == 2
    assert result.limit_price == 5.10

    assert len(
        manager.replace_reconcile_calls
    ) == 2
