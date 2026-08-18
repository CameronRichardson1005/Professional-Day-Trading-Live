from __future__ import annotations

from typing import Any, Callable

from .webull_account_risk import (
    WebullExecutionRiskLimits,
    WebullExecutionRiskState,
)
from .webull_execution import (
    WebullTradeIntent,
)
from .webull_quick_flip_shadow_intent_adapter import (
    quick_flip_preview_to_trade_intent,
)
from .webull_safety import (
    WebullAccountState,
)
from .webull_shadow_execution import (
    WebullShadowExecutionCoordinator,
    WebullShadowExecutionRecord,
)
from .webull_shadow_intent_adapter import (
    manipulation_preview_to_trade_intent,
)


class WebullStrategyShadowRouterError(
    RuntimeError
):
    pass


class WebullStrategyShadowRouter:
    """
    Central observation-only strategy execution boundary.

    Each strategy uses its own strict preview adapter:

        Manipulation PREVIEW READY
            -> WebullTradeIntent

        Quick Flip PREVIEW READY
            -> WebullTradeIntent

    The normalized intent then passes to the existing
    WebullShadowExecutionCoordinator.

    This router has no broker, no Webull SDK client, no real
    execution ledger, and no broker mutation methods.
    """

    def __init__(
        self,
        *,
        coordinator: (
            WebullShadowExecutionCoordinator
        ),
        manipulation_adapter: (
            Callable[..., WebullTradeIntent]
            | None
        ) = None,
        quick_flip_adapter: (
            Callable[..., WebullTradeIntent]
            | None
        ) = None,
    ) -> None:
        evaluate = getattr(
            coordinator,
            "evaluate",
            None,
        )

        if not callable(
            evaluate
        ):
            raise WebullStrategyShadowRouterError(
                "SHADOW_COORDINATOR_INVALID"
            )

        selected_manipulation_adapter = (
            manipulation_adapter
            if manipulation_adapter is not None
            else manipulation_preview_to_trade_intent
        )

        selected_quick_flip_adapter = (
            quick_flip_adapter
            if quick_flip_adapter is not None
            else quick_flip_preview_to_trade_intent
        )

        if not callable(
            selected_manipulation_adapter
        ):
            raise WebullStrategyShadowRouterError(
                "MANIPULATION_SHADOW_ADAPTER_INVALID"
            )

        if not callable(
            selected_quick_flip_adapter
        ):
            raise WebullStrategyShadowRouterError(
                "QUICK_FLIP_SHADOW_ADAPTER_INVALID"
            )

        self.coordinator = coordinator

        self.manipulation_adapter = (
            selected_manipulation_adapter
        )

        self.quick_flip_adapter = (
            selected_quick_flip_adapter
        )

    @staticmethod
    def _require_intent(
        intent: Any,
        *,
        reason: str,
    ) -> WebullTradeIntent:
        if not isinstance(
            intent,
            WebullTradeIntent,
        ):
            raise WebullStrategyShadowRouterError(
                reason
            )

        return intent

    def _evaluate(
        self,
        *,
        preview: dict[str, Any],
        adapter: Callable[..., WebullTradeIntent],
        invalid_intent_reason: str,
        account: WebullAccountState,
        risk_state: WebullExecutionRiskState,
        risk_limits: WebullExecutionRiskLimits,
    ) -> WebullShadowExecutionRecord:
        intent = adapter(
            preview
        )

        intent = self._require_intent(
            intent,
            reason=(
                invalid_intent_reason
            ),
        )

        result = (
            self.coordinator.evaluate(
                intent=intent,
                account=account,
                risk_state=risk_state,
                risk_limits=risk_limits,
            )
        )

        if not isinstance(
            result,
            WebullShadowExecutionRecord,
        ):
            raise WebullStrategyShadowRouterError(
                "SHADOW_COORDINATOR_RESULT_INVALID"
            )

        return result

    def evaluate_manipulation_preview(
        self,
        *,
        preview: dict[str, Any],
        account: WebullAccountState,
        risk_state: WebullExecutionRiskState,
        risk_limits: WebullExecutionRiskLimits,
    ) -> WebullShadowExecutionRecord:
        return self._evaluate(
            preview=preview,
            adapter=(
                self.manipulation_adapter
            ),
            invalid_intent_reason=(
                "MANIPULATION_SHADOW_INTENT_INVALID"
            ),
            account=account,
            risk_state=risk_state,
            risk_limits=risk_limits,
        )

    def evaluate_quick_flip_preview(
        self,
        *,
        preview: dict[str, Any],
        account: WebullAccountState,
        risk_state: WebullExecutionRiskState,
        risk_limits: WebullExecutionRiskLimits,
    ) -> WebullShadowExecutionRecord:
        return self._evaluate(
            preview=preview,
            adapter=(
                self.quick_flip_adapter
            ),
            invalid_intent_reason=(
                "QUICK_FLIP_SHADOW_INTENT_INVALID"
            ),
            account=account,
            risk_state=risk_state,
            risk_limits=risk_limits,
        )
