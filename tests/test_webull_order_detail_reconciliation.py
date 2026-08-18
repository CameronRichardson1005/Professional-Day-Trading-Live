import pytest

from trading_bot.webull_order_detail_reconciliation import (
    WebullOrderDetailReconciler,
    WebullOrderDetailReconciliationError,
)


class FakeResponse:
    def __init__(
        self,
        payload,
        *,
        status_code=200,
    ):
        self.payload = payload
        self.status_code = (
            status_code
        )

    def json(
        self,
    ):
        return self.payload


class FakeOrderV3:
    def __init__(
        self,
        details,
    ):
        self.details = details
        self.calls = []

    def get_order_detail(
        self,
        account_id,
        client_order_id,
    ):
        self.calls.append(
            (
                account_id,
                client_order_id,
            )
        )

        value = self.details[
            client_order_id
        ]

        if isinstance(
            value,
            Exception,
        ):
            raise value

        return FakeResponse(
            value
        )


class FakeTradeClient:
    def __init__(
        self,
        details,
    ):
        self.order_v3 = FakeOrderV3(
            details
        )


def historical_order(
    *,
    key="order-1",
    symbol="SOUN",
    side="SELL",
    status="FILLED",
    quantity="1",
    price="10.00",
    filled_time=1787061600000,
):
    return {
        "client_order_id": key,
        "symbol": symbol,
        "side": side,
        "status": status,
        "filled_quantity": quantity,
        "filled_price": price,
        "filled_time": filled_time,
    }


def payload(
    order=None,
):
    return [
        {
            "client_order_id": (
                "order-1"
            ),
            "combo_type": "NORMAL",
            "orders": [
                order
                if order is not None
                else historical_order()
            ],
        }
    ]


def detail(
    *,
    key="order-1",
    symbol="SOUN",
    side="SELL",
    status="FILLED",
    quantity="1",
    price="10.00",
    filled_time=1787061600000,
):
    return {
        "client_order_id": key,
        "symbol": symbol,
        "side": side,
        "status": status,
        "filled_quantity": quantity,
        "filled_price": price,
        "filled_time": filled_time,
    }


def reconciler(
    details,
):
    client = FakeTradeClient(
        details
    )

    result = (
        WebullOrderDetailReconciler(
            trade_client=client,
            account_id="sandbox-1",
        )
    )

    return result, client


def test_detail_reconciles_existing_latest_status():
    service, client = reconciler({
        "order-1": detail(
            status="CANCELLED",
        )
    })

    result = service.reconcile(
        history_payload=payload(),
        client_order_ids=(
            "order-1",
        ),
    )

    order = result[0][
        "orders"
    ][0]

    assert (
        order["status"]
        == "CANCELLED"
    )

    assert client.order_v3.calls == [
        (
            "sandbox-1",
            "order-1",
        )
    ]


def test_detail_can_advance_partial_fill():
    history_order = (
        historical_order(
            status="PARTIAL_FILLED",
            quantity="1",
            price="10.00",
        )
    )

    service, _ = reconciler({
        "order-1": detail(
            status="FILLED",
            quantity="2",
            price="10.25",
            filled_time=(
                1787061660000
            ),
        )
    })

    result = service.reconcile(
        history_payload=payload(
            history_order
        ),
        client_order_ids=(
            "order-1",
        ),
    )

    order = result[0][
        "orders"
    ][0]

    assert (
        order["filled_quantity"]
        == "2"
    )

    assert (
        order["filled_price"]
        == "10.25"
    )

    assert (
        order["filled_time"]
        == 1787061660000
    )


def test_known_filled_order_missing_from_history_is_added():
    service, _ = reconciler({
        "order-new": detail(
            key="order-new",
            side="SELL",
            quantity="1",
            price="9.50",
            filled_time=(
                1787061700000
            ),
        )
    })

    result = service.reconcile(
        history_payload=[],
        client_order_ids=(
            "order-new",
        ),
    )

    assert len(result) == 1

    assert (
        result[0][
            "orders"
        ][0][
            "client_order_id"
        ]
        == "order-new"
    )


def test_detail_client_order_id_mismatch_fails():
    service, _ = reconciler({
        "order-1": detail(
            key="different-order",
        )
    })

    with pytest.raises(
        WebullOrderDetailReconciliationError,
        match=(
            "DETAIL_CLIENT_ORDER_ID_MISMATCH"
        ),
    ):
        service.reconcile(
            history_payload=payload(),
            client_order_ids=(
                "order-1",
            ),
        )


def test_detail_symbol_mismatch_fails():
    service, _ = reconciler({
        "order-1": detail(
            symbol="BBAI",
        )
    })

    with pytest.raises(
        WebullOrderDetailReconciliationError,
        match=(
            "DETAIL_SYMBOL_MISMATCH"
        ),
    ):
        service.reconcile(
            history_payload=payload(),
            client_order_ids=(
                "order-1",
            ),
        )


def test_detail_side_mismatch_fails():
    service, _ = reconciler({
        "order-1": detail(
            side="BUY",
        )
    })

    with pytest.raises(
        WebullOrderDetailReconciliationError,
        match=(
            "DETAIL_SIDE_MISMATCH"
        ),
    ):
        service.reconcile(
            history_payload=payload(),
            client_order_ids=(
                "order-1",
            ),
        )


def test_detail_fill_regression_fails():
    service, _ = reconciler({
        "order-1": detail(
            quantity="0.5",
        )
    })

    with pytest.raises(
        WebullOrderDetailReconciliationError,
        match=(
            "DETAIL_FILL_QUANTITY_REGRESSION"
        ),
    ):
        service.reconcile(
            history_payload=payload(),
            client_order_ids=(
                "order-1",
            ),
        )


def test_new_fill_without_timestamp_fails():
    history_order = (
        historical_order(
            status="PARTIAL_FILLED",
            quantity="1",
        )
    )

    latest = detail(
        status="FILLED",
        quantity="2",
    )

    latest.pop(
        "filled_time"
    )

    service, _ = reconciler({
        "order-1": latest
    })

    with pytest.raises(
        WebullOrderDetailReconciliationError,
        match=(
            "DETAIL_NEW_FILL_TIME_MISSING"
        ),
    ):
        service.reconcile(
            history_payload=payload(
                history_order
            ),
            client_order_ids=(
                "order-1",
            ),
        )


def test_detail_request_failure_fails_closed():
    service, _ = reconciler({
        "order-1": TimeoutError(
            "simulated timeout"
        )
    })

    with pytest.raises(
        WebullOrderDetailReconciliationError,
        match=(
            "DETAIL_REQUEST_FAILED"
        ),
    ):
        service.reconcile(
            history_payload=payload(),
            client_order_ids=(
                "order-1",
            ),
        )


def test_duplicate_client_id_in_history_fails_closed():
    duplicated = payload()

    duplicated.append({
        "client_order_id": (
            "order-1"
        ),
        "combo_type": "NORMAL",
        "orders": [
            historical_order()
        ],
    })

    service, client = reconciler({
        "order-1": detail()
    })

    with pytest.raises(
        WebullOrderDetailReconciliationError,
        match=(
            "DETAIL_DUPLICATE_CLIENT_ORDER_ID"
        ),
    ):
        service.reconcile(
            history_payload=duplicated,
            client_order_ids=(
                "order-1",
            ),
        )

    assert (
        client.order_v3.calls
        == []
    )
