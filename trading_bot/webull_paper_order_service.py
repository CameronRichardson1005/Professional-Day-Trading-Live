from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from typing import Callable

from .webull_account_snapshot import (
    WebullAccountSnapshotClient,
)
from .webull_approval import (
    WebullApprovalError,
    WebullApprovalQueue,
)
from .webull_paper_order_store import (
    WebullPaperOrderRecord,
    WebullPaperOrderStore,
    WebullPaperOrderStoreError,
)
from .webull_preview_store import (
    WebullPreviewStore,
    WebullPreviewStoreError,
)
from .webull_paper_risk import (
    WebullPaperRiskError,
    evaluate_webull_paper_risk,
)
from .webull_safety import WebullOrderProposal


class WebullPaperOrderServiceError(RuntimeError):
    pass


class WebullPaperOrderService:
    """
    Create local simulated paper orders from approved Webull
    preview proposals.

    This service never places, replaces, modifies, or cancels
    broker orders.
    """

    def __init__(
        self,
        *,
        approval_queue: WebullApprovalQueue,
        preview_store: WebullPreviewStore | None = None,
        snapshot_client: (
            WebullAccountSnapshotClient | None
        ) = None,
        paper_order_store: (
            WebullPaperOrderStore | None
        ) = None,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self.approval_queue = approval_queue
        self.preview_store = (
            preview_store or WebullPreviewStore()
        )
        self.snapshot_client = (
            snapshot_client
            or WebullAccountSnapshotClient()
        )
        self.paper_order_store = (
            paper_order_store
            or WebullPaperOrderStore()
        )
        self.clock = clock or (
            lambda: datetime.now(UTC)
        )
        self.id_factory = id_factory or (
            lambda: uuid.uuid4().hex
        )

    @staticmethod
    def _idempotency_key(
        *,
        approval_id: str,
        proposal: WebullOrderProposal,
    ) -> str:
        payload = "|".join([
            approval_id.strip(),
            proposal.symbol.strip().upper(),
            proposal.side.strip().upper(),
            str(proposal.quantity),
            f"{proposal.limit_price:.4f}",
        ])

        return hashlib.sha256(
            payload.encode("utf-8")
        ).hexdigest()

    def submit_paper_order(
        self,
        *,
        symbol: str,
        approval_id: str,
        approval_token: str,
    ) -> WebullPaperOrderRecord:
        normalized_symbol = symbol.strip().upper()

        if not normalized_symbol:
            raise WebullPaperOrderServiceError(
                "PAPER_ORDER_SYMBOL_REQUIRED"
            )

        if not approval_id.strip():
            raise WebullPaperOrderServiceError(
                "APPROVAL_ID_REQUIRED"
            )

        if not approval_token:
            raise WebullPaperOrderServiceError(
                "APPROVAL_TOKEN_REQUIRED"
            )

        try:
            preview = self.preview_store.load_preview(
                normalized_symbol
            )
        except WebullPreviewStoreError as error:
            raise WebullPaperOrderServiceError(
                "PREVIEW_STORE_UNAVAILABLE"
            ) from error

        if preview is None:
            raise WebullPaperOrderServiceError(
                "PREVIEW_NOT_FOUND"
            )

        if preview["status"] != "PREVIEW READY":
            raise WebullPaperOrderServiceError(
                "PREVIEW_NOT_READY"
            )

        proposal = WebullOrderProposal(
            symbol=normalized_symbol,
            side="BUY",
            quantity=int(preview["quantity"]),
            limit_price=float(
                preview["limitPrice"]
            ),
            manually_approved=False,
        )

        if (
            preview.get("targetPrice") is None
            or preview.get("tradingStopPrice") is None
        ):
            raise WebullPaperOrderServiceError(
                "PREVIEW_LIFECYCLE_DATA_MISSING"
            )

        target_price = float(
            preview["targetPrice"]
        )
        stop_price = float(
            preview["tradingStopPrice"]
        )

        stored_exposure = round(
            float(preview["proposedExposure"]),
            2,
        )

        if proposal.proposed_exposure != stored_exposure:
            raise WebullPaperOrderServiceError(
                "PREVIEW_EXPOSURE_MISMATCH"
            )

        idempotency_key = self._idempotency_key(
            approval_id=approval_id,
            proposal=proposal,
        )

        try:
            existing_records = (
                self.paper_order_store.load()
            )
        except WebullPaperOrderStoreError as error:
            raise WebullPaperOrderServiceError(
                "PAPER_ORDER_STORE_UNAVAILABLE"
            ) from error

        if any(
            record.idempotency_key == idempotency_key
            for record in existing_records.values()
        ):
            raise WebullPaperOrderServiceError(
                "DUPLICATE_PAPER_SUBMISSION"
            )

        submitted_at = self.clock()

        if submitted_at.tzinfo is None:
            raise WebullPaperOrderServiceError(
                "CLOCK_MUST_BE_TIMEZONE_AWARE"
            )

        submitted_at = submitted_at.astimezone(UTC)

        try:
            paper_risk = (
                evaluate_webull_paper_risk(
                    records=list(
                        existing_records.values()
                    ),
                    proposed_exposure=(
                        proposal.proposed_exposure
                    ),
                    now=submitted_at,
                )
            )
        except WebullPaperRiskError as error:
            raise WebullPaperOrderServiceError(
                f"PAPER_RISK_CHECK_FAILED:{error}"
            ) from error

        if not paper_risk.allowed:
            raise WebullPaperOrderServiceError(
                paper_risk.reason
            )

        try:
            current_account = (
                self.snapshot_client
                .get_account_state()
            )
        except Exception as error:
            raise WebullPaperOrderServiceError(
                "ACCOUNT_SNAPSHOT_FAILED"
            ) from error

        try:
            safety = (
                self.approval_queue
                .claim_for_paper_submission(
                    approval_id=approval_id,
                    approval_token=approval_token,
                    proposal=proposal,
                    current_account=current_account,
                )
            )
        except WebullApprovalError as error:
            raise WebullPaperOrderServiceError(
                str(error)
            ) from error

        record = WebullPaperOrderRecord(
            paper_order_id=self.id_factory(),
            approval_reference=approval_id,
            idempotency_key=idempotency_key,
            symbol=proposal.symbol,
            side=proposal.side,
            quantity=proposal.quantity,
            limit_price=proposal.limit_price,
            proposed_exposure=(
                proposal.proposed_exposure
            ),
            status="PAPER SUBMITTED",
            created_at=submitted_at,
            submitted_at=submitted_at,
            safety_reason=safety.reason,
            strategy_name=preview.get(
                "strategyName"
            ),
            reward_risk=preview.get(
                "rewardRisk"
            ),
            confirmation_time=preview.get(
                "confirmationTime"
            ),
            retracement_price=preview.get(
                "retracementPrice"
            ),
            impulse_atr_multiple=preview.get(
                "impulseAtrMultiple"
            ),
            pullback_volume_ratio=preview.get(
                "pullbackVolumeRatio"
            ),
            target_price=target_price,
            stop_price=stop_price,
            lifecycle_status="ENTRY PENDING",
        )

        try:
            self.paper_order_store.add(record)
        except WebullPaperOrderStoreError as error:
            durable_record_exists = False

            try:
                persisted_records = (
                    self.paper_order_store.load()
                )

                durable_record_exists = any(
                    persisted.idempotency_key
                    == idempotency_key
                    for persisted
                    in persisted_records.values()
                )
            except WebullPaperOrderStoreError:
                durable_record_exists = False

            if durable_record_exists:
                return record

            try:
                self.approval_queue                     .restore_after_failed_paper_submission(
                        approval_id=approval_id,
                        approval_token=approval_token,
                        proposal=proposal,
                    )
            except WebullApprovalError as rollback_error:
                raise WebullPaperOrderServiceError(
                    "PAPER_ORDER_PERSISTENCE_FAILED_"
                    "AND_APPROVAL_ROLLBACK_FAILED:"
                    f"{rollback_error}"
                ) from error

            raise WebullPaperOrderServiceError(
                "PAPER_ORDER_PERSISTENCE_FAILED:"
                f"{error}"
            ) from error

        return record
