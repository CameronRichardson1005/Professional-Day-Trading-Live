from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Callable

from .config import (
    WEBULL_APPROVAL_TTL_SECONDS,
    WEBULL_ORDER_SUBMISSION_ENABLED,
    WEBULL_TRADING_KILL_SWITCH,
)
from .webull_approval_store import (
    StoredApprovalRecord,
    WebullApprovalStore,
)
from .webull_safety import (
    WebullAccountState,
    WebullOrderProposal,
    WebullSafetyDecision,
    WebullSafetyGate,
)


class WebullApprovalError(RuntimeError):
    pass


@dataclass(frozen=True)
class WebullApprovalTicket:
    approval_id: str
    approval_token: str
    symbol: str
    quantity: int
    limit_price: float
    proposed_exposure: float
    created_at: datetime
    expires_at: datetime
    status: str = "PENDING"


@dataclass
class _ApprovalRecord:
    approval_id: str
    token_hash: str
    proposal_fingerprint: str
    symbol: str
    quantity: int
    limit_price: float
    proposed_exposure: float
    created_at: datetime
    expires_at: datetime
    status: str = "PENDING"
    approved_at: datetime | None = None
    consumed_at: datetime | None = None


class WebullApprovalQueue:
    """
    One-time manual approval workflow.

    This class does not call Webull and cannot place, replace,
    modify, or cancel broker orders.
    """

    def __init__(
        self,
        *,
        clock: Callable[[], datetime] | None = None,
        ttl_seconds: int = WEBULL_APPROVAL_TTL_SECONDS,
        store: WebullApprovalStore | None = None,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError(
                "Approval TTL must be positive."
            )

        self._clock = clock or (
            lambda: datetime.now(UTC)
        )
        self._ttl_seconds = ttl_seconds
        self._store = store
        self._records: dict[str, _ApprovalRecord] = {}

        if self._store is not None:
            stored_records = self._store.load()

            self._records = {
                approval_id: self._from_stored(record)
                for approval_id, record
                in stored_records.items()
            }

            self._expire_loaded_records()

    @staticmethod
    def _from_stored(
        record: StoredApprovalRecord,
    ) -> _ApprovalRecord:
        return _ApprovalRecord(
            approval_id=record.approval_id,
            token_hash=record.token_hash,
            proposal_fingerprint=(
                record.proposal_fingerprint
            ),
            symbol=record.symbol,
            quantity=record.quantity,
            limit_price=record.limit_price,
            proposed_exposure=(
                record.proposed_exposure
            ),
            created_at=record.created_at,
            expires_at=record.expires_at,
            status=record.status,
            approved_at=record.approved_at,
            consumed_at=record.consumed_at,
        )

    @staticmethod
    def _to_stored(
        record: _ApprovalRecord,
    ) -> StoredApprovalRecord:
        return StoredApprovalRecord(
            approval_id=record.approval_id,
            token_hash=record.token_hash,
            proposal_fingerprint=(
                record.proposal_fingerprint
            ),
            symbol=record.symbol,
            quantity=record.quantity,
            limit_price=record.limit_price,
            proposed_exposure=(
                record.proposed_exposure
            ),
            created_at=record.created_at,
            expires_at=record.expires_at,
            status=record.status,
            approved_at=record.approved_at,
            consumed_at=record.consumed_at,
        )

    def _persist(self) -> None:
        if self._store is None:
            return

        self._store.save({
            approval_id: self._to_stored(record)
            for approval_id, record
            in self._records.items()
        })

    def _expire_loaded_records(self) -> None:
        now = self._clock()
        changed = False

        for record in self._records.values():
            if (
                record.status in {"PENDING", "APPROVED"}
                and now >= record.expires_at
            ):
                record.status = "EXPIRED"
                changed = True

        if changed:
            self._persist()

    @staticmethod
    def _token_hash(token: str) -> str:
        return hashlib.sha256(
            token.encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _proposal_fingerprint(
        proposal: WebullOrderProposal,
    ) -> str:
        payload = "|".join([
            proposal.symbol.strip().upper(),
            proposal.side.strip().upper(),
            str(proposal.quantity),
            f"{proposal.limit_price:.4f}",
        ])

        return hashlib.sha256(
            payload.encode("utf-8")
        ).hexdigest()

    def _get_record(
        self,
        approval_id: str,
    ) -> _ApprovalRecord:
        record = self._records.get(approval_id)

        if record is None:
            raise WebullApprovalError(
                "APPROVAL_NOT_FOUND"
            )

        return record

    def _verify_token(
        self,
        record: _ApprovalRecord,
        token: str,
    ) -> None:
        supplied_hash = self._token_hash(token)

        if not hmac.compare_digest(
            record.token_hash,
            supplied_hash,
        ):
            raise WebullApprovalError(
                "INVALID_APPROVAL_TOKEN"
            )

    def _reject_if_expired(
        self,
        record: _ApprovalRecord,
    ) -> None:
        if self._clock() >= record.expires_at:
            record.status = "EXPIRED"

            raise WebullApprovalError(
                "APPROVAL_EXPIRED"
            )

    def has_active_duplicate(
        self,
        proposal: WebullOrderProposal,
    ) -> bool:
        """
        Return True when the same proposal already has a
        PENDING or APPROVED ticket.
        """
        self._expire_loaded_records()

        fingerprint = self._proposal_fingerprint(
            proposal
        )

        return any(
            record.status in {"PENDING", "APPROVED"}
            and hmac.compare_digest(
                record.proposal_fingerprint,
                fingerprint,
            )
            for record in self._records.values()
        )

    def create(
        self,
        *,
        proposal: WebullOrderProposal,
        account: WebullAccountState,
    ) -> WebullApprovalTicket:
        preview_decision = WebullSafetyGate.evaluate(
            account=account,
            proposal=proposal,
            require_manual_approval=False,
        )

        if not preview_decision.allowed:
            raise WebullApprovalError(
                "APPROVAL_REQUEST_REJECTED:"
                f"{preview_decision.reason}"
            )

        now = self._clock()
        expires_at = now + timedelta(
            seconds=self._ttl_seconds
        )

        approval_id = uuid.uuid4().hex
        approval_token = secrets.token_urlsafe(32)

        record = _ApprovalRecord(
            approval_id=approval_id,
            token_hash=self._token_hash(
                approval_token
            ),
            proposal_fingerprint=(
                self._proposal_fingerprint(proposal)
            ),
            symbol=proposal.symbol.strip().upper(),
            quantity=proposal.quantity,
            limit_price=round(
                proposal.limit_price,
                4,
            ),
            proposed_exposure=(
                proposal.proposed_exposure
            ),
            created_at=now,
            expires_at=expires_at,
        )

        self._records[approval_id] = record
        self._persist()

        return WebullApprovalTicket(
            approval_id=approval_id,
            approval_token=approval_token,
            symbol=record.symbol,
            quantity=record.quantity,
            limit_price=record.limit_price,
            proposed_exposure=record.proposed_exposure,
            created_at=record.created_at,
            expires_at=record.expires_at,
        )

    def approve(
        self,
        *,
        approval_id: str,
        approval_token: str,
    ) -> None:
        record = self._get_record(approval_id)
        self._verify_token(
            record,
            approval_token,
        )
        self._reject_if_expired(record)

        if record.status == "CONSUMED":
            raise WebullApprovalError(
                "APPROVAL_ALREADY_CONSUMED"
            )

        if record.status == "APPROVED":
            raise WebullApprovalError(
                "APPROVAL_ALREADY_APPROVED"
            )

        if record.status != "PENDING":
            raise WebullApprovalError(
                f"APPROVAL_NOT_PENDING:{record.status}"
            )

        record.status = "APPROVED"
        record.approved_at = self._clock()
        self._persist()

    def claim_for_submission(
        self,
        *,
        approval_id: str,
        approval_token: str,
        proposal: WebullOrderProposal,
        current_account: WebullAccountState,
    ) -> WebullSafetyDecision:
        record = self._get_record(approval_id)
        self._verify_token(
            record,
            approval_token,
        )
        self._reject_if_expired(record)

        if record.status == "CONSUMED":
            raise WebullApprovalError(
                "APPROVAL_ALREADY_CONSUMED"
            )

        if record.status != "APPROVED":
            raise WebullApprovalError(
                "APPROVAL_NOT_APPROVED"
            )

        current_fingerprint = (
            self._proposal_fingerprint(proposal)
        )

        if not hmac.compare_digest(
            record.proposal_fingerprint,
            current_fingerprint,
        ):
            raise WebullApprovalError(
                "ORDER_CHANGED_AFTER_APPROVAL"
            )

        if WEBULL_TRADING_KILL_SWITCH:
            raise WebullApprovalError(
                "TRADING_KILL_SWITCH_ACTIVE"
            )

        if not WEBULL_ORDER_SUBMISSION_ENABLED:
            raise WebullApprovalError(
                "REAL_ORDER_SUBMISSION_DISABLED"
            )

        approved_proposal = WebullOrderProposal(
            symbol=proposal.symbol,
            side=proposal.side,
            quantity=proposal.quantity,
            limit_price=proposal.limit_price,
            manually_approved=True,
        )

        final_decision = WebullSafetyGate.evaluate(
            account=current_account,
            proposal=approved_proposal,
        )

        if not final_decision.allowed:
            raise WebullApprovalError(
                "FINAL_SAFETY_RECHECK_FAILED:"
                f"{final_decision.reason}"
            )

        record.status = "CONSUMED"
        record.consumed_at = self._clock()
        self._persist()

        return final_decision

    def claim_for_paper_submission(
        self,
        *,
        approval_id: str,
        approval_token: str,
        proposal: WebullOrderProposal,
        current_account: WebullAccountState,
    ) -> WebullSafetyDecision:
        """
        Consume an approved ticket for a local simulated
        paper order.

        This method performs no broker action and does not alter
        the real-order submission kill switch or enablement flag.
        """
        record = self._get_record(approval_id)
        self._verify_token(
            record,
            approval_token,
        )
        self._reject_if_expired(record)

        if record.status == "CONSUMED":
            raise WebullApprovalError(
                "APPROVAL_ALREADY_CONSUMED"
            )

        if record.status != "APPROVED":
            raise WebullApprovalError(
                "APPROVAL_NOT_APPROVED"
            )

        current_fingerprint = (
            self._proposal_fingerprint(proposal)
        )

        if not hmac.compare_digest(
            record.proposal_fingerprint,
            current_fingerprint,
        ):
            raise WebullApprovalError(
                "ORDER_CHANGED_AFTER_APPROVAL"
            )

        approved_proposal = WebullOrderProposal(
            symbol=proposal.symbol,
            side=proposal.side,
            quantity=proposal.quantity,
            limit_price=proposal.limit_price,
            manually_approved=True,
        )

        final_decision = WebullSafetyGate.evaluate(
            account=current_account,
            proposal=approved_proposal,
        )

        if not final_decision.allowed:
            raise WebullApprovalError(
                "FINAL_SAFETY_RECHECK_FAILED:"
                f"{final_decision.reason}"
            )

        record.status = "CONSUMED"
        record.consumed_at = self._clock()
        self._persist()

        return final_decision

    def restore_after_failed_paper_submission(
        self,
        *,
        approval_id: str,
        approval_token: str,
        proposal: WebullOrderProposal,
    ) -> None:
        """
        Restore a just-consumed paper approval when durable local
        paper-order persistence failed.

        This method performs no broker action. It may only restore
        a CONSUMED approval whose exact proposal and token still
        match.
        """
        record = self._get_record(approval_id)
        self._verify_token(
            record,
            approval_token,
        )

        if record.status != "CONSUMED":
            raise WebullApprovalError(
                "APPROVAL_NOT_CONSUMED"
            )

        current_fingerprint = (
            self._proposal_fingerprint(proposal)
        )

        if not hmac.compare_digest(
            record.proposal_fingerprint,
            current_fingerprint,
        ):
            raise WebullApprovalError(
                "ORDER_CHANGED_AFTER_APPROVAL"
            )

        record.status = "APPROVED"
        record.consumed_at = None
        self._persist()

    @staticmethod
    def _public_datetime(
        value: datetime | None,
    ) -> str | None:
        if value is None:
            return None

        return (
            value.astimezone(UTC)
            .isoformat(timespec="seconds")
            .replace("+00:00", "Z")
        )

    def list_public_records(
        self,
    ) -> list[dict[str, object]]:
        """
        Return dashboard-safe approval summaries.

        Tokens, token hashes, proposal fingerprints, account
        identifiers, and broker credentials are never included.
        """
        self._expire_loaded_records()

        records = sorted(
            self._records.values(),
            key=lambda record: record.created_at,
            reverse=True,
        )

        result: list[dict[str, object]] = []

        for record in records:
            payload: dict[str, object] = {
                "symbol": record.symbol,
                "quantity": record.quantity,
                "limitPrice": record.limit_price,
                "proposedExposure": (
                    record.proposed_exposure
                ),
                "status": record.status,
                "createdAt": self._public_datetime(
                    record.created_at
                ),
                "expiresAt": self._public_datetime(
                    record.expires_at
                ),
            }

            approved_at = self._public_datetime(
                record.approved_at
            )
            consumed_at = self._public_datetime(
                record.consumed_at
            )

            if approved_at is not None:
                payload["approvedAt"] = approved_at

            if consumed_at is not None:
                payload["consumedAt"] = consumed_at

            result.append(payload)

        return result

    def status(
        self,
        approval_id: str,
    ) -> str:
        record = self._get_record(approval_id)

        if (
            record.status in {"PENDING", "APPROVED"}
            and self._clock() >= record.expires_at
        ):
            record.status = "EXPIRED"
            self._persist()

        return record.status
