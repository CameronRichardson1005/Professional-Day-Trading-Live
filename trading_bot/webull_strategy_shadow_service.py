from __future__ import annotations

from typing import Any

from .webull_account_risk import (
    WebullExecutionRiskLimits,
    WebullExecutionRiskState,
)
from .webull_safety import (
    WebullAccountState,
)
from .webull_shadow_execution import (
    WebullShadowExecutionRecord,
)
from .webull_strategy_shadow_router import (
    WebullStrategyShadowRouter,
)


class WebullStrategyShadowServiceError(
    RuntimeError
):
    pass


class WebullStrategyShadowService:
    """
    Fresh-risk orchestration boundary for strategy shadow execution.

    Every evaluation:
    1. obtains a NEW authoritative runtime-risk snapshot;
    2. validates the snapshot;
    3. sends the preview and snapshot to the shadow router.

    This service:
    - has no broker;
    - has no execution manager;
    - has no real execution ledger;
    - has no Webull SDK client;
    - cannot submit, replace, cancel, or close an order.

    The risk snapshot client is dependency injected so the existing
    WebullRuntimeRiskSnapshotClient can be supplied later without
    coupling this shadow-only module to broker mutation code.
    """

    def __init__(
        self,
        *,
        router: WebullStrategyShadowRouter,
        risk_snapshot_client: Any,
    ) -> None:
        manipulation_evaluator = getattr(
            router,
            "evaluate_manipulation_preview",
            None,
        )

        quick_flip_evaluator = getattr(
            router,
            "evaluate_quick_flip_preview",
            None,
        )

        if (
            not callable(
                manipulation_evaluator
            )
            or not callable(
                quick_flip_evaluator
            )
        ):
            raise WebullStrategyShadowServiceError(
                "SHADOW_ROUTER_INVALID"
            )

        get_snapshot = getattr(
            risk_snapshot_client,
            "get_snapshot",
            None,
        )

        if not callable(
            get_snapshot
        ):
            raise WebullStrategyShadowServiceError(
                "SHADOW_RISK_SNAPSHOT_CLIENT_INVALID"
            )

        self.router = router
        self.risk_snapshot_client = (
            risk_snapshot_client
        )

    def _fresh_risk_snapshot(
        self,
    ) -> tuple[
        WebullAccountState,
        WebullExecutionRiskState,
        WebullExecutionRiskLimits,
    ]:
        try:
            snapshot = (
                self.risk_snapshot_client
                .get_snapshot()
            )
        except Exception as error:
            raise WebullStrategyShadowServiceError(
                "SHADOW_RISK_SNAPSHOT_UNAVAILABLE"
            ) from error

        account_id = str(
            getattr(
                snapshot,
                "account_id",
                "",
            )
        ).strip()

        if not account_id:
            raise WebullStrategyShadowServiceError(
                "SHADOW_RISK_ACCOUNT_ID_MISSING"
            )

        account_state = getattr(
            snapshot,
            "account_state",
            None,
        )

        risk_state = getattr(
            snapshot,
            "risk_state",
            None,
        )

        risk_limits = getattr(
            snapshot,
            "risk_limits",
            None,
        )

        if not isinstance(
            account_state,
            WebullAccountState,
        ):
            raise WebullStrategyShadowServiceError(
                "SHADOW_ACCOUNT_STATE_INVALID"
            )

        if not isinstance(
            risk_state,
            WebullExecutionRiskState,
        ):
            raise WebullStrategyShadowServiceError(
                "SHADOW_RISK_STATE_INVALID"
            )

        if not isinstance(
            risk_limits,
            WebullExecutionRiskLimits,
        ):
            raise WebullStrategyShadowServiceError(
                "SHADOW_RISK_LIMITS_INVALID"
            )

        if (
            not account_state.data_is_current
            or not risk_state.data_is_current
        ):
            raise WebullStrategyShadowServiceError(
                "SHADOW_RISK_SNAPSHOT_STALE_OR_UNKNOWN"
            )

        return (
            account_state,
            risk_state,
            risk_limits,
        )

    def evaluate_manipulation_preview(
        self,
        *,
        preview: dict[str, Any],
    ) -> WebullShadowExecutionRecord:
        (
            account_state,
            risk_state,
            risk_limits,
        ) = self._fresh_risk_snapshot()

        return (
            self.router
            .evaluate_manipulation_preview(
                preview=preview,
                account=account_state,
                risk_state=risk_state,
                risk_limits=risk_limits,
            )
        )

    def evaluate_quick_flip_preview(
        self,
        *,
        preview: dict[str, Any],
    ) -> WebullShadowExecutionRecord:
        (
            account_state,
            risk_state,
            risk_limits,
        ) = self._fresh_risk_snapshot()

        return (
            self.router
            .evaluate_quick_flip_preview(
                preview=preview,
                account=account_state,
                risk_state=risk_state,
                risk_limits=risk_limits,
            )
        )
