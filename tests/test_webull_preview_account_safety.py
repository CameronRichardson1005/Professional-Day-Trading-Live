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


def test_preview_uses_dynamic_cash_safe_allowance():
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
    assert results[0]["quantity"] == 90
    assert (
        results[0]["estimatedPositionValue"]
        == 900.0
    )
    assert (
        results[0]["remainingAllowanceBeforePreview"]
        == 900.0
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
    assert results[0]["quantity"] == 45
    assert results[0]["estimatedPositionValue"] == 450.0
    assert results[0]["recommendedAllocation"] == 450.0
    assert results[0]["allocationWeight"] == 0.5

    assert results[1]["status"] == "PREVIEW READY"
    assert results[1]["quantity"] == 45
    assert results[1]["estimatedPositionValue"] == 450.0
    assert results[1]["recommendedAllocation"] == 450.0
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


def test_live_equal_weight_rebalances_unbuyable_whole_share_budgets(
    monkeypatch,
):
    """
    Regression for the 2026-08-20 small-account failure.

    A $50 cash account has a $45 deployable preview pool at the
    90% deployment fraction. Five live Manipulation INVEST
    opportunities initially receive about $9 each.

    Candidates whose equal-weight budget cannot buy one whole
    share must release that capital. The remaining funded,
    whole-share-feasible candidates are then equal-weighted from
    the same original safe pool.

    Broker submission remains disabled.
    """
    from types import SimpleNamespace

    import trading_bot.webull_preview_service as module

    stocks = {
        "BBAI": invest_stock(
            "BBAI",
            limit_buy=3.12,
            trading_stop=3.00,
        ),
        "OPEN": invest_stock(
            "OPEN",
            limit_buy=3.485,
            trading_stop=3.30,
        ),
        "SOFI": invest_stock(
            "SOFI",
            limit_buy=18.37,
            trading_stop=18.00,
        ),
        "RIVN": invest_stock(
            "RIVN",
            limit_buy=14.00,
            trading_stop=13.80,
        ),
        "PLTR": invest_stock(
            "PLTR",
            limit_buy=170.00,
            trading_stop=169.00,
        ),
    }

    def fake_live_plan(
        *,
        stocks,
        trading_date,
        deployable_pool,
    ):
        symbols = (
            "BBAI",
            "OPEN",
            "SOFI",
            "RIVN",
            "PLTR",
        )

        equal_budget = round(
            deployable_pool / len(symbols),
            2,
        )

        return SimpleNamespace(
            decision_reason=(
                "EQUAL_WEIGHT_PORTFOLIO"
            ),
            allocations=tuple(
                SimpleNamespace(
                    symbol=symbol,
                    recommended_allocation=(
                        equal_budget
                    ),
                    allocation_weight=0.2,
                    score=1.0,
                )
                for symbol in symbols
            ),
        )

    monkeypatch.setattr(
        module,
        "build_live_manipulation_allocation_plan",
        fake_live_plan,
    )

    preview_client = FakePreviewClient()

    service = WebullPreviewService(
        client=preview_client,
        snapshot_client=FakeSnapshotClient(
            cash_account(
                available_cash=50.0,
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
            "trading_bot.webull_preview_service."
            "WEBULL_CAPITAL_DEPLOYMENT_FRACTION",
            0.90,
        ),
        patch(
            "trading_bot.webull_preview_client."
            "WEBULL_PREVIEW_RISK_DOLLARS",
            1000.0,
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
        results = service.prepare_previews(
            stocks,
            trading_date="2026-08-20",
        )

    ready = {
        result["symbol"]: result
        for result in results
        if result["status"] == "PREVIEW READY"
    }

    # Find the largest equal-weight subset that can actually buy
    # at least one whole share at each Manipulation limit.
    #
    # $45 / 3 = $15, so BBAI, OPEN, and RIVN are executable.
    # SOFI and PLTR still require more than $15 for one share.
    assert set(ready) == {
        "BBAI",
        "OPEN",
        "RIVN",
    }

    # Unusable allocations must be redistributed instead of
    # leaving most of the $45 safe pool stranded.
    assert (
        ready["BBAI"]["recommendedAllocation"]
        == 15.00
    )
    assert (
        ready["OPEN"]["recommendedAllocation"]
        == 15.00
    )
    assert (
        ready["RIVN"]["recommendedAllocation"]
        == 15.00
    )

    # Metadata describes the executable three-way portfolio.
    expected_weight = round(1.0 / 3.0, 6)

    assert (
        ready["BBAI"]["allocationWeight"]
        == expected_weight
    )
    assert (
        ready["OPEN"]["allocationWeight"]
        == expected_weight
    )
    assert (
        ready["RIVN"]["allocationWeight"]
        == expected_weight
    )

    # Whole-share rounding may leave a few dollars, but should
    # no longer strand the majority of the deployable pool.
    actually_deployed = sum(
        result["estimatedPositionValue"]
        for result in ready.values()
    )

    assert actually_deployed > 40.0

    assert (
        service.committed_policy_decision_reason
        == "EQUAL_WEIGHT_PORTFOLIO"
    )
