from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Callable

from .webull_account_risk import (
    WebullExecutionRiskLimits,
    WebullExecutionRiskState,
    build_execution_risk_state,
    configured_execution_risk_limits,
)
from .webull_execution import (
    WebullTradeIntent,
)
from .webull_execution_manager import (
    WebullSandboxExecutionManager,
)
from .webull_safety import (
    WebullAccountState,
)


class WebullRuntimeRiskError(RuntimeError):
    pass


@dataclass(frozen=True)
class WebullRuntimeRiskSnapshot:
    """
    One pre-submission account/risk snapshot.

    The position and open-order state comes from a fresh
    Webull sandbox account snapshot.

    Daily REALIZED P&L and the kill switch are deliberately
    supplied by explicit providers. They are never guessed from
    paper analytics, unrealized P&L, or current market value.
    """

    account_id: str
    account_state: WebullAccountState
    risk_state: WebullExecutionRiskState
    risk_limits: WebullExecutionRiskLimits

    position_count: int
    open_order_count: int


class WebullRuntimeRiskSnapshotClient:
    """
    Build a new fail-closed execution-risk snapshot on demand.

    Every call re-reads the account through snapshot_client.

    This object does not place, replace, cancel, or close orders.
    """

    def __init__(
        self,
        *,
        snapshot_client: Any,
        daily_realized_pnl_provider: (
            Callable[[], float] | None
        ) = None,
        kill_switch_provider: (
            Callable[[], bool] | None
        ) = None,
    ) -> None:
        self.snapshot_client = (
            snapshot_client
        )

        self.daily_realized_pnl_provider = (
            daily_realized_pnl_provider
        )

        self.kill_switch_provider = (
            kill_switch_provider
        )

    def _daily_realized_pnl(
        self,
    ) -> float:
        provider = (
            self.daily_realized_pnl_provider
        )

        if provider is None:
            raise WebullRuntimeRiskError(
                "DAILY_REALIZED_PNL_PROVIDER_REQUIRED"
            )

        try:
            raw_value = provider()
        except Exception as error:
            raise WebullRuntimeRiskError(
                "DAILY_REALIZED_PNL_UNAVAILABLE"
            ) from error

        if isinstance(
            raw_value,
            bool,
        ):
            raise WebullRuntimeRiskError(
                "DAILY_REALIZED_PNL_INVALID"
            )

        try:
            value = float(
                raw_value
            )
        except (
            TypeError,
            ValueError,
        ) as error:
            raise WebullRuntimeRiskError(
                "DAILY_REALIZED_PNL_INVALID"
            ) from error

        if not math.isfinite(
            value
        ):
            raise WebullRuntimeRiskError(
                "DAILY_REALIZED_PNL_INVALID"
            )

        return round(
            value,
            6,
        )

    def _kill_switch_active(
        self,
    ) -> bool:
        provider = (
            self.kill_switch_provider
        )

        if provider is None:
            raise WebullRuntimeRiskError(
                "KILL_SWITCH_PROVIDER_REQUIRED"
            )

        try:
            value = provider()
        except Exception as error:
            raise WebullRuntimeRiskError(
                "KILL_SWITCH_STATE_UNAVAILABLE"
            ) from error

        if not isinstance(
            value,
            bool,
        ):
            raise WebullRuntimeRiskError(
                "KILL_SWITCH_STATE_INVALID"
            )

        return value

    def get_snapshot(
        self,
    ) -> WebullRuntimeRiskSnapshot:
        try:
            snapshot = (
                self.snapshot_client
                .get_snapshot()
            )
        except Exception as error:
            raise WebullRuntimeRiskError(
                "ACCOUNT_SNAPSHOT_UNAVAILABLE"
            ) from error

        account_id = str(
            getattr(
                snapshot,
                "account_id",
                "",
            )
        ).strip()

        if not account_id:
            raise WebullRuntimeRiskError(
                "ACCOUNT_ID_MISSING"
            )

        account_state = getattr(
            snapshot,
            "account_state",
            None,
        )

        if not isinstance(
            account_state,
            WebullAccountState,
        ):
            raise WebullRuntimeRiskError(
                "ACCOUNT_STATE_INVALID"
            )

        if not (
            account_state
            .data_is_current
        ):
            raise WebullRuntimeRiskError(
                "ACCOUNT_SNAPSHOT_STALE_OR_UNKNOWN"
            )

        try:
            positions = tuple(
                snapshot.positions
            )

            open_orders = tuple(
                snapshot.open_orders
            )
        except Exception as error:
            raise WebullRuntimeRiskError(
                "ACCOUNT_DETAIL_STATE_INVALID"
            ) from error

        try:
            position_count = int(
                snapshot.position_count
            )

            open_order_count = int(
                snapshot.open_order_count
            )
        except (
            TypeError,
            ValueError,
        ) as error:
            raise WebullRuntimeRiskError(
                "ACCOUNT_DETAIL_COUNT_INVALID"
            ) from error

        if (
            position_count
            != len(positions)
        ):
            raise WebullRuntimeRiskError(
                "POSITION_COUNT_MISMATCH"
            )

        if (
            open_order_count
            != len(open_orders)
        ):
            raise WebullRuntimeRiskError(
                "OPEN_ORDER_COUNT_MISMATCH"
            )

        daily_realized_pnl = (
            self._daily_realized_pnl()
        )

        kill_switch_active = (
            self._kill_switch_active()
        )

        risk_state = (
            build_execution_risk_state(
                positions=positions,
                open_orders=open_orders,
                daily_realized_pnl=(
                    daily_realized_pnl
                ),
                kill_switch_active=(
                    kill_switch_active
                ),
                data_is_current=True,
            )
        )

        return WebullRuntimeRiskSnapshot(
            account_id=account_id,
            account_state=account_state,
            risk_state=risk_state,
            risk_limits=(
                configured_execution_risk_limits()
            ),
            position_count=(
                position_count
            ),
            open_order_count=(
                open_order_count
            ),
        )


class WebullRiskProtectedSubmissionService:
    """
    Future automatic-entry boundary.

    A NEW risk snapshot is required immediately before each
    submission attempt.

    This class is intentionally not connected to main.py or any
    automatic runtime builder yet.
    """

    def __init__(
        self,
        *,
        risk_snapshot_client: (
            WebullRuntimeRiskSnapshotClient
        ),
        execution_manager: (
            WebullSandboxExecutionManager
        ),
    ) -> None:
        self.risk_snapshot_client = (
            risk_snapshot_client
        )

        self.execution_manager = (
            execution_manager
        )

    def submit(
        self,
        *,
        intent: WebullTradeIntent,
    ):
        current = (
            self.risk_snapshot_client
            .get_snapshot()
        )

        return (
            self.execution_manager
            .submit_with_account_risk(
                intent=intent,
                account=(
                    current.account_state
                ),
                risk_state=(
                    current.risk_state
                ),
                risk_limits=(
                    current.risk_limits
                ),
            )
        )
