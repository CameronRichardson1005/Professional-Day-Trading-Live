from datetime import UTC, datetime
from types import SimpleNamespace

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
)
from trading_bot.webull_strategy_shadow_service import (
    WebullStrategyShadowService,
    WebullStrategyShadowServiceError,
)


NOW = datetime(
    2026,
    8,
    18,
    19,
    0,
    tzinfo=UTC,
)


def account(
    *,
    current=True,
):
    return WebullAccountState(
        account_type="CASH",
        available_cash=1000.0,
        position_exposure=0.0,
        open_buy_order_exposure=0.0,
        data_is_current=current,
        buying_power=1000.0,
    )


def risk_state(
    *,
    kill=False,
    current=True,
):
    return WebullExecutionRiskState(
        daily_realized_pnl=0.0,
        open_position_symbols=(),
        open_order_symbols=(),
        pending_buy_symbols=(),
        position_exposures=(),
        pending_buy_exposures=(),
        kill_switch_active=kill,
        data_is_current=current,
    )


def limits():
    return WebullExecutionRiskLimits(
        max_daily_loss=100.0,
        max_open_positions=3,
        max_open_orders=3,
        max_position_exposure=500.0,
    )


def snapshot(
    *,
    account_id="sandbox-account-1",
    account_value=None,
    risk_value=None,
    limit_value=None,
):
    return SimpleNamespace(
        account_id=account_id,
        account_state=(
            account()
            if account_value is None
            else account_value
        ),
        risk_state=(
            risk_state()
            if risk_value is None
            else risk_value
        ),
        risk_limits=(
            limits()
            if limit_value is None
            else limit_value
        ),
    )


class FakeRiskSnapshotClient:
    def __init__(
        self,
        values,
    ):
        self.values = list(
            values
        )
        self.calls = 0

    def get_snapshot(
        self,
    ):
        self.calls += 1

        if not self.values:
            raise RuntimeError(
                "no snapshot"
            )

        value = self.values.pop(0)

        if isinstance(
            value,
            Exception,
        ):
            raise value

        return value


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
        "strategyName": "QUICK_FLIP",
        "side": "BUY",
        "quantity": 20,
        "limitBuy": 5.0,
        "takeProfit1": 5.25,
        "takeProfit2": 5.50,
        "automaticStopLoss": False,
        "proposedExposure": 100.0,
    }


def build_service(
    tmp_path,
    *,
    snapshots=None,
):
    journal = WebullShadowExecutionJournal(
        tmp_path / "shadow.json"
    )

    coordinator = (
        WebullShadowExecutionCoordinator(
            journal=journal,
            clock=lambda: NOW,
        )
    )

    router = WebullStrategyShadowRouter(
        coordinator=coordinator
    )

    client = FakeRiskSnapshotClient(
        snapshots
        if snapshots is not None
        else [snapshot()]
    )

    service = (
        WebullStrategyShadowService(
            router=router,
            risk_snapshot_client=client,
        )
    )

    return (
        service,
        client,
        journal,
    )


def test_manipulation_uses_fresh_snapshot_and_records_shadow(
    tmp_path,
):
    service, client, journal = (
        build_service(
            tmp_path
        )
    )

    record = (
        service
        .evaluate_manipulation_preview(
            preview=(
                manipulation_preview()
            )
        )
    )

    assert client.calls == 1

    assert (
        record.status
        == "ACCEPTED_SHADOW"
    )

    assert (
        record.strategy_name
        == MANIPULATION_STRATEGY_NAME
    )

    assert (
        record.broker_submission_attempted
        is False
    )

    assert len(
        journal.load()
    ) == 1


def test_quick_flip_uses_fresh_snapshot_and_records_shadow(
    tmp_path,
):
    service, client, journal = (
        build_service(
            tmp_path
        )
    )

    record = (
        service
        .evaluate_quick_flip_preview(
            preview=(
                quick_flip_preview()
            )
        )
    )

    assert client.calls == 1

    assert (
        record.status
        == "ACCEPTED_SHADOW"
    )

    assert (
        record.strategy_name
        == "QUICK_FLIP"
    )

    assert (
        record.broker_submission_attempted
        is False
    )

    assert len(
        journal.load()
    ) == 1


def test_every_preview_refreshes_risk_snapshot(
    tmp_path,
):
    service, client, journal = (
        build_service(
            tmp_path,
            snapshots=[
                snapshot(),
                snapshot(),
            ],
        )
    )

    service.evaluate_manipulation_preview(
        preview=(
            manipulation_preview()
        )
    )

    service.evaluate_quick_flip_preview(
        preview=(
            quick_flip_preview()
        )
    )

    assert client.calls == 2

    assert len(
        journal.load()
    ) == 2


def test_kill_switch_rejection_is_shadow_only(
    tmp_path,
):
    service, client, journal = (
        build_service(
            tmp_path,
            snapshots=[
                snapshot(
                    risk_value=(
                        risk_state(
                            kill=True
                        )
                    )
                )
            ],
        )
    )

    record = (
        service
        .evaluate_manipulation_preview(
            preview=(
                manipulation_preview()
            )
        )
    )

    assert client.calls == 1

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


def test_snapshot_failure_does_not_reach_shadow_journal(
    tmp_path,
):
    service, client, journal = (
        build_service(
            tmp_path,
            snapshots=[
                RuntimeError(
                    "simulated"
                )
            ],
        )
    )

    with pytest.raises(
        WebullStrategyShadowServiceError,
        match=(
            "^SHADOW_RISK_SNAPSHOT_UNAVAILABLE$"
        ),
    ):
        service.evaluate_manipulation_preview(
            preview=(
                manipulation_preview()
            )
        )

    assert client.calls == 1
    assert journal.load() == ()


def test_missing_account_id_fails_closed(
    tmp_path,
):
    service, _, journal = (
        build_service(
            tmp_path,
            snapshots=[
                snapshot(
                    account_id=""
                )
            ],
        )
    )

    with pytest.raises(
        WebullStrategyShadowServiceError,
        match=(
            "^SHADOW_RISK_ACCOUNT_ID_MISSING$"
        ),
    ):
        service.evaluate_manipulation_preview(
            preview=(
                manipulation_preview()
            )
        )

    assert journal.load() == ()


def test_stale_account_state_fails_before_router(
    tmp_path,
):
    service, _, journal = (
        build_service(
            tmp_path,
            snapshots=[
                snapshot(
                    account_value=(
                        account(
                            current=False
                        )
                    )
                )
            ],
        )
    )

    with pytest.raises(
        WebullStrategyShadowServiceError,
        match=(
            "^SHADOW_RISK_SNAPSHOT_STALE_OR_UNKNOWN$"
        ),
    ):
        service.evaluate_manipulation_preview(
            preview=(
                manipulation_preview()
            )
        )

    assert journal.load() == ()


def test_stale_risk_state_fails_before_router(
    tmp_path,
):
    service, _, journal = (
        build_service(
            tmp_path,
            snapshots=[
                snapshot(
                    risk_value=(
                        risk_state(
                            current=False
                        )
                    )
                )
            ],
        )
    )

    with pytest.raises(
        WebullStrategyShadowServiceError,
        match=(
            "^SHADOW_RISK_SNAPSHOT_STALE_OR_UNKNOWN$"
        ),
    ):
        service.evaluate_quick_flip_preview(
            preview=(
                quick_flip_preview()
            )
        )

    assert journal.load() == ()


def test_invalid_router_is_rejected():
    with pytest.raises(
        WebullStrategyShadowServiceError,
        match=(
            "^SHADOW_ROUTER_INVALID$"
        ),
    ):
        WebullStrategyShadowService(
            router=object(),
            risk_snapshot_client=(
                FakeRiskSnapshotClient(
                    [snapshot()]
                )
            ),
        )


def test_invalid_snapshot_client_is_rejected(
    tmp_path,
):
    journal = WebullShadowExecutionJournal(
        tmp_path / "shadow.json"
    )

    coordinator = (
        WebullShadowExecutionCoordinator(
            journal=journal,
            clock=lambda: NOW,
        )
    )

    router = WebullStrategyShadowRouter(
        coordinator=coordinator
    )

    with pytest.raises(
        WebullStrategyShadowServiceError,
        match=(
            "^SHADOW_RISK_SNAPSHOT_CLIENT_INVALID$"
        ),
    ):
        WebullStrategyShadowService(
            router=router,
            risk_snapshot_client=object(),
        )
