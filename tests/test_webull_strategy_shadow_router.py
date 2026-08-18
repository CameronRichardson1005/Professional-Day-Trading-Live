from datetime import UTC, datetime

import pytest

from trading_bot.config import (
    MANIPULATION_STRATEGY_NAME,
)
from trading_bot.webull_account_risk import (
    WebullExecutionRiskLimits,
    WebullExecutionRiskState,
)
from trading_bot.webull_safety import (
    WebullAccountState,
)
from trading_bot.webull_shadow_execution import (
    WebullShadowExecutionCoordinator,
    WebullShadowExecutionJournal,
)
from trading_bot.webull_strategy_shadow_router import (
    WebullStrategyShadowRouter,
    WebullStrategyShadowRouterError,
)


NOW = datetime(
    2026,
    8,
    18,
    18,
    45,
    tzinfo=UTC,
)


def account(
    *,
    available_cash=1000.0,
    position_exposure=0.0,
    open_buy_order_exposure=0.0,
):
    return WebullAccountState(
        account_type="CASH",
        available_cash=(
            available_cash
        ),
        position_exposure=(
            position_exposure
        ),
        open_buy_order_exposure=(
            open_buy_order_exposure
        ),
        data_is_current=True,
        buying_power=(
            available_cash
        ),
    )


def risk_state(
    *,
    daily_realized_pnl=0.0,
    kill_switch_active=False,
):
    return WebullExecutionRiskState(
        daily_realized_pnl=(
            daily_realized_pnl
        ),
        open_position_symbols=(),
        open_order_symbols=(),
        pending_buy_symbols=(),
        position_exposures=(),
        pending_buy_exposures=(),
        kill_switch_active=(
            kill_switch_active
        ),
        data_is_current=True,
    )


def limits():
    return WebullExecutionRiskLimits(
        max_daily_loss=100.0,
        max_open_positions=3,
        max_open_orders=3,
        max_position_exposure=500.0,
    )


def manipulation_preview():
    return {
        "status": "PREVIEW READY",
        "submitted": False,
        "safetyAllowed": True,
        "safetyReason": (
            "PREVIEW_ELIGIBLE"
        ),
        "symbol": "OPEN",
        "strategyName": (
            MANIPULATION_STRATEGY_NAME
        ),
        "quantity": 10,
        "limitBuy": 10.0,
        "target": 10.50,
        "tradingStopLoss": 9.50,
        "proposedExposure": 100.0,
    }


def quick_flip_preview():
    return {
        "status": "PREVIEW READY",
        "submitted": False,
        "safetyAllowed": True,
        "safetyReason": (
            "PREVIEW_ELIGIBLE"
        ),
        "symbol": "SOUN",
        "strategyName": (
            "QUICK_FLIP"
        ),
        "side": "BUY",
        "quantity": 20,
        "limitBuy": 5.0,
        "takeProfit1": 5.25,
        "takeProfit2": 5.50,
        "automaticStopLoss": False,
        "proposedExposure": 100.0,
    }


def build_router(
    tmp_path,
):
    journal = (
        WebullShadowExecutionJournal(
            tmp_path
            / "shadow.json"
        )
    )

    coordinator = (
        WebullShadowExecutionCoordinator(
            journal=journal,
            clock=lambda: NOW,
        )
    )

    router = (
        WebullStrategyShadowRouter(
            coordinator=coordinator
        )
    )

    return (
        router,
        journal,
    )


def test_manipulation_preview_reaches_shadow_journal(
    tmp_path,
):
    router, journal = (
        build_router(
            tmp_path
        )
    )

    record = (
        router
        .evaluate_manipulation_preview(
            preview=(
                manipulation_preview()
            ),
            account=account(),
            risk_state=risk_state(),
            risk_limits=limits(),
        )
    )

    assert (
        record.status
        == "ACCEPTED_SHADOW"
    )

    assert (
        record.strategy_name
        == MANIPULATION_STRATEGY_NAME
    )

    assert record.symbol == "OPEN"
    assert record.quantity == 10
    assert record.limit_price == 10.0

    assert (
        record.broker_submission_attempted
        is False
    )

    persisted = journal.load()

    assert len(
        persisted
    ) == 1

    assert (
        persisted[0]["status"]
        == "ACCEPTED_SHADOW"
    )


def test_quick_flip_preview_reaches_shadow_journal(
    tmp_path,
):
    router, journal = (
        build_router(
            tmp_path
        )
    )

    record = (
        router
        .evaluate_quick_flip_preview(
            preview=(
                quick_flip_preview()
            ),
            account=account(),
            risk_state=risk_state(),
            risk_limits=limits(),
        )
    )

    assert (
        record.status
        == "ACCEPTED_SHADOW"
    )

    assert (
        record.strategy_name
        == "QUICK_FLIP"
    )

    assert record.symbol == "SOUN"
    assert record.quantity == 20
    assert record.limit_price == 5.0

    assert (
        record.broker_submission_attempted
        is False
    )

    persisted = journal.load()

    assert len(
        persisted
    ) == 1

    assert (
        persisted[0]["strategy_name"]
        == "QUICK_FLIP"
    )


def test_both_strategies_share_shadow_boundary(
    tmp_path,
):
    router, journal = (
        build_router(
            tmp_path
        )
    )

    first = (
        router
        .evaluate_manipulation_preview(
            preview=(
                manipulation_preview()
            ),
            account=account(),
            risk_state=risk_state(),
            risk_limits=limits(),
        )
    )

    second = (
        router
        .evaluate_quick_flip_preview(
            preview=(
                quick_flip_preview()
            ),
            account=account(),
            risk_state=risk_state(),
            risk_limits=limits(),
        )
    )

    assert (
        first.status
        == "ACCEPTED_SHADOW"
    )

    assert (
        second.status
        == "ACCEPTED_SHADOW"
    )

    records = journal.load()

    assert len(
        records
    ) == 2

    assert {
        item[
            "strategy_name"
        ]
        for item in records
    } == {
        MANIPULATION_STRATEGY_NAME,
        "QUICK_FLIP",
    }

    assert all(
        item[
            "broker_submission_attempted"
        ]
        is False
        for item in records
    )


def test_manipulation_adapter_failure_does_not_write_journal(
    tmp_path,
):
    router, journal = (
        build_router(
            tmp_path
        )
    )

    preview = (
        manipulation_preview()
    )

    preview[
        "status"
    ] = "PREVIEW FAILED"

    with pytest.raises(
        Exception,
        match=(
            "MANIPULATION_PREVIEW_NOT_READY"
        ),
    ):
        router.evaluate_manipulation_preview(
            preview=preview,
            account=account(),
            risk_state=risk_state(),
            risk_limits=limits(),
        )

    assert journal.load() == ()


def test_quick_flip_adapter_failure_does_not_write_journal(
    tmp_path,
):
    router, journal = (
        build_router(
            tmp_path
        )
    )

    preview = (
        quick_flip_preview()
    )

    preview[
        "automaticStopLoss"
    ] = True

    with pytest.raises(
        Exception,
        match=(
            "QUICK_FLIP_AUTOMATIC_"
            "STOP_STATE_INVALID"
        ),
    ):
        router.evaluate_quick_flip_preview(
            preview=preview,
            account=account(),
            risk_state=risk_state(),
            risk_limits=limits(),
        )

    assert journal.load() == ()


def test_account_risk_rejection_is_shadow_only(
    tmp_path,
):
    router, journal = (
        build_router(
            tmp_path
        )
    )

    record = (
        router
        .evaluate_manipulation_preview(
            preview=(
                manipulation_preview()
            ),
            account=account(),
            risk_state=risk_state(
                kill_switch_active=True
            ),
            risk_limits=limits(),
        )
    )

    assert (
        record.status
        == "REJECTED_SHADOW"
    )

    assert (
        record.risk_allowed
        is False
    )

    assert (
        record.broker_submission_attempted
        is False
    )

    assert len(
        journal.load()
    ) == 1


def test_safety_rejection_is_shadow_only(
    tmp_path,
):
    router, journal = (
        build_router(
            tmp_path
        )
    )

    # $400 current exposure + $100 proposed is above the
    # configured $475 operational cap while remaining within
    # the hard $500 cap.
    record = (
        router
        .evaluate_manipulation_preview(
            preview=(
                manipulation_preview()
            ),
            account=account(
                position_exposure=400.0
            ),
            risk_state=risk_state(),
            risk_limits=limits(),
        )
    )

    assert (
        record.status
        == "REJECTED_SHADOW"
    )

    assert (
        record.risk_allowed
        is True
    )

    assert (
        record.safety_allowed
        is False
    )

    assert (
        record.broker_submission_attempted
        is False
    )

    assert len(
        journal.load()
    ) == 1


def test_invalid_coordinator_is_rejected():
    with pytest.raises(
        WebullStrategyShadowRouterError,
        match=(
            "^SHADOW_COORDINATOR_INVALID$"
        ),
    ):
        WebullStrategyShadowRouter(
            coordinator=object()
        )


def test_router_exposes_no_broker_mutation_actions(
    tmp_path,
):
    router, _ = (
        build_router(
            tmp_path
        )
    )

    for name in (
        "place_order",
        "submit",
        "submit_order",
        "replace_order",
        "cancel_order",
        "close_order",
    ):
        assert not hasattr(
            router,
            name,
        )
