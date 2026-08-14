from unittest.mock import patch

from trading_bot.models import Stock
from trading_bot.webull_preview_client import (
    WebullPreviewClient,
)
from trading_bot.webull_preview_service import (
    WebullPreviewService,
)
from trading_bot.webull_safety import (
    WebullAccountState,
)


def invest_stock(
    symbol: str,
    *,
    limit_buy: float = 10.0,
    trading_stop: float = 9.0,
) -> Stock:
    stock = Stock(symbol=symbol)
    stock.signal = "INVEST"
    stock.limit_buy = limit_buy
    stock.limit_sell = limit_buy + 1.0
    stock.trading_stop_loss = trading_stop
    return stock


class FakeSnapshotClient:
    def __init__(self, state):
        self.state = state
        self.calls = 0

    def get_account_state(self):
        self.calls += 1
        return self.state


class FailingSnapshotClient:
    def get_account_state(self):
        raise RuntimeError("snapshot unavailable")


class FakePreviewClient:
    def __init__(self):
        self.requests = []

    def build_request(
        self,
        stock,
        *,
        max_position_value=None,
    ):
        return WebullPreviewClient.build_request(
            stock,
            max_position_value=max_position_value,
        )

    def preview(self, request):
        self.requests.append(request)

        return {
            "status": "PREVIEW READY",
            "submitted": False,
            "symbol": request.symbol,
            "quantity": request.quantity,
            "limitBuy": request.limit_price,
            "target": request.target_price,
            "tradingStopLoss": (
                request.trading_stop_loss
            ),
            "riskPerShare": request.risk_per_share,
            "plannedRisk": request.planned_risk,
            "estimatedPositionValue": (
                request.estimated_position_value
            ),
            "maxPositionValue": (
                request.max_position_value
            ),
            "sizingConstraint": (
                request.sizing_constraint
            ),
            "estimatedCost": (
                request.estimated_position_value
            ),
            "estimatedTransactionFee": 0.0,
            "currency": "USD",
        }


def cash_account(
    *,
    available_cash=1000.0,
    position_exposure=0.0,
    open_buy_order_exposure=0.0,
):
    return WebullAccountState(
        account_type="CASH",
        available_cash=available_cash,
        position_exposure=position_exposure,
        open_buy_order_exposure=(
            open_buy_order_exposure
        ),
        data_is_current=True,
    )


def test_preview_uses_remaining_operational_allowance():
    stock = invest_stock(
        "TEST",
        limit_buy=10.0,
        trading_stop=9.99,
    )

    preview_client = FakePreviewClient()

    service = WebullPreviewService(
        client=preview_client,
        snapshot_client=FakeSnapshotClient(
            cash_account(
                position_exposure=450.0,
            )
        ),
    )

    with (
        patch(
            "trading_bot.webull_preview_service."
            "WEBULL_PREVIEW_ENABLED",
            True,
        ),
        patch(
            "trading_bot.webull_preview_client."
            "WEBULL_PREVIEW_RISK_DOLLARS",
            25.0,
        ),
        patch(
            "trading_bot.webull_preview_client."
            "WEBULL_PREVIEW_MAX_POSITION_VALUE",
            500.0,
        ),
        patch(
            "trading_bot.webull_preview_client."
            "WEBULL_PREVIEW_MAX_SHARES",
            1000,
        ),
    ):
        results = service.prepare_previews({
            stock.symbol: stock
        })

    assert len(results) == 1
    assert results[0]["status"] == "PREVIEW READY"
    assert results[0]["quantity"] == 2
    assert (
        results[0]["estimatedPositionValue"]
        == 20.0
    )
    assert (
        results[0]["remainingAllowanceBeforePreview"]
        == 25.0
    )


def test_multiple_previews_reserve_shared_cap():
    first = invest_stock(
        "ONE",
        limit_buy=10.0,
        trading_stop=9.0,
    )
    second = invest_stock(
        "TWO",
        limit_buy=10.0,
        trading_stop=9.0,
    )

    service = WebullPreviewService(
        client=FakePreviewClient(),
        snapshot_client=FakeSnapshotClient(
            cash_account()
        ),
    )

    with (
        patch(
            "trading_bot.webull_preview_service."
            "WEBULL_PREVIEW_ENABLED",
            True,
        ),
        patch(
            "trading_bot.webull_preview_client."
            "WEBULL_PREVIEW_RISK_DOLLARS",
            250.0,
        ),
        patch(
            "trading_bot.webull_preview_client."
            "WEBULL_PREVIEW_MAX_POSITION_VALUE",
            500.0,
        ),
        patch(
            "trading_bot.webull_preview_client."
            "WEBULL_PREVIEW_MAX_SHARES",
            1000,
        ),
    ):
        results = service.prepare_previews({
            first.symbol: first,
            second.symbol: second,
        })

    assert results[0]["status"] == "PREVIEW READY"
    assert results[0]["quantity"] == 23
    assert results[0]["estimatedPositionValue"] == 230.0
    assert results[0]["recommendedAllocation"] == 237.5
    assert results[0]["allocationWeight"] == 0.5

    assert results[1]["status"] == "PREVIEW READY"
    assert results[1]["quantity"] == 23
    assert results[1]["estimatedPositionValue"] == 230.0
    assert results[1]["recommendedAllocation"] == 237.5
    assert results[1]["allocationWeight"] == 0.5

    assert (
        results[0]["capitalAllocationMethod"]
        == "EQUAL_WEIGHT_CASH_SAFE"
    )
    assert (
        results[1]["capitalAllocationMethod"]
        == "EQUAL_WEIGHT_CASH_SAFE"
    )


def test_margin_account_preview_is_rejected():
    stock = invest_stock("TEST")

    service = WebullPreviewService(
        client=FakePreviewClient(),
        snapshot_client=FakeSnapshotClient(
            WebullAccountState(
                account_type="MARGIN",
                available_cash=1000.0,
                position_exposure=0.0,
                open_buy_order_exposure=0.0,
            )
        ),
    )

    with patch(
        "trading_bot.webull_preview_service."
        "WEBULL_PREVIEW_ENABLED",
        True,
    ):
        result = service.prepare_previews({
            stock.symbol: stock
        })[0]

    assert result["status"] == "PREVIEW FAILED"
    assert result["safetyAllowed"] is False
    assert result["safetyReason"] == (
        "CASH_ACCOUNT_REQUIRED"
    )


def test_snapshot_failure_blocks_all_previews():
    one = invest_stock("ONE")
    two = invest_stock("TWO")

    client = FakePreviewClient()

    service = WebullPreviewService(
        client=client,
        snapshot_client=FailingSnapshotClient(),
    )

    with patch(
        "trading_bot.webull_preview_service."
        "WEBULL_PREVIEW_ENABLED",
        True,
    ):
        results = service.prepare_previews({
            one.symbol: one,
            two.symbol: two,
        })

    assert len(results) == 2
    assert all(
        result["status"] == "PREVIEW FAILED"
        for result in results
    )
    assert all(
        result["safetyReason"]
        == "ACCOUNT_SNAPSHOT_FAILED"
        for result in results
    )
    assert client.requests == []


def test_preview_requires_later_manual_approval():
    stock = invest_stock("TEST")

    service = WebullPreviewService(
        client=FakePreviewClient(),
        snapshot_client=FakeSnapshotClient(
            cash_account()
        ),
    )

    with patch(
        "trading_bot.webull_preview_service."
        "WEBULL_PREVIEW_ENABLED",
        True,
    ):
        result = service.prepare_previews({
            stock.symbol: stock
        })[0]

    assert result["safetyAllowed"] is True
    assert result["manualApprovalRequired"] is True
    assert result["manualApprovalGranted"] is False
    assert result["submitted"] is False


def test_service_exposes_no_order_actions():
    service = WebullPreviewService(
        client=FakePreviewClient(),
        snapshot_client=FakeSnapshotClient(
            cash_account()
        ),
    )

    assert not hasattr(service, "place_order")
    assert not hasattr(service, "submit_order")
    assert not hasattr(service, "replace_order")
    assert not hasattr(service, "cancel_order")
