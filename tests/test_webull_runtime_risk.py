from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from trading_bot.webull_account_parser import (
    ParsedWebullOpenOrder,
    ParsedWebullPosition,
)
from trading_bot.webull_execution import (
    WebullTradeIntent,
)
from trading_bot.webull_runtime_risk import (
    WebullRiskProtectedSubmissionService,
    WebullRuntimeRiskError,
    WebullRuntimeRiskSnapshotClient,
)
from trading_bot.webull_safety import (
    WebullAccountState,
)


NOW = datetime(
    2026,
    8,
    18,
    12,
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
        position_exposure=100.0,
        open_buy_order_exposure=50.0,
        data_is_current=current,
        buying_power=1000.0,
    )


def position():
    return ParsedWebullPosition(
        symbol="SOUN",
        quantity=5.0,
        market_price=20.0,
        market_value=100.0,
    )


def pending_buy():
    return ParsedWebullOpenOrder(
        symbol="OPEN",
        side="BUY",
        remaining_quantity=5.0,
        limit_price=10.0,
        reserved_exposure=50.0,
    )


def snapshot(
    *,
    current=True,
):
    return SimpleNamespace(
        account_id="sandbox-account-1",
        account_state=account(
            current=current
        ),
        position_count=1,
        open_order_count=1,
        positions=(
            position(),
        ),
        open_orders=(
            pending_buy(),
        ),
    )


class FakeSnapshotClient:
    def __init__(
        self,
        value,
    ):
        self.value = value
        self.calls = 0

    def get_snapshot(
        self,
    ):
        self.calls += 1
        return self.value


class FakeExecutionManager:
    def __init__(
        self,
    ):
        self.calls = []

    def submit_with_account_risk(
        self,
        *,
        intent,
        account,
        risk_state,
        risk_limits,
    ):
        self.calls.append({
            "intent": intent,
            "account": account,
            "risk_state": risk_state,
            "risk_limits": risk_limits,
        })

        return "SUBMITTED"


def source(
    *,
    snapshot_value=None,
    pnl_provider=None,
    kill_provider=None,
):
    return WebullRuntimeRiskSnapshotClient(
        snapshot_client=(
            FakeSnapshotClient(
                snapshot_value
                if snapshot_value
                is not None
                else snapshot()
            )
        ),
        daily_realized_pnl_provider=(
            pnl_provider
            if pnl_provider
            is not None
            else lambda: -7.50
        ),
        kill_switch_provider=(
            kill_provider
            if kill_provider
            is not None
            else lambda: False
        ),
    )


def intent(
    *,
    key="runtime-risk-1",
):
    return WebullTradeIntent(
        client_order_id=key,
        strategy_name="MANIPULATION",
        symbol="BBAI",
        side="BUY",
        quantity=5,
        limit_price=20.0,
        created_at=NOW,
    )


def test_runtime_snapshot_builds_authoritative_state():
    client = source()

    result = (
        client.get_snapshot()
    )

    assert result.account_id == (
        "sandbox-account-1"
    )

    assert (
        result.risk_state
        .daily_realized_pnl
        == -7.5
    )

    assert (
        result.risk_state
        .open_position_symbols
        == ("SOUN",)
    )

    assert (
        result.risk_state
        .pending_buy_symbols
        == ("OPEN",)
    )

    assert dict(
        result.risk_state
        .position_exposures
    ) == {
        "SOUN": 100.0,
    }

    assert dict(
        result.risk_state
        .pending_buy_exposures
    ) == {
        "OPEN": 50.0,
    }

    assert (
        result.risk_limits
        .max_daily_loss
        == 25.0
    )

    assert (
        result.risk_limits
        .max_open_positions
        == 2
    )

    assert (
        result.risk_limits
        .max_open_orders
        == 2
    )

    assert (
        result.risk_limits
        .max_position_exposure
        == 225.0
    )


def test_missing_realized_pnl_provider_fails_closed():
    client = (
        WebullRuntimeRiskSnapshotClient(
            snapshot_client=(
                FakeSnapshotClient(
                    snapshot()
                )
            ),
            daily_realized_pnl_provider=None,
            kill_switch_provider=(
                lambda: False
            ),
        )
    )

    with pytest.raises(
        WebullRuntimeRiskError,
        match=(
            "DAILY_REALIZED_PNL_PROVIDER_REQUIRED"
        ),
    ):
        client.get_snapshot()


def test_realized_pnl_provider_failure_fails_closed():
    def broken():
        raise RuntimeError(
            "simulated"
        )

    client = source(
        pnl_provider=broken
    )

    with pytest.raises(
        WebullRuntimeRiskError,
        match=(
            "DAILY_REALIZED_PNL_UNAVAILABLE"
        ),
    ):
        client.get_snapshot()


def test_invalid_realized_pnl_fails_closed():
    client = source(
        pnl_provider=(
            lambda: float("nan")
        )
    )

    with pytest.raises(
        WebullRuntimeRiskError,
        match=(
            "DAILY_REALIZED_PNL_INVALID"
        ),
    ):
        client.get_snapshot()


def test_missing_kill_switch_provider_fails_closed():
    client = (
        WebullRuntimeRiskSnapshotClient(
            snapshot_client=(
                FakeSnapshotClient(
                    snapshot()
                )
            ),
            daily_realized_pnl_provider=(
                lambda: 0.0
            ),
            kill_switch_provider=None,
        )
    )

    with pytest.raises(
        WebullRuntimeRiskError,
        match=(
            "KILL_SWITCH_PROVIDER_REQUIRED"
        ),
    ):
        client.get_snapshot()


def test_invalid_kill_switch_state_fails_closed():
    client = source(
        kill_provider=(
            lambda: "false"
        )
    )

    with pytest.raises(
        WebullRuntimeRiskError,
        match=(
            "KILL_SWITCH_STATE_INVALID"
        ),
    ):
        client.get_snapshot()


def test_stale_account_snapshot_fails_closed():
    client = source(
        snapshot_value=(
            snapshot(
                current=False
            )
        )
    )

    with pytest.raises(
        WebullRuntimeRiskError,
        match=(
            "ACCOUNT_SNAPSHOT_STALE_OR_UNKNOWN"
        ),
    ):
        client.get_snapshot()


def test_position_count_mismatch_fails_closed():
    value = snapshot()

    value.position_count = 2

    client = source(
        snapshot_value=value
    )

    with pytest.raises(
        WebullRuntimeRiskError,
        match="POSITION_COUNT_MISMATCH",
    ):
        client.get_snapshot()


def test_submission_service_refreshes_before_every_order():
    snapshot_client = (
        FakeSnapshotClient(
            snapshot()
        )
    )

    risk_client = (
        WebullRuntimeRiskSnapshotClient(
            snapshot_client=(
                snapshot_client
            ),
            daily_realized_pnl_provider=(
                lambda: 0.0
            ),
            kill_switch_provider=(
                lambda: False
            ),
        )
    )

    manager = (
        FakeExecutionManager()
    )

    service = (
        WebullRiskProtectedSubmissionService(
            risk_snapshot_client=(
                risk_client
            ),
            execution_manager=manager,
        )
    )

    assert service.submit(
        intent=intent(
            key="first"
        )
    ) == "SUBMITTED"

    assert service.submit(
        intent=intent(
            key="second"
        )
    ) == "SUBMITTED"

    assert (
        snapshot_client.calls
        == 2
    )

    assert len(
        manager.calls
    ) == 2


def test_submission_never_reaches_manager_when_risk_source_fails():
    snapshot_client = (
        FakeSnapshotClient(
            snapshot()
        )
    )

    risk_client = (
        WebullRuntimeRiskSnapshotClient(
            snapshot_client=(
                snapshot_client
            ),
            daily_realized_pnl_provider=None,
            kill_switch_provider=(
                lambda: False
            ),
        )
    )

    manager = (
        FakeExecutionManager()
    )

    service = (
        WebullRiskProtectedSubmissionService(
            risk_snapshot_client=(
                risk_client
            ),
            execution_manager=manager,
        )
    )

    with pytest.raises(
        WebullRuntimeRiskError,
        match=(
            "DAILY_REALIZED_PNL_PROVIDER_REQUIRED"
        ),
    ):
        service.submit(
            intent=intent()
        )

    assert (
        manager.calls
        == []
    )
