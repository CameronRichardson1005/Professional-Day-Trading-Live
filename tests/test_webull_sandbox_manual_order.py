from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from trading_bot.webull_sandbox_manual_order import (
    CONFIRMATION_PHRASE,
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


def make_service(
    *,
    armed=True,
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
            clock=lambda: NOW,
            client_order_id_factory=(
                lambda: "manual-order-1"
            ),
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
