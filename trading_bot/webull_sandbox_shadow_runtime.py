from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .config import (
    WEBULL_EXECUTION_MODE,
    WEBULL_SANDBOX_ACCOUNT_ID,
    WEBULL_SANDBOX_APP_KEY,
    WEBULL_SANDBOX_APP_SECRET,
    WEBULL_TRADING_KILL_SWITCH,
)
from .webull_broker_history import (
    WebullStrictBrokerHistoryReader,
)
from .webull_execution import (
    WebullExecutionMode,
    require_safe_execution_mode,
)
from .webull_runtime_risk_snapshot import (
    WebullRuntimeRiskSnapshotClient,
)
from .webull_sandbox_broker import (
    SANDBOX_ENDPOINT,
)
from .webull_sandbox_preflight import (
    WebullSandboxAccountSnapshotClient,
)
from .webull_sdk_safety import (
    build_quiet_trade_client,
)
from .webull_shadow_execution import (
    WebullShadowExecutionCoordinator,
    WebullShadowExecutionJournal,
)
from .webull_strategy_shadow_router import (
    WebullStrategyShadowRouter,
)
from .webull_strategy_shadow_service import (
    WebullStrategyShadowService,
)
from .webull_strict_daily_pnl import (
    WebullStrictDailyRealizedPnlProvider,
)


DEFAULT_SANDBOX_SHADOW_JOURNAL = Path(
    "runtime/webull_shadow_execution.json"
)


class WebullSandboxShadowRuntimeError(
    RuntimeError
):
    pass


@dataclass(frozen=True)
class WebullSandboxShadowRuntime:
    """
    Fully assembled sandbox-only shadow evaluation runtime.

    This runtime is observational only.

    It contains:
    - a sandbox-pinned Webull TradeClient;
    - read-only sandbox account snapshot acquisition;
    - read-only paginated broker history;
    - strict daily realized P&L;
    - fresh runtime risk snapshots;
    - the strategy shadow router and journal.

    It does NOT contain:
    - WebullSandboxBroker;
    - WebullSandboxExecutionManager;
    - WebullExecutionLedger;
    - any automatic order submission service.

    The configured execution kill switch is always passed
    through unchanged.
    """

    account_snapshot_client: (
        WebullSandboxAccountSnapshotClient
    )

    history_reader: (
        WebullStrictBrokerHistoryReader
    )

    daily_realized_pnl_provider: (
        WebullStrictDailyRealizedPnlProvider
    )

    risk_snapshot_client: (
        WebullRuntimeRiskSnapshotClient
    )

    journal: (
        WebullShadowExecutionJournal
    )

    coordinator: (
        WebullShadowExecutionCoordinator
    )

    router: (
        WebullStrategyShadowRouter
    )

    service: (
        WebullStrategyShadowService
    )


def _configured_kill_switch_state(
) -> bool:
    value = WEBULL_TRADING_KILL_SWITCH

    if not isinstance(
        value,
        bool,
    ):
        raise WebullSandboxShadowRuntimeError(
            "SHADOW_KILL_SWITCH_STATE_INVALID"
        )

    return value


def _required_text(
    value,
    *,
    reason: str,
) -> str:
    if not isinstance(
        value,
        str,
    ):
        raise WebullSandboxShadowRuntimeError(
            reason
        )

    cleaned = value.strip()

    if not cleaned:
        raise WebullSandboxShadowRuntimeError(
            reason
        )

    return cleaned


def build_webull_sandbox_shadow_runtime(
    *,
    trading_date_provider: Callable[[], str],
    history_start_date: str,
    journal_path=DEFAULT_SANDBOX_SHADOW_JOURNAL,
    account_id: str | None = None,
    app_key: str | None = None,
    app_secret: str | None = None,
    execution_mode: str = WEBULL_EXECUTION_MODE,
) -> WebullSandboxShadowRuntime:
    """
    Assemble the sandbox-only strategy shadow runtime.

    Important safety properties:

    - execution mode MUST be SANDBOX;
    - credentials are the SANDBOX credential set;
    - Webull client host is always SANDBOX_ENDPOINT;
    - there is no caller-supplied endpoint;
    - there is no caller-supplied kill-switch override;
    - no broker/execution manager/real execution ledger is
      constructed;
    - construction itself performs no Webull HTTP request.
    """

    mode = require_safe_execution_mode(
        execution_mode
    )

    if mode is not WebullExecutionMode.SANDBOX:
        raise WebullSandboxShadowRuntimeError(
            "SHADOW_SANDBOX_MODE_REQUIRED"
        )

    selected_account = _required_text(
        (
            WEBULL_SANDBOX_ACCOUNT_ID
            if account_id is None
            else account_id
        ),
        reason=(
            "SHADOW_SANDBOX_ACCOUNT_ID_REQUIRED"
        ),
    )

    selected_key = _required_text(
        (
            WEBULL_SANDBOX_APP_KEY
            if app_key is None
            else app_key
        ),
        reason=(
            "SHADOW_SANDBOX_APP_KEY_REQUIRED"
        ),
    )

    selected_secret = _required_text(
        (
            WEBULL_SANDBOX_APP_SECRET
            if app_secret is None
            else app_secret
        ),
        reason=(
            "SHADOW_SANDBOX_APP_SECRET_REQUIRED"
        ),
    )

    if not callable(
        trading_date_provider
    ):
        raise WebullSandboxShadowRuntimeError(
            "SHADOW_TRADING_DATE_PROVIDER_INVALID"
        )

    # This is the ONLY SDK client constructed by this factory.
    # The endpoint is intentionally not caller-configurable.
    trade_client = (
        build_quiet_trade_client(
            app_key=selected_key,
            app_secret=selected_secret,
            endpoint=SANDBOX_ENDPOINT,
        )
    )

    account_snapshot_client = (
        WebullSandboxAccountSnapshotClient(
            trade_client=trade_client,
            account_id=selected_account,
            execution_mode=(
                WebullExecutionMode.SANDBOX.value
            ),
        )
    )

    history_reader = (
        WebullStrictBrokerHistoryReader(
            trade_client=trade_client,
            account_id=selected_account,
        )
    )

    daily_realized_pnl_provider = (
        WebullStrictDailyRealizedPnlProvider(
            history_reader=history_reader,
            trading_date_provider=(
                trading_date_provider
            ),
            history_start_date=(
                history_start_date
            ),
        )
    )

    risk_snapshot_client = (
        WebullRuntimeRiskSnapshotClient(
            snapshot_client=(
                account_snapshot_client
            ),
            daily_realized_pnl_provider=(
                daily_realized_pnl_provider
            ),
            kill_switch_provider=(
                _configured_kill_switch_state
            ),
        )
    )

    journal = (
        WebullShadowExecutionJournal(
            journal_path
        )
    )

    coordinator = (
        WebullShadowExecutionCoordinator(
            journal=journal
        )
    )

    router = (
        WebullStrategyShadowRouter(
            coordinator=coordinator
        )
    )

    service = (
        WebullStrategyShadowService(
            router=router,
            risk_snapshot_client=(
                risk_snapshot_client
            ),
        )
    )

    return WebullSandboxShadowRuntime(
        account_snapshot_client=(
            account_snapshot_client
        ),
        history_reader=history_reader,
        daily_realized_pnl_provider=(
            daily_realized_pnl_provider
        ),
        risk_snapshot_client=(
            risk_snapshot_client
        ),
        journal=journal,
        coordinator=coordinator,
        router=router,
        service=service,
    )
