from types import SimpleNamespace

import pytest

from trading_bot.webull_account_snapshot import (
    WebullAccountSnapshotClient,
    WebullAccountSnapshotError,
)


class FakeResponse:
    def __init__(
        self,
        payload,
        *,
        status_code=200,
        json_error=None,
    ):
        self.status_code = status_code
        self._payload = payload
        self._json_error = json_error

    def json(self):
        if self._json_error is not None:
            raise self._json_error

        return self._payload


class FakeAccountClient:
    def __init__(
        self,
        *,
        accounts,
        balance,
        positions,
    ):
        self.accounts = accounts
        self.balance = balance
        self.positions = positions
        self.requested_balance_account = None
        self.requested_positions_account = None

    def get_account_list(self):
        return self.accounts

    def get_account_balance(
        self,
        account_id,
    ):
        self.requested_balance_account = account_id
        return self.balance

    def get_account_position(
        self,
        account_id,
    ):
        self.requested_positions_account = account_id
        return self.positions


class FakeOrderClient:
    def __init__(self, open_orders):
        self.open_orders = open_orders
        self.requested_account = None
        self.requested_page_size = None

    def get_order_open(
        self,
        account_id,
        page_size=None,
    ):
        self.requested_account = account_id
        self.requested_page_size = page_size
        return self.open_orders


def trade_client(
    *,
    accounts=None,
    balance=None,
    positions=None,
    open_orders=None,
):
    account_v2 = FakeAccountClient(
        accounts=accounts or FakeResponse([
            {
                "account_id": "account-1",
                "account_type": "CASH",
            }
        ]),
        balance=balance or FakeResponse({
            "available_cash": "1000.00",
        }),
        positions=positions or FakeResponse([]),
    )

    order_v3 = FakeOrderClient(
        open_orders or FakeResponse([])
    )

    return SimpleNamespace(
        account_v2=account_v2,
        order_v3=order_v3,
    )


def test_builds_read_only_cash_account_state():
    client = trade_client(
        positions=FakeResponse([
            {
                "symbol": "AAPL",
                "quantity": "2",
                "market_price": "100",
                "market_value": "200",
            },
            {
                "symbol": "MSFT",
                "quantity": "1",
                "market_price": "50",
                "market_value": "50",
            },
        ]),
        open_orders=FakeResponse([
            {
                "symbol": "NVDA",
                "side": "BUY",
                "quantity": "10",
                "filled_quantity": "4",
                "remain_quantity": "6",
                "limit_price": "20",
            },
            {
                "symbol": "AAPL",
                "side": "SELL",
                "quantity": "1",
                "filled_quantity": "0",
                "limit_price": "110",
            },
        ]),
    )

    snapshot_client = (
        WebullAccountSnapshotClient(
            trade_client=client
        )
    )

    state = snapshot_client.get_account_state()

    assert state.account_type == "CASH"
    assert state.available_cash == 1000.0
    assert state.position_exposure == 250.0
    assert state.open_buy_order_exposure == 120.0
    assert state.current_total_exposure == 370.0
    assert state.data_is_current


def test_uses_v3_open_order_endpoint():
    client = trade_client()

    snapshot_client = (
        WebullAccountSnapshotClient(
            trade_client=client
        )
    )

    snapshot_client.get_account_state()

    assert (
        client.order_v3.requested_account
        == "account-1"
    )
    assert (
        client.order_v3.requested_page_size
        == 100
    )


def test_uses_selected_account_for_all_reads():
    client = trade_client()

    snapshot_client = (
        WebullAccountSnapshotClient(
            trade_client=client
        )
    )

    snapshot_client.get_account_state()

    assert (
        client.account_v2
        .requested_balance_account
        == "account-1"
    )
    assert (
        client.account_v2
        .requested_positions_account
        == "account-1"
    )


def test_margin_account_is_preserved_for_safety_gate():
    client = trade_client(
        accounts=FakeResponse([
            {
                "account_id": "account-1",
                "account_type": "MARGIN",
            }
        ])
    )

    state = (
        WebullAccountSnapshotClient(
            trade_client=client
        )
        .get_account_state()
    )

    assert state.account_type == "MARGIN"


def test_non_200_response_fails_closed():
    client = trade_client(
        balance=FakeResponse(
            {},
            status_code=500,
        )
    )

    with pytest.raises(
        WebullAccountSnapshotError,
        match="balance lookup failed",
    ):
        (
            WebullAccountSnapshotClient(
                trade_client=client
            )
            .get_account_state()
        )


def test_invalid_json_fails_closed():
    client = trade_client(
        positions=FakeResponse(
            None,
            json_error=ValueError(
                "invalid json"
            ),
        )
    )

    with pytest.raises(
        WebullAccountSnapshotError,
        match="invalid JSON",
    ):
        (
            WebullAccountSnapshotClient(
                trade_client=client
            )
            .get_account_state()
        )


def test_missing_account_type_fails_closed():
    client = trade_client(
        accounts=FakeResponse([
            {
                "account_id": "account-1",
            }
        ])
    )

    with pytest.raises(
        WebullAccountSnapshotError,
        match="strict validation",
    ):
        (
            WebullAccountSnapshotClient(
                trade_client=client
            )
            .get_account_state()
        )


def test_invalid_position_payload_fails_closed():
    client = trade_client(
        positions=FakeResponse([
            {
                "symbol": "AAPL",
                "quantity": "2",
            }
        ])
    )

    with pytest.raises(
        WebullAccountSnapshotError,
        match="strict validation",
    ):
        (
            WebullAccountSnapshotClient(
                trade_client=client
            )
            .get_account_state()
        )


def test_invalid_open_order_payload_fails_closed():
    client = trade_client(
        open_orders=FakeResponse([
            {
                "symbol": "AAPL",
                "side": "BUY",
                "quantity": "10",
            }
        ])
    )

    with pytest.raises(
        WebullAccountSnapshotError,
        match="strict validation",
    ):
        (
            WebullAccountSnapshotClient(
                trade_client=client
            )
            .get_account_state()
        )


def test_client_exposes_no_order_actions():
    client = WebullAccountSnapshotClient(
        trade_client=trade_client()
    )

    assert not hasattr(client, "place_order")
    assert not hasattr(client, "submit_order")
    assert not hasattr(client, "replace_order")
    assert not hasattr(client, "cancel_order")
    assert not hasattr(client, "preview_order")
