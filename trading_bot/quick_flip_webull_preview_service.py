from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from .config import (
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

        previews: list[
            dict[str, Any]
        ] = []

        for symbol, signal in invest_results:
            try:
                remaining_allowance = (
                    self._remaining_allowance(
                        working_account
                    )
                )

                request = (
                    build_quick_flip_preview_request(
                        symbol=symbol,
                        signal=signal,
                        max_position_value=(
                            remaining_allowance
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
                })

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
