from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import WEBULL_APPROVAL_STORE_FILE


class WebullApprovalStoreError(RuntimeError):
    pass


@dataclass(frozen=True)
class StoredApprovalRecord:
    approval_id: str
    token_hash: str
    proposal_fingerprint: str
    symbol: str
    quantity: int
    limit_price: float
    proposed_exposure: float
    created_at: datetime
    expires_at: datetime
    status: str
    approved_at: datetime | None = None
    consumed_at: datetime | None = None


class WebullApprovalStore:
    """
    Atomic local persistence for Webull approval records.

    Plain approval tokens are never stored.
    """

    def __init__(
        self,
        path: Path | str = WEBULL_APPROVAL_STORE_FILE,
    ) -> None:
        self.path = Path(path)
        self.temp_path = self.path.with_suffix(
            self.path.suffix + ".tmp"
        )

    @staticmethod
    def _format_datetime(
        value: datetime | None,
    ) -> str | None:
        if value is None:
            return None

        if value.tzinfo is None:
            raise WebullApprovalStoreError(
                "Approval timestamps must be timezone-aware."
            )

        return (
            value.astimezone(UTC)
            .isoformat()
            .replace("+00:00", "Z")
        )

    @staticmethod
    def _parse_datetime(
        value: Any,
        *,
        field_name: str,
        required: bool,
    ) -> datetime | None:
        if value in {None, ""}:
            if required:
                raise WebullApprovalStoreError(
                    f"{field_name} is required."
                )

            return None

        if not isinstance(value, str):
            raise WebullApprovalStoreError(
                f"{field_name} must be a string."
            )

        try:
            parsed = datetime.fromisoformat(
                value.replace("Z", "+00:00")
            )
        except ValueError as error:
            raise WebullApprovalStoreError(
                f"{field_name} is invalid."
            ) from error

        if parsed.tzinfo is None:
            raise WebullApprovalStoreError(
                f"{field_name} must include a timezone."
            )

        return parsed.astimezone(UTC)

    @staticmethod
    def _serialize_record(
        record: StoredApprovalRecord,
    ) -> dict[str, Any]:
        payload = asdict(record)

        payload["created_at"] = (
            WebullApprovalStore._format_datetime(
                record.created_at
            )
        )
        payload["expires_at"] = (
            WebullApprovalStore._format_datetime(
                record.expires_at
            )
        )
        payload["approved_at"] = (
            WebullApprovalStore._format_datetime(
                record.approved_at
            )
        )
        payload["consumed_at"] = (
            WebullApprovalStore._format_datetime(
                record.consumed_at
            )
        )

        return payload

    @staticmethod
    def _parse_record(
        payload: Any,
    ) -> StoredApprovalRecord:
        if not isinstance(payload, dict):
            raise WebullApprovalStoreError(
                "Stored approval record must be an object."
            )

        required_strings = (
            "approval_id",
            "token_hash",
            "proposal_fingerprint",
            "symbol",
            "status",
        )

        values: dict[str, str] = {}

        for field_name in required_strings:
            value = payload.get(field_name)

            if not isinstance(value, str) or not value.strip():
                raise WebullApprovalStoreError(
                    f"{field_name} is required."
                )

            values[field_name] = value.strip()

        try:
            quantity = int(payload["quantity"])
            limit_price = float(payload["limit_price"])
            proposed_exposure = float(
                payload["proposed_exposure"]
            )
        except (KeyError, TypeError, ValueError) as error:
            raise WebullApprovalStoreError(
                "Stored approval numeric fields are invalid."
            ) from error

        if quantity <= 0:
            raise WebullApprovalStoreError(
                "Stored approval quantity must be positive."
            )

        if limit_price <= 0:
            raise WebullApprovalStoreError(
                "Stored approval limit price must be positive."
            )

        if proposed_exposure <= 0:
            raise WebullApprovalStoreError(
                "Stored proposed exposure must be positive."
            )

        return StoredApprovalRecord(
            approval_id=values["approval_id"],
            token_hash=values["token_hash"],
            proposal_fingerprint=(
                values["proposal_fingerprint"]
            ),
            symbol=values["symbol"].upper(),
            quantity=quantity,
            limit_price=limit_price,
            proposed_exposure=proposed_exposure,
            created_at=(
                WebullApprovalStore._parse_datetime(
                    payload.get("created_at"),
                    field_name="created_at",
                    required=True,
                )
            ),
            expires_at=(
                WebullApprovalStore._parse_datetime(
                    payload.get("expires_at"),
                    field_name="expires_at",
                    required=True,
                )
            ),
            status=values["status"].upper(),
            approved_at=(
                WebullApprovalStore._parse_datetime(
                    payload.get("approved_at"),
                    field_name="approved_at",
                    required=False,
                )
            ),
            consumed_at=(
                WebullApprovalStore._parse_datetime(
                    payload.get("consumed_at"),
                    field_name="consumed_at",
                    required=False,
                )
            ),
        )

    def load(
        self,
    ) -> dict[str, StoredApprovalRecord]:
        if not self.path.exists():
            return {}

        try:
            payload = json.loads(
                self.path.read_text(
                    encoding="utf-8"
                )
            )
        except (
            OSError,
            json.JSONDecodeError,
        ) as error:
            raise WebullApprovalStoreError(
                "Approval store could not be read."
            ) from error

        if not isinstance(payload, dict):
            raise WebullApprovalStoreError(
                "Approval store root must be an object."
            )

        if payload.get("version") != 1:
            raise WebullApprovalStoreError(
                "Unsupported approval store version."
            )

        records_payload = payload.get("records")

        if not isinstance(records_payload, list):
            raise WebullApprovalStoreError(
                "Approval store records must be a list."
            )

        records: dict[str, StoredApprovalRecord] = {}

        for raw_record in records_payload:
            record = self._parse_record(raw_record)

            if record.approval_id in records:
                raise WebullApprovalStoreError(
                    "Duplicate approval ID in store."
                )

            records[record.approval_id] = record

        return records

    def save(
        self,
        records: dict[str, StoredApprovalRecord],
    ) -> None:
        self.path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        payload = {
            "version": 1,
            "records": [
                self._serialize_record(record)
                for record in sorted(
                    records.values(),
                    key=lambda item: item.created_at,
                )
            ],
        }

        encoded = json.dumps(
            payload,
            indent=2,
            sort_keys=True,
        ) + "\n"

        try:
            self.temp_path.write_text(
                encoded,
                encoding="utf-8",
            )

            os.chmod(
                self.temp_path,
                0o600,
            )

            os.replace(
                self.temp_path,
                self.path,
            )

            os.chmod(
                self.path,
                0o600,
            )

        except OSError as error:
            try:
                self.temp_path.unlink(
                    missing_ok=True
                )
            except OSError:
                pass

            raise WebullApprovalStoreError(
                "Approval store could not be saved."
            ) from error
