from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class WebullPaperOrderStoreError(RuntimeError):
    pass


@dataclass(frozen=True)
class WebullPaperOrderRecord:
    paper_order_id: str
    approval_reference: str
    idempotency_key: str
    symbol: str
    side: str
    quantity: int
    limit_price: float
    proposed_exposure: float
    status: str
    created_at: datetime
    submitted_at: datetime
    safety_reason: str

    # Optional strategy snapshot captured when the LOCAL PAPER
    # order was created. Legacy records may not contain these.
    strategy_name: str | None = None
    reward_risk: float | None = None
    confirmation_time: str | None = None
    retracement_price: float | None = None
    impulse_atr_multiple: float | None = None
    pullback_volume_ratio: float | None = None

    # Strategy prices required for local lifecycle tracking.
    target_price: float | None = None
    stop_price: float | None = None

    # Local-paper lifecycle state only.
    lifecycle_status: str = "ENTRY PENDING"

    filled_at: datetime | None = None
    fill_price: float | None = None

    highest_price: float | None = None
    lowest_price: float | None = None
    mfe_pct: float | None = None
    mae_pct: float | None = None

    closed_at: datetime | None = None
    exit_price: float | None = None
    exit_reason: str = ""
    realized_pnl: float | None = None
    return_pct: float | None = None


class WebullPaperOrderStore:
    """
    Durable local storage for simulated Webull paper orders.

    This store contains no approval tokens, token hashes,
    credentials, account IDs, or raw broker responses.

    Lifecycle fields describe LOCAL PAPER simulation only.
    """

    def __init__(
        self,
        path: Path | str = (
            "runtime/webull_paper_orders.json"
        ),
    ) -> None:
        self.path = Path(path)
        self.temp_path = self.path.with_suffix(
            self.path.suffix + ".tmp"
        )

    @staticmethod
    def _format_datetime(value: datetime) -> str:
        if value.tzinfo is None:
            raise WebullPaperOrderStoreError(
                "Paper-order timestamps must be "
                "timezone-aware."
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
    ) -> datetime:
        if not isinstance(value, str) or not value.strip():
            raise WebullPaperOrderStoreError(
                f"{field_name} is required."
            )

        try:
            parsed = datetime.fromisoformat(
                value.replace("Z", "+00:00")
            )
        except ValueError as error:
            raise WebullPaperOrderStoreError(
                f"{field_name} is invalid."
            ) from error

        if parsed.tzinfo is None:
            raise WebullPaperOrderStoreError(
                f"{field_name} must include a timezone."
            )

        return parsed.astimezone(UTC)

    @staticmethod
    def _parse_optional_datetime(
        value: Any,
        *,
        field_name: str,
    ) -> datetime | None:
        if value is None:
            return None

        return WebullPaperOrderStore._parse_datetime(
            value,
            field_name=field_name,
        )

    @staticmethod
    def _validate_record(
        record: WebullPaperOrderRecord,
    ) -> WebullPaperOrderRecord:
        paper_order_id = record.paper_order_id.strip()
        approval_reference = (
            record.approval_reference.strip()
        )
        idempotency_key = record.idempotency_key.strip()
        symbol = record.symbol.strip().upper()
        side = record.side.strip().upper()
        status = record.status.strip().upper()
        safety_reason = record.safety_reason.strip()
        lifecycle_status = (
            record.lifecycle_status.strip().upper()
        )
        exit_reason = record.exit_reason.strip().upper()

        strategy_name = (
            None
            if record.strategy_name is None
            else record.strategy_name.strip()
        )
        confirmation_time = (
            None
            if record.confirmation_time is None
            else record.confirmation_time.strip()
        )

        if (
            record.strategy_name is not None
            and not strategy_name
        ):
            raise WebullPaperOrderStoreError(
                "strategy_name cannot be empty."
            )

        if (
            record.confirmation_time is not None
            and not confirmation_time
        ):
            raise WebullPaperOrderStoreError(
                "confirmation_time cannot be empty."
            )

        strategy_numbers = {}

        for field_name, raw_value in {
            "reward_risk": record.reward_risk,
            "retracement_price": record.retracement_price,
            "impulse_atr_multiple": record.impulse_atr_multiple,
            "pullback_volume_ratio": record.pullback_volume_ratio,
        }.items():
            if raw_value is None:
                strategy_numbers[field_name] = None
                continue

            value = float(raw_value)

            if not (
                float("-inf") < value < float("inf")
            ):
                raise WebullPaperOrderStoreError(
                    f"{field_name} must be finite."
                )

            strategy_numbers[field_name] = value

        if (
            strategy_numbers["reward_risk"] is not None
            and strategy_numbers["reward_risk"] <= 0
        ):
            raise WebullPaperOrderStoreError(
                "reward_risk must be positive."
            )

        if (
            strategy_numbers["retracement_price"] is not None
            and strategy_numbers["retracement_price"] <= 0
        ):
            raise WebullPaperOrderStoreError(
                "retracement_price must be positive."
            )

        if (
            strategy_numbers["impulse_atr_multiple"] is not None
            and strategy_numbers["impulse_atr_multiple"] < 0
        ):
            raise WebullPaperOrderStoreError(
                "impulse_atr_multiple cannot be negative."
            )

        if (
            strategy_numbers["pullback_volume_ratio"] is not None
            and strategy_numbers["pullback_volume_ratio"] < 0
        ):
            raise WebullPaperOrderStoreError(
                "pullback_volume_ratio cannot be negative."
            )

        if not paper_order_id:
            raise WebullPaperOrderStoreError(
                "paper_order_id is required."
            )

        if not approval_reference:
            raise WebullPaperOrderStoreError(
                "approval_reference is required."
            )

        if not idempotency_key:
            raise WebullPaperOrderStoreError(
                "idempotency_key is required."
            )

        if not symbol:
            raise WebullPaperOrderStoreError(
                "symbol is required."
            )

        if side != "BUY":
            raise WebullPaperOrderStoreError(
                "Only BUY paper orders are supported."
            )

        if record.quantity <= 0:
            raise WebullPaperOrderStoreError(
                "Paper-order quantity must be positive."
            )

        if record.limit_price <= 0:
            raise WebullPaperOrderStoreError(
                "Paper-order limit price must be positive."
            )

        limit_price = round(
            float(record.limit_price),
            4,
        )

        expected_exposure = round(
            record.quantity * limit_price,
            2,
        )

        if (
            round(record.proposed_exposure, 2)
            != expected_exposure
        ):
            raise WebullPaperOrderStoreError(
                "Paper-order exposure does not match "
                "quantity multiplied by limit price."
            )

        if status != "PAPER SUBMITTED":
            raise WebullPaperOrderStoreError(
                "Paper-order status must be PAPER SUBMITTED."
            )

        if not safety_reason:
            raise WebullPaperOrderStoreError(
                "safety_reason is required."
            )

        if lifecycle_status not in {
            "ENTRY PENDING",
            "OPEN",
            "CLOSED",
        }:
            raise WebullPaperOrderStoreError(
                "Unsupported paper-order lifecycle status."
            )

        target_price = None
        stop_price = None

        if (
            (record.target_price is None)
            != (record.stop_price is None)
        ):
            raise WebullPaperOrderStoreError(
                "Paper-order target and stop must either "
                "both be present or both be absent."
            )

        if record.target_price is not None:
            target_price = round(
                float(record.target_price),
                4,
            )
            stop_price = round(
                float(record.stop_price),
                4,
            )

            if target_price <= limit_price:
                raise WebullPaperOrderStoreError(
                    "Paper-order target must be above "
                    "the BUY limit price."
                )

            if stop_price <= 0:
                raise WebullPaperOrderStoreError(
                    "Paper-order stop must be positive."
                )

            if stop_price >= limit_price:
                raise WebullPaperOrderStoreError(
                    "Paper-order stop must be below "
                    "the BUY limit price."
                )

        WebullPaperOrderStore._format_datetime(
            record.created_at
        )
        WebullPaperOrderStore._format_datetime(
            record.submitted_at
        )

        created_at = record.created_at.astimezone(UTC)
        submitted_at = record.submitted_at.astimezone(UTC)

        if submitted_at < created_at:
            raise WebullPaperOrderStoreError(
                "submitted_at cannot precede created_at."
            )

        filled_at = (
            None
            if record.filled_at is None
            else record.filled_at.astimezone(UTC)
        )

        closed_at = (
            None
            if record.closed_at is None
            else record.closed_at.astimezone(UTC)
        )

        if filled_at is not None:
            WebullPaperOrderStore._format_datetime(
                filled_at
            )

            if filled_at < submitted_at:
                raise WebullPaperOrderStoreError(
                    "filled_at cannot precede submitted_at."
                )

        if closed_at is not None:
            WebullPaperOrderStore._format_datetime(
                closed_at
            )

            if (
                filled_at is not None
                and closed_at < filled_at
            ):
                raise WebullPaperOrderStoreError(
                    "closed_at cannot precede filled_at."
                )

        lifecycle_values = (
            record.fill_price,
            record.highest_price,
            record.lowest_price,
            record.mfe_pct,
            record.mae_pct,
        )

        close_values = (
            record.exit_price,
            record.realized_pnl,
            record.return_pct,
        )

        if lifecycle_status == "ENTRY PENDING":
            if any(
                value is not None
                for value in lifecycle_values
            ):
                raise WebullPaperOrderStoreError(
                    "ENTRY PENDING order cannot contain "
                    "fill or excursion data."
                )

            if filled_at is not None:
                raise WebullPaperOrderStoreError(
                    "ENTRY PENDING order cannot have filled_at."
                )

            if (
                closed_at is not None
                or any(
                    value is not None
                    for value in close_values
                )
                or exit_reason
            ):
                raise WebullPaperOrderStoreError(
                    "ENTRY PENDING order cannot contain "
                    "close data."
                )

            fill_price = None
            highest_price = None
            lowest_price = None
            mfe_pct = None
            mae_pct = None
            exit_price = None
            realized_pnl = None
            return_pct = None

        elif (
            lifecycle_status == "CLOSED"
            and filled_at is None
        ):
            if closed_at is None:
                raise WebullPaperOrderStoreError(
                    "NO ENTRY paper order requires "
                    "closed_at."
                )

            if exit_reason != "NO ENTRY":
                raise WebullPaperOrderStoreError(
                    "Unfilled CLOSED paper order must use "
                    "NO ENTRY exit reason."
                )

            if any(
                value is not None
                for value in lifecycle_values
            ):
                raise WebullPaperOrderStoreError(
                    "NO ENTRY paper order cannot contain "
                    "fill or excursion data."
                )

            if any(
                value is not None
                for value in close_values
            ):
                raise WebullPaperOrderStoreError(
                    "NO ENTRY paper order cannot contain "
                    "exit price or return data."
                )

            fill_price = None
            highest_price = None
            lowest_price = None
            mfe_pct = None
            mae_pct = None
            exit_price = None
            realized_pnl = None
            return_pct = None

        else:
            if target_price is None or stop_price is None:
                raise WebullPaperOrderStoreError(
                    "Lifecycle-managed paper order requires "
                    "target and stop prices."
                )

            if filled_at is None:
                raise WebullPaperOrderStoreError(
                    "OPEN or filled CLOSED paper order "
                    "requires filled_at."
                )

            if record.fill_price is None:
                raise WebullPaperOrderStoreError(
                    "OPEN or CLOSED paper order requires "
                    "fill_price."
                )

            fill_price = round(
                float(record.fill_price),
                4,
            )

            if fill_price <= 0:
                raise WebullPaperOrderStoreError(
                    "fill_price must be positive."
                )

            if record.highest_price is None:
                raise WebullPaperOrderStoreError(
                    "Lifecycle-managed order requires "
                    "highest_price."
                )

            if record.lowest_price is None:
                raise WebullPaperOrderStoreError(
                    "Lifecycle-managed order requires "
                    "lowest_price."
                )

            highest_price = round(
                float(record.highest_price),
                4,
            )
            lowest_price = round(
                float(record.lowest_price),
                4,
            )

            if highest_price < fill_price:
                raise WebullPaperOrderStoreError(
                    "highest_price cannot be below "
                    "fill_price."
                )

            if lowest_price > fill_price:
                raise WebullPaperOrderStoreError(
                    "lowest_price cannot be above "
                    "fill_price."
                )

            mfe_pct = round(
                (
                    highest_price - fill_price
                )
                / fill_price
                * 100.0,
                6,
            )

            mae_pct = round(
                (
                    lowest_price - fill_price
                )
                / fill_price
                * 100.0,
                6,
            )

            if lifecycle_status == "OPEN":
                if (
                    closed_at is not None
                    or any(
                        value is not None
                        for value in close_values
                    )
                    or exit_reason
                ):
                    raise WebullPaperOrderStoreError(
                        "OPEN paper order cannot contain "
                        "close data."
                    )

                exit_price = None
                realized_pnl = None
                return_pct = None

            else:
                if closed_at is None:
                    raise WebullPaperOrderStoreError(
                        "CLOSED paper order requires "
                        "closed_at."
                    )

                if record.exit_price is None:
                    raise WebullPaperOrderStoreError(
                        "CLOSED paper order requires "
                        "exit_price."
                    )

                if exit_reason not in {
                    "STOP",
                    "TARGET",
                    "TIME EXIT",
                }:
                    raise WebullPaperOrderStoreError(
                        "Unsupported paper-order exit reason."
                    )

                exit_price = round(
                    float(record.exit_price),
                    4,
                )

                if exit_price <= 0:
                    raise WebullPaperOrderStoreError(
                        "exit_price must be positive."
                    )

                realized_pnl = round(
                    (
                        exit_price - fill_price
                    )
                    * record.quantity,
                    6,
                )

                return_pct = round(
                    (
                        exit_price - fill_price
                    )
                    / fill_price
                    * 100.0,
                    6,
                )

        return WebullPaperOrderRecord(
            paper_order_id=paper_order_id,
            approval_reference=approval_reference,
            idempotency_key=idempotency_key,
            symbol=symbol,
            side=side,
            quantity=record.quantity,
            limit_price=limit_price,
            proposed_exposure=expected_exposure,
            status=status,
            created_at=created_at,
            submitted_at=submitted_at,
            safety_reason=safety_reason,
            strategy_name=strategy_name,
            reward_risk=(
                None
                if strategy_numbers["reward_risk"] is None
                else round(
                    strategy_numbers["reward_risk"],
                    6,
                )
            ),
            confirmation_time=confirmation_time,
            retracement_price=(
                None
                if strategy_numbers["retracement_price"] is None
                else round(
                    strategy_numbers["retracement_price"],
                    6,
                )
            ),
            impulse_atr_multiple=(
                None
                if strategy_numbers["impulse_atr_multiple"] is None
                else round(
                    strategy_numbers["impulse_atr_multiple"],
                    6,
                )
            ),
            pullback_volume_ratio=(
                None
                if strategy_numbers["pullback_volume_ratio"] is None
                else round(
                    strategy_numbers["pullback_volume_ratio"],
                    6,
                )
            ),
            target_price=target_price,
            stop_price=stop_price,
            lifecycle_status=lifecycle_status,
            filled_at=filled_at,
            fill_price=fill_price,
            highest_price=highest_price,
            lowest_price=lowest_price,
            mfe_pct=mfe_pct,
            mae_pct=mae_pct,
            closed_at=closed_at,
            exit_price=exit_price,
            exit_reason=exit_reason,
            realized_pnl=realized_pnl,
            return_pct=return_pct,
        )

    @staticmethod
    def _serialize_record(
        record: WebullPaperOrderRecord,
    ) -> dict[str, Any]:
        validated = (
            WebullPaperOrderStore._validate_record(
                record
            )
        )

        payload = asdict(validated)

        payload["created_at"] = (
            WebullPaperOrderStore._format_datetime(
                validated.created_at
            )
        )
        payload["submitted_at"] = (
            WebullPaperOrderStore._format_datetime(
                validated.submitted_at
            )
        )

        if validated.filled_at is not None:
            payload["filled_at"] = (
                WebullPaperOrderStore._format_datetime(
                    validated.filled_at
                )
            )

        if validated.closed_at is not None:
            payload["closed_at"] = (
                WebullPaperOrderStore._format_datetime(
                    validated.closed_at
                )
            )

        return payload

    @staticmethod
    def _parse_record(
        payload: Any,
    ) -> WebullPaperOrderRecord:
        if not isinstance(payload, dict):
            raise WebullPaperOrderStoreError(
                "Stored paper order must be an object."
            )

        required = {
            "paper_order_id",
            "approval_reference",
            "idempotency_key",
            "symbol",
            "side",
            "quantity",
            "limit_price",
            "proposed_exposure",
            "status",
            "created_at",
            "submitted_at",
            "safety_reason",
        }

        optional = {
            "target_price",
            "stop_price",
            "strategy_name",
            "reward_risk",
            "confirmation_time",
            "retracement_price",
            "impulse_atr_multiple",
            "pullback_volume_ratio",
            "lifecycle_status",
            "filled_at",
            "fill_price",
            "highest_price",
            "lowest_price",
            "mfe_pct",
            "mae_pct",
            "closed_at",
            "exit_price",
            "exit_reason",
            "realized_pnl",
            "return_pct",
        }

        unknown = set(payload) - required - optional
        missing = required - set(payload)

        if unknown:
            raise WebullPaperOrderStoreError(
                "Stored paper order contains unsupported "
                "fields: "
                + ", ".join(sorted(unknown))
            )

        if missing:
            raise WebullPaperOrderStoreError(
                "Stored paper order is missing fields: "
                + ", ".join(sorted(missing))
            )

        try:
            quantity = int(payload["quantity"])
            limit_price = float(payload["limit_price"])
            proposed_exposure = float(
                payload["proposed_exposure"]
            )
        except (TypeError, ValueError) as error:
            raise WebullPaperOrderStoreError(
                "Stored paper-order numeric fields "
                "are invalid."
            ) from error

        def optional_float(name: str) -> float | None:
            value = payload.get(name)

            if value is None:
                return None

            try:
                return float(value)
            except (TypeError, ValueError) as error:
                raise WebullPaperOrderStoreError(
                    f"Stored {name} is invalid."
                ) from error

        record = WebullPaperOrderRecord(
            paper_order_id=str(
                payload["paper_order_id"]
            ),
            approval_reference=str(
                payload["approval_reference"]
            ),
            idempotency_key=str(
                payload["idempotency_key"]
            ),
            symbol=str(payload["symbol"]),
            side=str(payload["side"]),
            quantity=quantity,
            limit_price=limit_price,
            proposed_exposure=proposed_exposure,
            status=str(payload["status"]),
            created_at=(
                WebullPaperOrderStore._parse_datetime(
                    payload["created_at"],
                    field_name="created_at",
                )
            ),
            submitted_at=(
                WebullPaperOrderStore._parse_datetime(
                    payload["submitted_at"],
                    field_name="submitted_at",
                )
            ),
            safety_reason=str(
                payload["safety_reason"]
            ),
            strategy_name=(
                None
                if payload.get("strategy_name") is None
                else str(payload["strategy_name"])
            ),
            reward_risk=optional_float(
                "reward_risk"
            ),
            confirmation_time=(
                None
                if payload.get("confirmation_time") is None
                else str(payload["confirmation_time"])
            ),
            retracement_price=optional_float(
                "retracement_price"
            ),
            impulse_atr_multiple=optional_float(
                "impulse_atr_multiple"
            ),
            pullback_volume_ratio=optional_float(
                "pullback_volume_ratio"
            ),
            target_price=optional_float(
                "target_price"
            ),
            stop_price=optional_float(
                "stop_price"
            ),
            lifecycle_status=str(
                payload.get(
                    "lifecycle_status",
                    "ENTRY PENDING",
                )
            ),
            filled_at=(
                WebullPaperOrderStore
                ._parse_optional_datetime(
                    payload.get("filled_at"),
                    field_name="filled_at",
                )
            ),
            fill_price=optional_float(
                "fill_price"
            ),
            highest_price=optional_float(
                "highest_price"
            ),
            lowest_price=optional_float(
                "lowest_price"
            ),
            mfe_pct=optional_float("mfe_pct"),
            mae_pct=optional_float("mae_pct"),
            closed_at=(
                WebullPaperOrderStore
                ._parse_optional_datetime(
                    payload.get("closed_at"),
                    field_name="closed_at",
                )
            ),
            exit_price=optional_float(
                "exit_price"
            ),
            exit_reason=str(
                payload.get("exit_reason", "")
            ),
            realized_pnl=optional_float(
                "realized_pnl"
            ),
            return_pct=optional_float(
                "return_pct"
            ),
        )

        return WebullPaperOrderStore._validate_record(
            record
        )

    def load(
        self,
    ) -> dict[str, WebullPaperOrderRecord]:
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
            raise WebullPaperOrderStoreError(
                "Paper-order store could not be read."
            ) from error

        if not isinstance(payload, dict):
            raise WebullPaperOrderStoreError(
                "Paper-order store root must be an object."
            )

        if payload.get("version") != 1:
            raise WebullPaperOrderStoreError(
                "Unsupported paper-order store version."
            )

        raw_records = payload.get("records")

        if not isinstance(raw_records, list):
            raise WebullPaperOrderStoreError(
                "Paper-order records must be a list."
            )

        records: dict[
            str,
            WebullPaperOrderRecord,
        ] = {}

        idempotency_keys: set[str] = set()

        for raw_record in raw_records:
            record = self._parse_record(raw_record)

            if record.paper_order_id in records:
                raise WebullPaperOrderStoreError(
                    "Duplicate paper-order ID in store."
                )

            if record.idempotency_key in idempotency_keys:
                raise WebullPaperOrderStoreError(
                    "Duplicate idempotency key in store."
                )

            records[record.paper_order_id] = record
            idempotency_keys.add(
                record.idempotency_key
            )

        return records

    def save(
        self,
        records: dict[
            str,
            WebullPaperOrderRecord,
        ],
    ) -> None:
        validated: dict[
            str,
            WebullPaperOrderRecord,
        ] = {}

        idempotency_keys: set[str] = set()

        for key, raw_record in records.items():
            record = self._validate_record(raw_record)

            if key != record.paper_order_id:
                raise WebullPaperOrderStoreError(
                    "Paper-order dictionary key does not "
                    "match paper_order_id."
                )

            if record.idempotency_key in idempotency_keys:
                raise WebullPaperOrderStoreError(
                    "Duplicate idempotency key."
                )

            validated[key] = record
            idempotency_keys.add(
                record.idempotency_key
            )

        payload = {
            "version": 1,
            "records": [
                self._serialize_record(record)
                for record in sorted(
                    validated.values(),
                    key=lambda item: item.created_at,
                )
            ],
        }

        encoded = json.dumps(
            payload,
            indent=2,
            sort_keys=True,
        ) + "\n"

        self.path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        try:
            self.temp_path.write_text(
                encoded,
                encoding="utf-8",
            )
            os.chmod(self.temp_path, 0o600)
            os.replace(
                self.temp_path,
                self.path,
            )
            os.chmod(self.path, 0o600)
        except OSError as error:
            try:
                self.temp_path.unlink(
                    missing_ok=True
                )
            except OSError:
                pass

            raise WebullPaperOrderStoreError(
                "Paper-order store could not be saved."
            ) from error

    def add(
        self,
        record: WebullPaperOrderRecord,
    ) -> None:
        validated = self._validate_record(record)
        records = self.load()

        if validated.paper_order_id in records:
            raise WebullPaperOrderStoreError(
                "DUPLICATE_PAPER_ORDER_ID"
            )

        if any(
            existing.idempotency_key
            == validated.idempotency_key
            for existing in records.values()
        ):
            raise WebullPaperOrderStoreError(
                "DUPLICATE_PAPER_SUBMISSION"
            )

        records[
            validated.paper_order_id
        ] = validated

        self.save(records)

    def update(
        self,
        record: WebullPaperOrderRecord,
    ) -> WebullPaperOrderRecord:
        validated = self._validate_record(record)
        records = self.load()

        existing = records.get(
            validated.paper_order_id
        )

        if existing is None:
            raise WebullPaperOrderStoreError(
                "PAPER_ORDER_NOT_FOUND"
            )

        if (
            existing.idempotency_key
            != validated.idempotency_key
        ):
            raise WebullPaperOrderStoreError(
                "PAPER_ORDER_IDEMPOTENCY_CHANGED"
            )

        records[
            validated.paper_order_id
        ] = validated

        self.save(records)

        return validated
