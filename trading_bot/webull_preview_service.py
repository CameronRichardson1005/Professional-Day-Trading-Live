from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from .capital_allocator import (
    build_equal_weight_capital_plan,
)
from .capital_reservation_store import (
    DailyCapitalReservationStore,
)
from .config import (
    WEBULL_CAPITAL_DEPLOYMENT_FRACTION,
    WEBULL_MAX_TOTAL_EXPOSURE_DOLLARS,
    WEBULL_OPERATIONAL_EXPOSURE_CAP_DOLLARS,
    WEBULL_PREVIEW_ENABLED,
    WEBULL_REQUIRE_MANUAL_APPROVAL,
)
from .models import Stock
from .webull_account_snapshot import (
    WebullAccountSnapshotClient,
)
from .webull_preview_client import (
    WebullPreviewClient,
)
from .webull_preview_store import (
    WebullPreviewStore,
    WebullPreviewStoreError,
)
from .webull_safety import (
    WebullAccountState,
    WebullOrderProposal,
    WebullSafetyGate,
)


class WebullPreviewService:
    """
    Account-aware Webull preview preparation.

    This service can read account state and create previews.
    It cannot submit, replace, modify, or cancel orders.
    """

    def __init__(
        self,
        client: WebullPreviewClient | None = None,
        snapshot_client: (
            WebullAccountSnapshotClient | None
        ) = None,
        preview_store: WebullPreviewStore | None = None,
    ) -> None:
        self.client = client
        self.snapshot_client = snapshot_client
        self.preview_store = preview_store

    @staticmethod
    def _failure(
        stock: Stock,
        error: str,
        *,
        reason: str = "PREVIEW_FAILED",
    ) -> dict[str, Any]:
        failure = {
            "status": "PREVIEW FAILED",
            "submitted": False,
            "symbol": stock.symbol,
            "safetyAllowed": False,
            "safetyReason": reason,
            "manualApprovalRequired": (
                WEBULL_REQUIRE_MANUAL_APPROVAL
            ),
            "manualApprovalGranted": False,
            "error": error,
        }

        stock.webull_preview = failure
        return failure

    @staticmethod
    def _remaining_allowance(
        account: WebullAccountState,
    ) -> float:
        operational_remaining = (
            WEBULL_OPERATIONAL_EXPOSURE_CAP_DOLLARS
            - account.current_total_exposure
        )

        hard_remaining = (
            WEBULL_MAX_TOTAL_EXPOSURE_DOLLARS
            - account.current_total_exposure
        )

        return round(
            max(
                0.0,
                min(
                    operational_remaining,
                    hard_remaining,
                    account.available_cash,
                ),
            ),
            2,
        )

    def _persist_ready_previews(
        self,
        previews: list[dict[str, Any]],
    ) -> None:
        store = (
            self.preview_store
            or WebullPreviewStore()
        )

        created_at = (
            datetime.now(UTC)
            .isoformat(timespec="seconds")
            .replace("+00:00", "Z")
        )

        records = []

        for preview in previews:
            if preview.get("status") != "PREVIEW READY":
                continue

            records.append({
                "symbol": preview["symbol"],
                "quantity": preview["quantity"],
                "limitPrice": preview["limitBuy"],
                "targetPrice": preview["target"],
                "tradingStopPrice": (
                    preview["tradingStopLoss"]
                ),
                "proposedExposure": (
                    preview["proposedExposure"]
                ),
                "strategyName": (
                    preview.get("strategyName")
                ),
                "rewardRisk": (
                    preview.get("rewardRisk")
                ),
                "confirmationTime": (
                    preview.get("confirmationTime")
                ),
                "retracementPrice": (
                    preview.get("retracementPrice")
                ),
                "impulseAtrMultiple": (
                    preview.get("impulseAtrMultiple")
                ),
                "pullbackVolumeRatio": (
                    preview.get("pullbackVolumeRatio")
                ),
                "status": "PREVIEW READY",
                "createdAt": created_at,
            })

        try:
            store.save_previews(records)
        except WebullPreviewStoreError as error:
            print(
                "Webull preview proposal persistence "
                f"failed: {error}"
            )

    def prepare_previews(
        self,
        stocks: dict[str, Stock],
    ) -> list[dict[str, Any]]:
        if not WEBULL_PREVIEW_ENABLED:
            self._persist_ready_previews([])
            print(
                "Webull preview integration is disabled."
            )
            return []

        invest_stocks = [
            stock
            for stock in stocks.values()
            if stock.signal == "INVEST"
        ]

        for stock in stocks.values():
            stock.webull_preview = None

        if not invest_stocks:
            self._persist_ready_previews([])
            return []

        client = self.client or WebullPreviewClient()

        snapshot_client = (
            self.snapshot_client
            or WebullAccountSnapshotClient()
        )

        try:
            working_account = (
                snapshot_client.get_account_state()
            )
        except Exception as error:
            self._persist_ready_previews([])

            return [
                self._failure(
                    stock,
                    (
                        "Webull account snapshot failed: "
                        f"{error}"
                    ),
                    reason="ACCOUNT_SNAPSHOT_FAILED",
                )
                for stock in invest_stocks
            ]

        capital_store = getattr(
            self,
            "capital_reservation_store",
            None,
        )

        # Default live service instances use the persistent
        # day-level ledger. Dependency-injected test/service
        # instances remain isolated unless a ledger is explicitly
        # supplied by the caller.
        if (
            capital_store is None
            and self.client is None
            and self.snapshot_client is None
        ):
            capital_store = (
                DailyCapitalReservationStore()
            )

        reservation_date = None
        reserved_before_batch = 0.0

        if capital_store is not None:
            reservation_date = (
                capital_store.current_trading_date()
            )
            reserved_before_batch = (
                capital_store
                .total_reserved_exposure(
                    reservation_date
                )
            )

        allocation_plan = (
            build_equal_weight_capital_plan(
                working_account,
                len(invest_stocks),
                deployment_fraction=(
                    WEBULL_CAPITAL_DEPLOYMENT_FRACTION
                ),
                operational_cap=(
                    WEBULL_OPERATIONAL_EXPOSURE_CAP_DOLLARS
                ),
                hard_cap=(
                    WEBULL_MAX_TOTAL_EXPOSURE_DOLLARS
                ),
                reserved_recommendation_exposure=(
                    reserved_before_batch
                ),
            )
        )

        results: list[dict[str, Any]] = []

        for stock in invest_stocks:
            try:
                remaining_allowance = (
                    self._remaining_allowance(
                        working_account
                    )
                )

                recommended_allocation = min(
                    remaining_allowance,
                    allocation_plan.per_candidate_budget,
                )

                request = client.build_request(
                    stock,
                    max_position_value=(
                        recommended_allocation
                    ),
                )

                proposal = WebullOrderProposal(
                    symbol=request.symbol,
                    side="BUY",
                    quantity=request.quantity,
                    limit_price=request.limit_price,
                    manually_approved=False,
                )

                safety = WebullSafetyGate.evaluate(
                    account=working_account,
                    proposal=proposal,
                    require_manual_approval=False,
                )

                if not safety.allowed:
                    results.append(
                        self._failure(
                            stock,
                            (
                                "Webull safety gate rejected "
                                f"the preview: {safety.reason}"
                            ),
                            reason=safety.reason,
                        )
                    )
                    continue

                preview = client.preview(request)

                preview.update({
                    "submitted": False,
                    "safetyAllowed": True,
                    "strategyName": (
                        stock.strategy_name or None
                    ),
                    "rewardRisk": stock.reward_risk,
                    "confirmationTime": (
                        stock.confirmation_time or None
                    ),
                    "retracementPrice": (
                        stock.retracement_price
                    ),
                    "impulseAtrMultiple": (
                        stock.impulse_atr_multiple
                    ),
                    "pullbackVolumeRatio": (
                        stock.pullback_volume_ratio
                    ),
                    "safetyReason": (
                        "PREVIEW_ELIGIBLE"
                    ),
                    "manualApprovalRequired": (
                        WEBULL_REQUIRE_MANUAL_APPROVAL
                    ),
                    "manualApprovalGranted": False,
                    "accountType": (
                        working_account.account_type
                    ),
                    "availableCashBeforePreview": (
                        working_account.available_cash
                    ),
                    "currentExposure": (
                        safety.current_exposure
                    ),
                    "proposedExposure": (
                        safety.proposed_exposure
                    ),
                    "projectedExposure": (
                        safety.projected_exposure
                    ),
                    "operationalExposureCap": (
                        safety.operational_cap
                    ),
                    "hardExposureCap": (
                        safety.hard_cap
                    ),
                    "remainingAllowanceBeforePreview": (
                        remaining_allowance
                    ),
                    "buyingPower": (
                        allocation_plan.buying_power
                    ),
                    "safeCapitalBase": (
                        allocation_plan.safe_capital_base
                    ),
                    "deployableCapitalPool": (
                        allocation_plan.deployable_pool
                    ),
                    "allocationWeight": (
                        allocation_plan.allocation_weight
                    ),
                    "recommendedAllocation": (
                        round(
                            recommended_allocation,
                            2,
                        )
                    ),
                    "capitalAllocationMethod": (
                        allocation_plan.method
                    ),
                    "reservedCapitalBeforeBatch": (
                        allocation_plan
                        .reserved_recommendation_exposure
                    ),
                })

                if capital_store is not None:
                    capital_store.reserve(
                        date_str=reservation_date,
                        reservation_id=(
                            "MANIPULATION:"
                            f"{stock.symbol}"
                        ),
                        strategy=(
                            stock.strategy_name
                            or "MANIPULATION"
                        ),
                        symbol=stock.symbol,
                        exposure=(
                            request
                            .estimated_position_value
                        ),
                    )

                stock.webull_preview = preview
                results.append(preview)

                working_account = replace(
                    working_account,
                    available_cash=round(
                        max(
                            0.0,
                            working_account.available_cash
                            - request.estimated_position_value,
                        ),
                        2,
                    ),
                    open_buy_order_exposure=round(
                        (
                            working_account
                            .open_buy_order_exposure
                            + request
                            .estimated_position_value
                        ),
                        2,
                    ),
                )

            except Exception as error:
                results.append(
                    self._failure(
                        stock,
                        str(error),
                    )
                )

        self._persist_ready_previews(results)

        return results
