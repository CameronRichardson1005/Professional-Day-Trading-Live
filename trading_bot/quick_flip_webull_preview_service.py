from __future__ import annotations

from .capital_allocator import (
    build_equal_weight_capital_plan,
    build_preview_exposure_ceiling,
)
from .capital_reservation_store import (
    DailyCapitalReservationStore,
)
from .live_committed_allocator import (
    build_live_quick_flip_allocation_plan,
)
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from .config import (
    WEBULL_CAPITAL_DEPLOYMENT_FRACTION,
    WEBULL_MAX_TOTAL_EXPOSURE_DOLLARS,
    WEBULL_OPERATIONAL_EXPOSURE_CAP_DOLLARS,
    WEBULL_PREVIEW_ENABLED,
    WEBULL_REQUIRE_MANUAL_APPROVAL,
)
from .quick_flip_webull_preview import (
    QuickFlipWebullPreviewClient,
    build_quick_flip_preview_request,
)
from .webull_account_snapshot import (
    WebullAccountSnapshotClient,
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


class QuickFlipWebullPreviewService:
    """
    Account-aware Webull preview preparation for Quick Flip.

    Quick Flip is:
    - long only;
    - stop-loss free;
    - preview only;
    - subject to the normal Webull account safety gates.

    This service cannot submit, replace, cancel, or modify
    broker orders.
    """

    def __init__(
        self,
        client: QuickFlipWebullPreviewClient | None = None,
        snapshot_client: (
            WebullAccountSnapshotClient | None
        ) = None,
        preview_store: WebullPreviewStore | None = None,
    ) -> None:
        self.client = client
        self.snapshot_client = snapshot_client
        self.preview_store = preview_store

        # Populated for each causal live Quick Flip event.
        self.committed_policy_funded = False
        self.committed_policy_decision_reason = None
        self.committed_policy_considered_symbols = set()

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

    @staticmethod
    def _failure(
        *,
        symbol: str,
        error: str,
        reason: str = "PREVIEW_FAILED",
    ) -> dict[str, Any]:
        return {
            "status": "PREVIEW FAILED",
            "submitted": False,
            "symbol": symbol,
            "strategyName": "QUICK_FLIP",
            "safetyAllowed": False,
            "safetyReason": reason,
            "manualApprovalRequired": (
                WEBULL_REQUIRE_MANUAL_APPROVAL
            ),
            "manualApprovalGranted": False,
            "automaticStopLoss": False,
            "error": error,
        }

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
            if (
                preview.get("status")
                != "PREVIEW READY"
            ):
                continue

            record = {
                "symbol": preview["symbol"],
                "quantity": preview["quantity"],
                "limitPrice": preview["limitBuy"],
                "takeProfit1": (
                    preview["takeProfit1"]
                ),
                "takeProfit2": (
                    preview["takeProfit2"]
                ),
                "proposedExposure": (
                    preview["proposedExposure"]
                ),
                "strategyName": "QUICK_FLIP",
                "status": "PREVIEW READY",
                "createdAt": created_at,
            }

            confirmation_time = preview.get(
                "confirmationTime"
            )

            if confirmation_time:
                record[
                    "confirmationTime"
                ] = str(
                    confirmation_time
                )

            records.append(record)

        try:
            store.save_previews(records)
        except WebullPreviewStoreError as error:
            print(
                "Quick Flip Webull preview "
                "persistence failed: "
                f"{error}"
            )

    def prepare_previews(
        self,
        results: dict[str, Any],
        *,
        trading_date: str | None = None,
    ) -> list[dict[str, Any]]:
        if not WEBULL_PREVIEW_ENABLED:
            self._persist_ready_previews([])

            print(
                "Webull preview integration "
                "is disabled."
            )

            return []

        invest_results = []

        for symbol, result in results.items():
            if result is None:
                continue

            signal = getattr(
                result,
                "signal",
                None,
            )

            if signal is None:
                continue

            if signal.signal != "INVEST":
                continue

            invest_results.append(
                (
                    symbol,
                    signal,
                )
            )

        if not invest_results:
            self._persist_ready_previews([])
            return []

        client = (
            self.client
            or QuickFlipWebullPreviewClient()
        )

        snapshot_client = (
            self.snapshot_client
            or WebullAccountSnapshotClient()
        )

        try:
            working_account = (
                snapshot_client
                .get_account_state()
            )
        except Exception as error:
            self._persist_ready_previews([])

            return [
                self._failure(
                    symbol=symbol,
                    error=(
                        "Webull account snapshot "
                        f"failed: {error}"
                    ),
                    reason=(
                        "ACCOUNT_SNAPSHOT_FAILED"
                    ),
                )
                for symbol, _
                in invest_results
            ]

        capital_store = getattr(
            self,
            "capital_reservation_store",
            None,
        )

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
                len(invest_results),
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

        self.committed_policy_funded = False
        self.committed_policy_decision_reason = None
        self.committed_policy_considered_symbols = set()

        if trading_date is not None:
            live_policy_plan = (
                build_live_quick_flip_allocation_plan(
                    results=results,
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
                self.committed_policy_considered_symbols.add(
                    item.symbol
                )

                live_policy_allocations[
                    item.symbol
                ] = item.recommended_allocation

                live_policy_weights[
                    item.symbol
                ] = item.allocation_weight

            self.committed_policy_funded = any(
                item.allocation_weight > 0
                for item
                in live_policy_plan.allocations
            )

        preview_safety_ceiling = max(
            0.0,
            preview_exposure_ceiling
            - reserved_before_batch,
        )

        previews: list[
            dict[str, Any]
        ] = []

        for symbol, signal in invest_results:
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
                            symbol,
                            0.0,
                        )
                    )

                    if policy_budget <= 0:
                        continue

                recommended_allocation = min(
                    remaining_allowance,
                    policy_budget,
                )

                if recommended_allocation <= 0:
                    continue

                request = (
                    build_quick_flip_preview_request(
                        symbol=symbol,
                        signal=signal,
                        max_position_value=(
                            recommended_allocation
                        ),
                    )
                )

                proposal = WebullOrderProposal(
                    symbol=request.symbol,
                    side="BUY",
                    quantity=request.quantity,
                    limit_price=(
                        request.limit_price
                    ),
                    manually_approved=False,
                )

                # Preview eligibility is checked before the
                # separate manual-approval workflow, matching
                # the existing preview service.
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
                    previews.append(
                        self._failure(
                            symbol=symbol,
                            error=(
                                "Webull safety gate "
                                "rejected the Quick "
                                "Flip preview: "
                                f"{safety.reason}"
                            ),
                            reason=safety.reason,
                        )
                    )

                    continue

                preview = client.preview(
                    request
                )

                confirmation_time = getattr(
                    signal,
                    "confirmation_time",
                    None,
                )

                if (
                    confirmation_time is not None
                    and hasattr(
                        confirmation_time,
                        "isoformat",
                    )
                ):
                    confirmation_time = (
                        confirmation_time
                        .isoformat()
                    )

                preview.update({
                    "submitted": False,
                    "strategyName": (
                        "QUICK_FLIP"
                    ),
                    "automaticStopLoss": False,
                    "safetyAllowed": True,
                    "safetyReason": (
                        "PREVIEW_ELIGIBLE"
                    ),
                    "manualApprovalRequired": (
                        WEBULL_REQUIRE_MANUAL_APPROVAL
                    ),
                    "manualApprovalGranted": False,
                    "confirmationTime": (
                        confirmation_time
                    ),
                    "accountType": (
                        working_account.account_type
                    ),
                    "availableCashBeforePreview": (
                        working_account
                        .available_cash
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
                                symbol,
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
                    "capitalAllocationMethod": (
                        allocation_plan.method
                    ),
                    "reservedCapitalBeforeBatch": (
                        allocation_plan
                        .reserved_recommendation_exposure
                    ),
                })

                if capital_store is not None:
                    reservation_suffix = (
                        confirmation_time
                        if confirmation_time
                        else "SIGNAL"
                    )

                    capital_store.reserve(
                        date_str=reservation_date,
                        reservation_id=(
                            "QUICK_FLIP:"
                            f"{symbol}:"
                            f"{reservation_suffix}"
                        ),
                        strategy="QUICK_FLIP",
                        symbol=symbol,
                        exposure=(
                            request
                            .estimated_position_value
                        ),
                    )

                previews.append(preview)

                # Reserve exposure locally so multiple
                # simultaneous Quick Flip previews share
                # the same account cap.
                working_account = replace(
                    working_account,
                    available_cash=round(
                        max(
                            0.0,
                            working_account
                            .available_cash
                            - request
                            .estimated_position_value,
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
                previews.append(
                    self._failure(
                        symbol=symbol,
                        error=str(error),
                    )
                )

        self._persist_ready_previews(
            previews
        )

        return previews
