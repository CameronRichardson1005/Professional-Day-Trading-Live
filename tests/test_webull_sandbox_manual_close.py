from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from trading_bot.webull_account_parser import (
    ParsedWebullOpenOrder,
    ParsedWebullPosition,
)
from trading_bot.webull_sandbox_manual_close import (
    CLOSE_CONFIRMATION_PHRASE,
    WebullSandboxManualCloseError,
    WebullSandboxManualCloseRequest,
    WebullSandboxManualCloseService,
)


NOW = datetime(
    2026,
    8,
    17,
    20,
    0,
    tzinfo=UTC,
)


def position(quantity=2.0):
    return ParsedWebullPosition(
        symbol="SOUN",
        quantity=quantity,
        market_price=7.00,
        market_value=round(quantity * 7.00, 2),
    )


def snapshot(
    *,
    positions=None,
    open_orders=None,
):
    return SimpleNamespace(
        positions=tuple(
            [position()]
            if positions is None
            else positions
        ),
        open_orders=tuple(
            ()
            if open_orders is None
            else open_orders
        ),
    )


class FakeSnapshotClient:
    def __init__(self, value):
        self.value = value
        self.calls = 0

    def get_snapshot(self):
        self.calls += 1
        return self.value


class FakeCloseManager:
    def __init__(self):
        self.calls = []

    def submit(
        self,
        *,
        intent,
        management_armed,
    ):
        self.calls.append(
            (intent, management_armed)
        )

        return SimpleNamespace(
            client_order_id=(
                intent.client_order_id
            ),
            symbol=intent.symbol,
            side=intent.side,
            quantity=intent.quantity,
            limit_price=intent.limit_price,
            status="SUBMITTED",
            filled_quantity=0.0,
        )


def request():
    return WebullSandboxManualCloseRequest(
        symbol="soun",
        quantity=1,
        limit_price=6.90,
        confirmation=CLOSE_CONFIRMATION_PHRASE,
    )


def make_service(
    *,
    management_armed,
    value=None,
):
    client = FakeSnapshotClient(
        value or snapshot()
    )
    manager = FakeCloseManager()

    service = WebullSandboxManualCloseService(
        snapshot_client=client,
        close_manager=manager,
        management_armed=management_armed,
        clock=lambda: NOW,
        client_order_id_factory=(
            lambda: "close-1"
        ),
    )

    return service, client, manager


def test_management_arm_required_before_snapshot():
    service, client, manager = make_service(
        management_armed=False
    )

    with pytest.raises(
        WebullSandboxManualCloseError,
        match="SANDBOX_ORDER_MANAGEMENT_NOT_ARMED",
    ):
        service.close(request())

    assert client.calls == 0
    assert manager.calls == []


def test_close_uses_confirmed_position():
    service, client, manager = make_service(
        management_armed=True
    )

    result = service.close(request())

    assert result.status == "SUBMITTED"
    assert client.calls == 1
    assert len(manager.calls) == 1

    intent, armed = manager.calls[0]

    assert armed is True
    assert intent.symbol == "SOUN"
    assert intent.side == "SELL"
    assert intent.quantity == 1
    assert (
        intent.confirmed_position_quantity
        == 2.0
    )


def test_open_sell_same_symbol_blocks_close():
    existing = ParsedWebullOpenOrder(
        symbol="SOUN",
        side="SELL",
        remaining_quantity=1.0,
        limit_price=7.00,
        reserved_exposure=0.0,
    )

    service, client, manager = make_service(
        management_armed=True,
        value=snapshot(
            open_orders=(existing,)
        ),
    )

    with pytest.raises(
        WebullSandboxManualCloseError,
        match="OPEN_SELL_ORDER_ALREADY_EXISTS",
    ):
        service.close(request())

    assert manager.calls == []


def test_sell_other_symbol_does_not_block():
    existing = ParsedWebullOpenOrder(
        symbol="AAPL",
        side="SELL",
        remaining_quantity=1.0,
        limit_price=100.0,
        reserved_exposure=0.0,
    )

    service, client, manager = make_service(
        management_armed=True,
        value=snapshot(
            open_orders=(existing,)
        ),
    )

    result = service.close(request())

    assert result.status == "SUBMITTED"


def test_close_cannot_exceed_position():
    service, client, manager = make_service(
        management_armed=True,
        value=snapshot(
            positions=(position(quantity=0.5),)
        ),
    )

    with pytest.raises(
        WebullSandboxManualCloseError,
        match="CLOSE_QUANTITY_EXCEEDS_POSITION",
    ):
        service.close(request())

    assert manager.calls == []


def test_wrong_confirmation_rejected():
    with pytest.raises(
        WebullSandboxManualCloseError,
        match="SANDBOX_CLOSE_CONFIRMATION_REQUIRED",
    ):
        WebullSandboxManualCloseRequest(
            symbol="SOUN",
            quantity=1,
            limit_price=6.90,
            confirmation="WRONG",
        )
