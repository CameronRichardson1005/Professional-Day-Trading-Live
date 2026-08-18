from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from .capital_allocator import (
    build_equal_weight_capital_plan,
    build_preview_exposure_ceiling,
)
from .capital_reservation_store import (
    DailyCapitalReservationStore,
)
from .live_committed_allocator import (
    build_live_manipulation_allocation_plan,
    rank_committed_allocations,
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

        # Populated only when the committed production allocation
        # policy is requested for a live trading date.
        self.committed_policy_funded = False
        self.committed_policy_decision_reason = None

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
        *,
        preview_exposure_ceiling: float,
        reserved_before_batch: float,
    ) -> float:
        remaining = (
            float(preview_exposure_ceiling)
            - float(reserved_before_batch)
            - account.current_total_exposure
        )

        return round(
            max(
                0.0,
                min(
                    remaining,
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
        *,
        trading_date: str | None = None,
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

        preview_exposure_ceiling = (
            build_preview_exposure_ceiling(
                working_account,
                deployment_fraction=(
                    WEBULL_CAPITAL_DEPLOYMENT_FRACTION
                ),
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
                    preview_exposure_ceiling
                ),
                hard_cap=(
                    preview_exposure_ceiling
                ),
                reserved_recommendation_exposure=(
                    reserved_before_batch
                ),
            )
        )

        live_policy_plan = None
        live_policy_allocations = {}
        live_policy_weights = {}
        live_policy_ranks = {}
        live_policy_scores = {}

        self.committed_policy_funded = False
        self.committed_policy_decision_reason = None

        if trading_date is not None:
            live_policy_plan = (
                build_live_manipulation_allocation_plan(
                    stocks=stocks,
                    trading_date=trading_date,
                    deployable_pool=(
                        allocation_plan.deployable_pool
                    ),
                )
            )

            self.committed_policy_decision_reason = (
                live_policy_plan.decision_reason
            )

            for item in live_policy_plan.allocations:
                live_policy_allocations[
                    item.symbol
                ] = item.recommended_allocation

                live_policy_weights[
                    item.symbol
                ] = item.allocation_weight

            ranked_policy_items = (
                rank_committed_allocations(
                    live_policy_plan
                )
            )

            live_policy_ranks = {
                item.symbol: index
                for index, item
                in enumerate(
                    ranked_policy_items,
                    start=1,
                )
            }

            live_policy_scores = {
                item.symbol: item.score
                for item
                in live_policy_plan.allocations
            }

            self.committed_policy_funded = any(
                item.allocation_weight > 0
                for item
                in live_policy_plan.allocations
            )

        if live_policy_plan is not None:
            fallback_rank = (
                len(
                    live_policy_ranks
                )
                + 1
            )

            invest_stocks.sort(
                key=lambda stock: (
                    live_policy_ranks.get(
                        stock.symbol,
                        fallback_rank,
                    ),
                    stock.symbol,
                )
            )

        preview_safety_ceiling = max(
            0.0,
            preview_exposure_ceiling
            - reserved_before_batch,
        )

        results: list[dict[str, Any]] = []

        for stock in invest_stocks:
            try:
                remaining_allowance = (
                    self._remaining_allowance(
                        working_account,
                        preview_exposure_ceiling=(
                            preview_exposure_ceiling
                        ),
                        reserved_before_batch=(
                            reserved_before_batch
                        ),
                    )
                )

                if live_policy_plan is None:
                    policy_budget = (
                        allocation_plan
                        .per_candidate_budget
                    )
                else:
                    policy_budget = (
                        live_policy_allocations.get(
                            stock.symbol,
                            0.0,
                        )
                    )

                    # The committed policy intentionally gives
                    # non-funded candidates zero preview capital.
                    if policy_budget <= 0:
                        continue

                recommended_allocation = min(
                    remaining_allowance,
                    policy_budget,
                )

                if recommended_allocation <= 0:
                    continue

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
                    operational_cap_override=(
                        preview_safety_ceiling
                    ),
                    hard_cap_override=(
                        preview_safety_ceiling
                    ),
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
                        (
                            live_policy_weights.get(
                                stock.symbol,
                                0.0,
                            )
                            if live_policy_plan
                            is not None
                            else allocation_plan
                            .allocation_weight
                        )
                    ),
                    "recommendedAllocation": (
                        round(
                            recommended_allocation,
                            2,
                        )
                    ),
                    "allocationRank": (
                        live_policy_ranks.get(
                            stock.symbol
                        )
                        if live_policy_plan
                        is not None
                        else None
                    ),
                    "allocationScore": (
                        live_policy_scores.get(
                            stock.symbol
                        )
                        if live_policy_plan
                        is not None
                        else None
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
