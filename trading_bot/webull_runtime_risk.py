from __future__ import annotations

from .webull_execution import (
    WebullTradeIntent,
)
from .webull_execution_manager import (
    WebullSandboxExecutionManager,
)
from .webull_runtime_risk_snapshot import (
    WebullRuntimeRiskError,
    WebullRuntimeRiskSnapshot,
    WebullRuntimeRiskSnapshotClient,
)


__all__ = [
    "WebullRuntimeRiskError",
    "WebullRuntimeRiskSnapshot",
    "WebullRuntimeRiskSnapshotClient",
    "WebullRiskProtectedSubmissionService",
]


class WebullRiskProtectedSubmissionService:
    """
    Future automatic-entry boundary.

    A NEW risk snapshot is required immediately before each
    submission attempt.

    This class remains intentionally separate from the
    read-only runtime-risk snapshot module and is not connected
    to main.py or any automatic runtime builder.
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
