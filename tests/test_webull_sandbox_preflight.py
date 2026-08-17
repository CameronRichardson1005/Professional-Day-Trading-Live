from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from trading_bot.webull_execution import (
    WebullTradeIntent,
)
from trading_bot.webull_execution_ledger import (
    WebullExecutionLedger,
)
from trading_bot.webull_sandbox_broker import (
    WebullSandboxBroker,
)
from trading_bot.webull_sandbox_preflight import (
    WebullSandboxAccountSnapshotClient,
    WebullSandboxPreflight,
    WebullSandboxPreflightError,
    select_account_by_id,
)


NOW = datetime(
    2026,
    8,
    17,
    19,
    20,
    tzinfo=UTC,
)


class FakeResponse:
    def __init__(
        self,
        payload,
        *,
        status_code=200,
    ):
        self.status_code = status_code
        self.payload = payload

    def json(self):
        return self.payload


class FakeAccountV2:
    def __init__(
        self,
        *,
        account_type="CASH",
    ):
        self.account_type = account_type
        self.balance_account = None
        self.position_account = None

    def get_account_list(self):
        return FakeResponse([
            {
                "account_id": "other-account",
                "account_type": "CASH",
            },
            {
                "account_id": "sandbox-account",
                "account_type": (
                    self.account_type
                ),
            },
        ])

    def get_account_balance(
        self,
        account_id,
    ):
        self.balance_account = account_id

        return FakeResponse({
            "available_cash": "500.00",
        })

    def get_account_position(
        self,
        account_id,
    ):
        self.position_account = account_id
        return FakeResponse([])


class FakeOrderV3:
    def __init__(self):
        self.open_account = None
        self.open_page_size = None
        self.open_orders = []
        self.details = {}

        self.place_calls = 0
        self.replace_calls = 0
        self.cancel_calls = 0

    def get_order_open(
        self,
        account_id,
        page_size=None,
    ):
        self.open_account = account_id
        self.open_page_size = page_size

        return FakeResponse(
            self.open_orders
        )

    def get_order_detail(
        self,
        account_id,
        client_order_id,
    ):
        payload = self.details.get(
            client_order_id
        )

        if payload is None:
            return FakeResponse(
                {},
                status_code=404,
            )

        return FakeResponse(payload)

    def place_order(self, *args, **kwargs):
        self.place_calls += 1
        raise AssertionError(
            "Preflight must not place orders."
        )

    def replace_order(self, *args, **kwargs):
        self.replace_calls += 1
        raise AssertionError(
            "Preflight must not replace orders."
        )

    def cancel_order(self, *args, **kwargs):
        self.cancel_calls += 1
        raise AssertionError(
            "Preflight must not cancel orders."
        )


def make_trade_client(
    *,
    account_type="CASH",
):
    return SimpleNamespace(
        account_v2=FakeAccountV2(
            account_type=account_type,
        ),
        order_v3=FakeOrderV3(),
    )


def make_components(
    tmp_path: Path,
    *,
    account_type="CASH",
):
    client = make_trade_client(
        account_type=account_type,
    )

    snapshot = (
        WebullSandboxAccountSnapshotClient(
            trade_client=client,
            account_id="sandbox-account",
            execution_mode="SANDBOX",
        )
    )

    broker = WebullSandboxBroker(
        trade_client=client,
        account_id="sandbox-account",
        execution_mode="SANDBOX",
        submission_enabled=False,
    )

    ledger = WebullExecutionLedger(
        tmp_path / "execution.json",
        clock=lambda: NOW,
    )

    preflight = WebullSandboxPreflight(
        snapshot_client=snapshot,
        broker=broker,
        ledger=ledger,
    )

    return (
        preflight,
        client,
        ledger,
    )


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


def test_selects_configured_account_from_multiple():
    selected = select_account_by_id(
        [
            {
                "account_id": "first",
                "account_type": "CASH",
            },
            {
                "account_id": "wanted",
                "account_type": "CASH",
            },
        ],
        account_id="wanted",
    )

    assert selected.account_id == "wanted"
    assert selected.account_type == "CASH"


def test_missing_configured_account_fails_closed():
    with pytest.raises(
        WebullSandboxPreflightError,
        match=(
            "CONFIGURED_SANDBOX_ACCOUNT_NOT_FOUND"
        ),
    ):
        select_account_by_id(
            [
                {
                    "account_id": "other",
                    "account_type": "CASH",
                }
            ],
            account_id="wanted",
        )


def test_snapshot_uses_exact_selected_account(
    tmp_path,
):
    preflight, client, ledger = (
        make_components(tmp_path)
    )

    report = preflight.run()

    assert report.allowed is True
    assert (
        report.account_id
        == "sandbox-account"
    )

    assert (
        client.account_v2
        .balance_account
        == "sandbox-account"
    )

    assert (
        client.account_v2
        .position_account
        == "sandbox-account"
    )

    assert (
        client.order_v3.open_account
        == "sandbox-account"
    )

    assert (
        client.order_v3.open_page_size
        == 100
    )


def test_margin_account_fails_preflight(
    tmp_path,
):
    preflight, client, ledger = (
        make_components(
            tmp_path,
            account_type="MARGIN",
        )
    )

    with pytest.raises(
        WebullSandboxPreflightError,
        match="CASH_ACCOUNT_REQUIRED",
    ):
        preflight.run()


def test_untracked_open_order_fails_closed(
    tmp_path,
):
    preflight, client, ledger = (
        make_components(tmp_path)
    )

    client.order_v3.open_orders = [
        {
            "client_order_id": "manual-1",
            "symbol": "AAPL",
            "side": "BUY",
            "quantity": "1",
            "filled_quantity": "0",
            "remain_quantity": "1",
            "limit_price": "100",
        }
    ]

    with pytest.raises(
        WebullSandboxPreflightError,
        match="UNTRACKED_BROKER_OPEN_ORDER",
    ):
        preflight.run()


def test_nonterminal_order_is_reconciled(
    tmp_path,
):
    preflight, client, ledger = (
        make_components(tmp_path)
    )

    ledger.add_intent(
        intent=make_intent(),
        execution_mode="SANDBOX",
    )

    ledger.mark_operation_state(
        client_order_id="order-1",
        status="SUBMITTED",
    )

    client.order_v3.details[
        "order-1"
    ] = {
        "client_order_id": "order-1",
        "order_id": "broker-1",
        "symbol": "SOUN",
        "side": "BUY",
        "status": "PARTIAL_FILLED",
        "quantity": "10",
        "limit_price": "6.25",
        "filled_quantity": "4",
        "filled_price": "6.24",
    }

    client.order_v3.open_orders = [
        {
            "client_order_id": "order-1",
            "symbol": "SOUN",
            "side": "BUY",
            "quantity": "10",
            "filled_quantity": "4",
            "remain_quantity": "6",
            "limit_price": "6.25",
        }
    ]

    report = preflight.run()

    assert report.reconciled_orders == 1

    record = ledger.load()[
        "order-1"
    ]

    assert (
        record.status
        == "PARTIALLY_FILLED"
    )

    assert record.filled_quantity == 4
    assert record.average_fill_price == 6.24


def test_direct_broker_change_sets_manual_override(
    tmp_path,
):
    preflight, client, ledger = (
        make_components(tmp_path)
    )

    ledger.add_intent(
        intent=make_intent(),
        execution_mode="SANDBOX",
    )

    ledger.mark_operation_state(
        client_order_id="order-1",
        status="SUBMITTED",
    )

    client.order_v3.details[
        "order-1"
    ] = {
        "client_order_id": "order-1",
        "order_id": "broker-1",
        "symbol": "SOUN",
        "side": "BUY",
        "status": "SUBMITTED",
        "quantity": "12",
        "limit_price": "6.20",
        "filled_quantity": "0",
    }

    with pytest.raises(
        WebullSandboxPreflightError,
        match="MANUAL_BROKER_CHANGE_DETECTED",
    ):
        preflight.run()

    record = ledger.load()[
        "order-1"
    ]

    assert record.manual_override is True
    assert (
        record.manual_override_reason
        == "BROKER_ORDER_CHANGED_OUTSIDE_BOT"
    )

    assert record.quantity == 12
    assert record.limit_price == 6.20


def test_unknown_local_submission_must_reconcile(
    tmp_path,
):
    preflight, client, ledger = (
        make_components(tmp_path)
    )

    ledger.add_intent(
        intent=make_intent(),
        execution_mode="SANDBOX",
    )

    ledger.mark_operation_state(
        client_order_id="order-1",
        status="SUBMISSION_UNKNOWN",
    )

    with pytest.raises(
        WebullSandboxPreflightError,
        match="ORDER_RECONCILIATION_FAILED",
    ):
        preflight.run()

    record = ledger.load()[
        "order-1"
    ]

    assert (
        record.status
        == "BROKER_STATE_UNKNOWN"
    )


def test_preflight_never_mutates_broker(
    tmp_path,
):
    preflight, client, ledger = (
        make_components(tmp_path)
    )

    report = preflight.run()

    assert report.allowed is True

    assert client.order_v3.place_calls == 0
    assert client.order_v3.replace_calls == 0
    assert client.order_v3.cancel_calls == 0
