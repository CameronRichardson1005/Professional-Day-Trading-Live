from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from trading_bot.config import (
    MANIPULATION_STRATEGY_NAME,
)
from trading_bot.quick_flip_webull_preview_service import (
    QuickFlipWebullPreviewService,
)
from trading_bot.webull_preview_service import (
    WebullPreviewService,
)
from trading_bot.webull_safety import (
    WebullAccountState,
)


NOW = datetime(
    2026,
    8,
    18,
    18,
    40,
    tzinfo=UTC,
)


@pytest.fixture(autouse=True)
def enable_preview_for_funding_tests(
    monkeypatch,
):
    """
    These tests exercise preview funding semantics directly.

    Production WEBULL_PREVIEW_ENABLED remains unchanged; only the
    imported module globals are enabled for each isolated test.
    """
    import trading_bot.webull_preview_service as manipulation_module
    import trading_bot.quick_flip_webull_preview_service as quick_flip_module

    monkeypatch.setattr(
        manipulation_module,
        "WEBULL_PREVIEW_ENABLED",
        True,
    )

    monkeypatch.setattr(
        quick_flip_module,
        "WEBULL_PREVIEW_ENABLED",
        True,
    )


class SnapshotClient:
    def get_account_state(self):
        return WebullAccountState(
            account_type="CASH",
            available_cash=1000.0,
            position_exposure=0.0,
            open_buy_order_exposure=0.0,
            data_is_current=True,
            buying_power=1000.0,
        )


class PreviewStore:
    def __init__(self):
        self.records = None

    def save_previews(
        self,
        records,
    ):
        self.records = records


class CapitalStore:
    def __init__(
        self,
        *,
        fail_reservation=False,
    ):
        self.fail_reservation = (
            fail_reservation
        )

        self.reservations = []

    def current_trading_date(self):
        return "2026-08-18"

    def total_reserved_exposure(
        self,
        date_str,
    ):
        assert (
            date_str
            == "2026-08-18"
        )

        return 0.0

    def reserve(
        self,
        **kwargs,
    ):
        if self.fail_reservation:
            raise RuntimeError(
                "simulated reservation failure"
            )

        self.reservations.append(
            kwargs
        )


class ManipulationClient:
    def build_request(
        self,
        stock,
        *,
        max_position_value,
    ):
        del max_position_value

        return SimpleNamespace(
            symbol=stock.symbol,
            quantity=10,
            limit_price=10.0,
            estimated_position_value=100.0,
        )

    def preview(
        self,
        request,
    ):
        return {
            "status": "PREVIEW READY",
            "symbol": request.symbol,
            "quantity": request.quantity,
            "limitBuy": request.limit_price,
            "target": 10.50,
            "tradingStopLoss": 9.50,
            "estimatedPositionValue": 100.0,
            "maxPositionValue": 100.0,
            "sizingConstraint": "TEST",
            "estimatedCost": 100.0,
            "estimatedTransactionFee": 0.0,
        }


class QuickFlipClient:
    def preview(
        self,
        request,
    ):
        return {
            "status": "PREVIEW READY",
            "symbol": request.symbol,
            "side": "BUY",
            "quantity": request.quantity,
            "limitBuy": request.limit_price,
            "takeProfit1": 5.25,
            "takeProfit2": 5.50,
            "automaticStopLoss": False,
            "estimatedPositionValue": 100.0,
            "maxPositionValue": 100.0,
            "sizingConstraint": "TEST",
            "estimatedCost": 100.0,
            "estimatedTransactionFee": 0.0,
        }


def manipulation_stock():
    return SimpleNamespace(
        symbol="OPEN",
        signal="INVEST",
        strategy_name=(
            MANIPULATION_STRATEGY_NAME
        ),
        reward_risk=2.0,
        confirmation_time=None,
        retracement_price=None,
        impulse_atr_multiple=None,
        pullback_volume_ratio=None,
        webull_preview=None,
    )


def quick_flip_results():
    signal = SimpleNamespace(
        signal="INVEST",
        confirmation_time=NOW,
        entry_price=5.0,
        take_profit_1=5.25,
        take_profit_2=5.50,
    )

    return {
        "SOUN": SimpleNamespace(
            signal=signal
        )
    }


def allocation_plan(
    *,
    symbol,
):
    item = SimpleNamespace(
        symbol=symbol,
        recommended_allocation=100.0,
        allocation_weight=1.0,
        score=1.0,
    )

    return SimpleNamespace(
        decision_reason=(
            "DOMINANT_OPPORTUNITY"
        ),
        allocations=(
            item,
        ),
    )


def test_manipulation_positive_allocation_is_not_funded_when_reservation_fails(
    monkeypatch,
):
    import trading_bot.webull_preview_service as module

    monkeypatch.setattr(
        module,
        "build_live_manipulation_allocation_plan",
        lambda **kwargs: allocation_plan(
            symbol="OPEN"
        ),
    )

    monkeypatch.setattr(
        module,
        "rank_committed_allocations",
        lambda plan: list(
            plan.allocations
        ),
    )

    capital_store = CapitalStore(
        fail_reservation=True
    )

    service = WebullPreviewService(
        client=ManipulationClient(),
        snapshot_client=SnapshotClient(),
        preview_store=PreviewStore(),
    )

    service.capital_reservation_store = (
        capital_store
    )

    results = service.prepare_previews(
        stocks={
            "OPEN": manipulation_stock()
        },
        trading_date="2026-08-18",
    )

    assert (
        service.committed_policy_funded
        is False
    )

    assert len(results) == 1

    assert (
        results[0]["status"]
        == "PREVIEW FAILED"
    )


def test_manipulation_ready_reserved_preview_marks_policy_funded(
    monkeypatch,
):
    import trading_bot.webull_preview_service as module

    monkeypatch.setattr(
        module,
        "build_live_manipulation_allocation_plan",
        lambda **kwargs: allocation_plan(
            symbol="OPEN"
        ),
    )

    monkeypatch.setattr(
        module,
        "rank_committed_allocations",
        lambda plan: list(
            plan.allocations
        ),
    )

    capital_store = CapitalStore()

    service = WebullPreviewService(
        client=ManipulationClient(),
        snapshot_client=SnapshotClient(),
        preview_store=PreviewStore(),
    )

    service.capital_reservation_store = (
        capital_store
    )

    results = service.prepare_previews(
        stocks={
            "OPEN": manipulation_stock()
        },
        trading_date="2026-08-18",
    )

    assert len(results) == 1

    assert (
        results[0]["status"]
        == "PREVIEW READY"
    )

    assert (
        service.committed_policy_funded
        is True
    )

    assert len(
        capital_store.reservations
    ) == 1


def test_quick_flip_positive_allocation_is_not_funded_when_reservation_fails(
    monkeypatch,
):
    import trading_bot.quick_flip_webull_preview_service as module

    monkeypatch.setattr(
        module,
        "build_live_quick_flip_allocation_plan",
        lambda **kwargs: allocation_plan(
            symbol="SOUN"
        ),
    )

    monkeypatch.setattr(
        module,
        "rank_committed_allocations",
        lambda plan: list(
            plan.allocations
        ),
    )

    monkeypatch.setattr(
        module,
        "build_quick_flip_preview_request",
        lambda **kwargs: SimpleNamespace(
            symbol=kwargs["symbol"],
            quantity=20,
            limit_price=5.0,
            estimated_position_value=100.0,
        ),
    )

    capital_store = CapitalStore(
        fail_reservation=True
    )

    service = (
        QuickFlipWebullPreviewService(
            client=QuickFlipClient(),
            snapshot_client=SnapshotClient(),
            preview_store=PreviewStore(),
        )
    )

    service.capital_reservation_store = (
        capital_store
    )

    results = service.prepare_previews(
        quick_flip_results(),
        trading_date="2026-08-18",
    )

    assert (
        service.committed_policy_funded
        is False
    )

    assert len(results) == 1

    assert (
        results[0]["status"]
        == "PREVIEW FAILED"
    )


def test_quick_flip_ready_reserved_preview_marks_policy_funded(
    monkeypatch,
):
    import trading_bot.quick_flip_webull_preview_service as module

    monkeypatch.setattr(
        module,
        "build_live_quick_flip_allocation_plan",
        lambda **kwargs: allocation_plan(
            symbol="SOUN"
        ),
    )

    monkeypatch.setattr(
        module,
        "rank_committed_allocations",
        lambda plan: list(
            plan.allocations
        ),
    )

    monkeypatch.setattr(
        module,
        "build_quick_flip_preview_request",
        lambda **kwargs: SimpleNamespace(
            symbol=kwargs["symbol"],
            quantity=20,
            limit_price=5.0,
            estimated_position_value=100.0,
        ),
    )

    capital_store = CapitalStore()

    service = (
        QuickFlipWebullPreviewService(
            client=QuickFlipClient(),
            snapshot_client=SnapshotClient(),
            preview_store=PreviewStore(),
        )
    )

    service.capital_reservation_store = (
        capital_store
    )

    results = service.prepare_previews(
        quick_flip_results(),
        trading_date="2026-08-18",
    )

    assert len(results) == 1

    assert (
        results[0]["status"]
        == "PREVIEW READY"
    )

    assert (
        service.committed_policy_funded
        is True
    )

    assert len(
        capital_store.reservations
    ) == 1
