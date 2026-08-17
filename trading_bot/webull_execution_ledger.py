from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from .config import (
    WEBULL_EXECUTION_LEDGER_FILE,
)
from .webull_execution import (
    WebullExecutionMode,
    WebullTradeIntent,
    parse_execution_mode,
)


class WebullExecutionLedgerError(RuntimeError):
    pass


@dataclass(frozen=True)
class WebullExecutionRecord:
    client_order_id: str
    execution_mode: str
    strategy_name: str
    symbol: str
    side: str
    quantity: int
    order_type: str
    limit_price: float
    time_in_force: str
    support_trading_session: str

    status: str

    created_at: datetime
    updated_at: datetime

    broker_order_id: str | None = None
    broker_status: str | None = None

    filled_quantity: float = 0.0
    average_fill_price: float | None = None

    last_reconciled_at: datetime | None = None

    manual_override: bool = False
    manual_override_reason: str | None = None
    manual_override_at: datetime | None = None

    replaced_from: str | None = None
    replacement_order_id: str | None = None

    replace_requested_quantity: int | None = None
    replace_requested_limit_price: float | None = None
    replace_requested_at: datetime | None = None

    cancel_requested: bool = False

    last_error: str | None = None


class WebullExecutionLedger:
    """
    Durable source-of-record for Webull execution state.

    The ledger is written BEFORE and AFTER broker operations.
    It stores no API secrets, approval tokens, or credentials.
    """

    VERSION = 1

    VALID_STATUSES = {
        "PREPARED",
        "SUBMITTING",
        "SUBMITTED",
        "SUBMISSION_UNKNOWN",
        "BROKER_STATE_UNKNOWN",
        "REJECTED",
        "PARTIALLY_FILLED",
        "FILLED",
        "REPLACE_PENDING",
        "CANCEL_PENDING",
        "CANCELLED",
        "ERROR",
    }

    def __init__(
        self,
        path: Path | str = (
            WEBULL_EXECUTION_LEDGER_FILE
        ),
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.path = Path(path)
        self.temp_path = self.path.with_suffix(
            self.path.suffix + ".tmp"
        )
        self.clock = clock or (
            lambda: datetime.now(UTC)
        )

    @staticmethod
    def _format_datetime(
        value: datetime | None,
    ) -> str | None:
        if value is None:
            return None

        if value.tzinfo is None:
            raise WebullExecutionLedgerError(
                "LEDGER_TIMESTAMP_MUST_BE_TIMEZONE_AWARE"
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
        required: bool,
        field_name: str,
    ) -> datetime | None:
        if value in {None, ""}:
            if required:
                raise WebullExecutionLedgerError(
                    f"{field_name.upper()}_REQUIRED"
                )

            return None

        if not isinstance(value, str):
            raise WebullExecutionLedgerError(
                f"{field_name.upper()}_INVALID"
            )

        try:
            result = datetime.fromisoformat(
                value.replace("Z", "+00:00")
            )
        except ValueError as error:
            raise WebullExecutionLedgerError(
                f"{field_name.upper()}_INVALID"
            ) from error

        if result.tzinfo is None:
            raise WebullExecutionLedgerError(
                f"{field_name.upper()}_MUST_HAVE_TIMEZONE"
            )

        return result.astimezone(UTC)

    @classmethod
    def _validate(
        cls,
        record: WebullExecutionRecord,
    ) -> WebullExecutionRecord:
        client_order_id = (
            record.client_order_id.strip()
        )

        if not client_order_id:
            raise WebullExecutionLedgerError(
                "CLIENT_ORDER_ID_REQUIRED"
            )

        mode = parse_execution_mode(
            record.execution_mode
        )

        strategy_name = (
            record.strategy_name.strip()
        )
        symbol = record.symbol.strip().upper()
        side = record.side.strip().upper()

        if not strategy_name:
            raise WebullExecutionLedgerError(
                "STRATEGY_NAME_REQUIRED"
            )

        if not symbol:
            raise WebullExecutionLedgerError(
                "SYMBOL_REQUIRED"
            )

        if side != "BUY":
            raise WebullExecutionLedgerError(
                "ONLY_BUY_EXECUTION_SUPPORTED"
            )

        if record.quantity <= 0:
            raise WebullExecutionLedgerError(
                "INVALID_QUANTITY"
            )

        limit_price = round(
            float(record.limit_price),
            4,
        )

        if limit_price <= 0:
            raise WebullExecutionLedgerError(
                "INVALID_LIMIT_PRICE"
            )

        status = record.status.strip().upper()

        if status not in cls.VALID_STATUSES:
            raise WebullExecutionLedgerError(
                "INVALID_EXECUTION_STATUS"
            )

        if record.created_at.tzinfo is None:
            raise WebullExecutionLedgerError(
                "CREATED_AT_MUST_HAVE_TIMEZONE"
            )

        if record.updated_at.tzinfo is None:
            raise WebullExecutionLedgerError(
                "UPDATED_AT_MUST_HAVE_TIMEZONE"
            )

        created_at = (
            record.created_at.astimezone(UTC)
        )
        updated_at = (
            record.updated_at.astimezone(UTC)
        )

        if updated_at < created_at:
            raise WebullExecutionLedgerError(
                "UPDATED_AT_PRECEDES_CREATED_AT"
            )

        filled_quantity = float(
            record.filled_quantity
        )

        if filled_quantity < 0:
            raise WebullExecutionLedgerError(
                "FILLED_QUANTITY_NEGATIVE"
            )

        if filled_quantity > record.quantity:
            raise WebullExecutionLedgerError(
                "FILLED_QUANTITY_EXCEEDS_ORDER"
            )

        average_fill_price = (
            None
            if record.average_fill_price is None
            else float(
                record.average_fill_price
            )
        )

        if (
            average_fill_price is not None
            and average_fill_price <= 0
        ):
            raise WebullExecutionLedgerError(
                "INVALID_AVERAGE_FILL_PRICE"
            )

        if record.manual_override:
            reason = (
                record.manual_override_reason or ""
            ).strip()

            if not reason:
                raise WebullExecutionLedgerError(
                    "MANUAL_OVERRIDE_REASON_REQUIRED"
                )

            if record.manual_override_at is None:
                raise WebullExecutionLedgerError(
                    "MANUAL_OVERRIDE_TIME_REQUIRED"
                )

        replace_fields_present = (
            record.replace_requested_quantity is not None,
            record.replace_requested_limit_price is not None,
            record.replace_requested_at is not None,
        )

        if (
            any(replace_fields_present)
            and not all(replace_fields_present)
        ):
            raise WebullExecutionLedgerError(
                "INCOMPLETE_REPLACE_REQUEST"
            )

        replace_requested_quantity = None
        replace_requested_limit_price = None
        replace_requested_at = None

        if all(replace_fields_present):
            if isinstance(
                record.replace_requested_quantity,
                bool,
            ):
                raise WebullExecutionLedgerError(
                    "INVALID_REPLACE_QUANTITY"
                )

            try:
                replace_requested_quantity = int(
                    record.replace_requested_quantity
                )
            except (
                TypeError,
                ValueError,
            ) as error:
                raise WebullExecutionLedgerError(
                    "INVALID_REPLACE_QUANTITY"
                ) from error

            if replace_requested_quantity <= 0:
                raise WebullExecutionLedgerError(
                    "INVALID_REPLACE_QUANTITY"
                )

            try:
                replace_requested_limit_price = round(
                    float(
                        record.replace_requested_limit_price
                    ),
                    4,
                )
            except (
                TypeError,
                ValueError,
            ) as error:
                raise WebullExecutionLedgerError(
                    "INVALID_REPLACE_LIMIT_PRICE"
                ) from error

            if replace_requested_limit_price <= 0:
                raise WebullExecutionLedgerError(
                    "INVALID_REPLACE_LIMIT_PRICE"
                )

            replace_requested_at = (
                record.replace_requested_at
            )

            if not isinstance(
                replace_requested_at,
                datetime,
            ):
                raise WebullExecutionLedgerError(
                    "REPLACE_REQUEST_TIME_INVALID"
                )

            if replace_requested_at.tzinfo is None:
                raise WebullExecutionLedgerError(
                    "REPLACE_REQUEST_TIME_MUST_HAVE_TIMEZONE"
                )

            replace_requested_at = (
                replace_requested_at.astimezone(UTC)
            )

        return replace(
            record,
            client_order_id=client_order_id,
            execution_mode=mode.value,
            strategy_name=strategy_name,
            symbol=symbol,
            side=side,
            order_type=(
                record.order_type.strip().upper()
            ),
            limit_price=limit_price,
            time_in_force=(
                record.time_in_force
                .strip()
                .upper()
            ),
            support_trading_session=(
                record.support_trading_session
                .strip()
                .upper()
            ),
            status=status,
            created_at=created_at,
            updated_at=updated_at,
            filled_quantity=filled_quantity,
            average_fill_price=(
                average_fill_price
            ),
            replace_requested_quantity=(
                replace_requested_quantity
            ),
            replace_requested_limit_price=(
                replace_requested_limit_price
            ),
            replace_requested_at=(
                replace_requested_at
            ),
            manual_override_reason=(
                None
                if record.manual_override_reason
                is None
                else record.manual_override_reason.strip()
            ),
            last_error=(
                None
                if record.last_error is None
                else record.last_error.strip()
            ),
        )

    @classmethod
    def _serialize(
        cls,
        record: WebullExecutionRecord,
    ) -> dict[str, Any]:
        record = cls._validate(record)
        payload = asdict(record)

        for field_name in (
            "created_at",
            "updated_at",
            "last_reconciled_at",
            "manual_override_at",
            "replace_requested_at",
        ):
            payload[field_name] = (
                cls._format_datetime(
                    getattr(
                        record,
                        field_name,
                    )
                )
            )

        return payload

    @classmethod
    def _parse(
        cls,
        payload: Any,
    ) -> WebullExecutionRecord:
        if not isinstance(payload, dict):
            raise WebullExecutionLedgerError(
                "LEDGER_RECORD_MUST_BE_OBJECT"
            )

        try:
            record = WebullExecutionRecord(
                client_order_id=str(
                    payload["client_order_id"]
                ),
                execution_mode=str(
                    payload["execution_mode"]
                ),
                strategy_name=str(
                    payload["strategy_name"]
                ),
                symbol=str(
                    payload["symbol"]
                ),
                side=str(
                    payload["side"]
                ),
                quantity=int(
                    payload["quantity"]
                ),
                order_type=str(
                    payload["order_type"]
                ),
                limit_price=float(
                    payload["limit_price"]
                ),
                time_in_force=str(
                    payload["time_in_force"]
                ),
                support_trading_session=str(
                    payload[
                        "support_trading_session"
                    ]
                ),
                status=str(
                    payload["status"]
                ),
                created_at=cls._parse_datetime(
                    payload.get("created_at"),
                    required=True,
                    field_name="created_at",
                ),
                updated_at=cls._parse_datetime(
                    payload.get("updated_at"),
                    required=True,
                    field_name="updated_at",
                ),
                broker_order_id=(
                    payload.get(
                        "broker_order_id"
                    )
                ),
                broker_status=(
                    payload.get(
                        "broker_status"
                    )
                ),
                filled_quantity=float(
                    payload.get(
                        "filled_quantity",
                        0,
                    )
                ),
                average_fill_price=(
                    None
                    if payload.get(
                        "average_fill_price"
                    ) is None
                    else float(
                        payload[
                            "average_fill_price"
                        ]
                    )
                ),
                last_reconciled_at=(
                    cls._parse_datetime(
                        payload.get(
                            "last_reconciled_at"
                        ),
                        required=False,
                        field_name=(
                            "last_reconciled_at"
                        ),
                    )
                ),
                manual_override=bool(
                    payload.get(
                        "manual_override",
                        False,
                    )
                ),
                manual_override_reason=(
                    payload.get(
                        "manual_override_reason"
                    )
                ),
                manual_override_at=(
                    cls._parse_datetime(
                        payload.get(
                            "manual_override_at"
                        ),
                        required=False,
                        field_name=(
                            "manual_override_at"
                        ),
                    )
                ),
                replaced_from=(
                    payload.get(
                        "replaced_from"
                    )
                ),
                replacement_order_id=(
                    payload.get(
                        "replacement_order_id"
                    )
                ),
                replace_requested_quantity=(
                    None
                    if payload.get(
                        "replace_requested_quantity"
                    ) is None
                    else int(
                        payload[
                            "replace_requested_quantity"
                        ]
                    )
                ),
                replace_requested_limit_price=(
                    None
                    if payload.get(
                        "replace_requested_limit_price"
                    ) is None
                    else float(
                        payload[
                            "replace_requested_limit_price"
                        ]
                    )
                ),
                replace_requested_at=(
                    cls._parse_datetime(
                        payload.get(
                            "replace_requested_at"
                        ),
                        required=False,
                        field_name=(
                            "replace_requested_at"
                        ),
                    )
                ),
                cancel_requested=bool(
                    payload.get(
                        "cancel_requested",
                        False,
                    )
                ),
                last_error=(
                    payload.get(
                        "last_error"
                    )
                ),
            )
        except (
            KeyError,
            TypeError,
            ValueError,
        ) as error:
            raise WebullExecutionLedgerError(
                "INVALID_LEDGER_RECORD"
            ) from error

        return cls._validate(record)

    def load(
        self,
    ) -> dict[str, WebullExecutionRecord]:
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
            raise WebullExecutionLedgerError(
                "EXECUTION_LEDGER_UNREADABLE"
            ) from error

        if not isinstance(payload, dict):
            raise WebullExecutionLedgerError(
                "EXECUTION_LEDGER_ROOT_INVALID"
            )

        if payload.get("version") != self.VERSION:
            raise WebullExecutionLedgerError(
                "EXECUTION_LEDGER_VERSION_UNSUPPORTED"
            )

        records = payload.get("records")

        if not isinstance(records, list):
            raise WebullExecutionLedgerError(
                "EXECUTION_LEDGER_RECORDS_INVALID"
            )

        result = {}

        for raw in records:
            record = self._parse(raw)

            if record.client_order_id in result:
                raise WebullExecutionLedgerError(
                    "DUPLICATE_CLIENT_ORDER_ID"
                )

            result[
                record.client_order_id
            ] = record

        return result

    def save(
        self,
        records: dict[
            str,
            WebullExecutionRecord,
        ],
    ) -> None:
        validated = {}

        for key, record in records.items():
            record = self._validate(record)

            if key != record.client_order_id:
                raise WebullExecutionLedgerError(
                    "LEDGER_KEY_ID_MISMATCH"
                )

            if key in validated:
                raise WebullExecutionLedgerError(
                    "DUPLICATE_CLIENT_ORDER_ID"
                )

            validated[key] = record

        payload = {
            "version": self.VERSION,
            "records": [
                self._serialize(record)
                for record in sorted(
                    validated.values(),
                    key=lambda item: (
                        item.created_at,
                        item.client_order_id,
                    ),
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

            raise WebullExecutionLedgerError(
                "EXECUTION_LEDGER_WRITE_FAILED"
            ) from error

    def add_intent(
        self,
        *,
        intent: WebullTradeIntent,
        execution_mode: (
            str | WebullExecutionMode
        ),
    ) -> WebullExecutionRecord:
        mode = parse_execution_mode(
            execution_mode
        )

        records = self.load()

        if intent.client_order_id in records:
            raise WebullExecutionLedgerError(
                "DUPLICATE_CLIENT_ORDER_ID"
            )

        record = WebullExecutionRecord(
            client_order_id=(
                intent.client_order_id
            ),
            execution_mode=mode.value,
            strategy_name=(
                intent.strategy_name
            ),
            symbol=intent.symbol,
            side=intent.side,
            quantity=intent.quantity,
            order_type=intent.order_type,
            limit_price=intent.limit_price,
            time_in_force=(
                intent.time_in_force
            ),
            support_trading_session=(
                intent.support_trading_session
            ),
            status="PREPARED",
            created_at=intent.created_at,
            updated_at=intent.created_at,
        )

        records[
            record.client_order_id
        ] = record

        self.save(records)

        return record

    def _replace_record(
        self,
        client_order_id: str,
        **changes: Any,
    ) -> WebullExecutionRecord:
        records = self.load()

        key = client_order_id.strip()

        record = records.get(key)

        if record is None:
            raise WebullExecutionLedgerError(
                "EXECUTION_ORDER_NOT_FOUND"
            )

        now = self.clock()

        if now.tzinfo is None:
            raise WebullExecutionLedgerError(
                "LEDGER_CLOCK_MUST_BE_TIMEZONE_AWARE"
            )

        updated = replace(
            record,
            **changes,
            updated_at=now.astimezone(UTC),
        )

        updated = self._validate(
            updated
        )

        records[key] = updated
        self.save(records)

        return updated

    def mark_manual_override(
        self,
        *,
        client_order_id: str,
        reason: str,
    ) -> WebullExecutionRecord:
        reason = reason.strip()

        if not reason:
            raise WebullExecutionLedgerError(
                "MANUAL_OVERRIDE_REASON_REQUIRED"
            )

        now = self.clock()

        if now.tzinfo is None:
            raise WebullExecutionLedgerError(
                "LEDGER_CLOCK_MUST_BE_TIMEZONE_AWARE"
            )

        return self._replace_record(
            client_order_id,
            manual_override=True,
            manual_override_reason=reason,
            manual_override_at=(
                now.astimezone(UTC)
            ),
        )

    def return_to_auto(
        self,
        *,
        client_order_id: str,
    ) -> WebullExecutionRecord:
        return self._replace_record(
            client_order_id,
            manual_override=False,
            manual_override_reason=None,
            manual_override_at=None,
        )

    def mark_replace_requested(
        self,
        *,
        client_order_id: str,
        quantity: int,
        limit_price: float,
    ) -> WebullExecutionRecord:
        if (
            isinstance(quantity, bool)
            or not isinstance(quantity, int)
            or quantity <= 0
        ):
            raise WebullExecutionLedgerError(
                "INVALID_REPLACE_QUANTITY"
            )

        try:
            price = round(
                float(limit_price),
                4,
            )
        except (
            TypeError,
            ValueError,
        ) as error:
            raise WebullExecutionLedgerError(
                "INVALID_REPLACE_LIMIT_PRICE"
            ) from error

        if price <= 0:
            raise WebullExecutionLedgerError(
                "INVALID_REPLACE_LIMIT_PRICE"
            )

        now = self.clock()

        if now.tzinfo is None:
            raise WebullExecutionLedgerError(
                "LEDGER_CLOCK_MUST_BE_TIMEZONE_AWARE"
            )

        return self._replace_record(
            client_order_id,
            status="REPLACE_PENDING",
            replace_requested_quantity=quantity,
            replace_requested_limit_price=price,
            replace_requested_at=(
                now.astimezone(UTC)
            ),
            last_error=None,
        )

    def clear_replace_request(
        self,
        *,
        client_order_id: str,
    ) -> WebullExecutionRecord:
        return self._replace_record(
            client_order_id,
            replace_requested_quantity=None,
            replace_requested_limit_price=None,
            replace_requested_at=None,
        )

    def mark_cancel_requested(
        self,
        *,
        client_order_id: str,
    ) -> WebullExecutionRecord:
        return self._replace_record(
            client_order_id,
            cancel_requested=True,
            status="CANCEL_PENDING",
        )

    def mark_operation_state(
        self,
        *,
        client_order_id: str,
        status: str,
        last_error: str | None = None,
    ) -> WebullExecutionRecord:
        return self._replace_record(
            client_order_id,
            status=status,
            last_error=last_error,
        )

    def record_broker_state(
        self,
        *,
        client_order_id: str,
        broker_status: str,
        broker_order_id: str | None = None,
        filled_quantity: float = 0,
        average_fill_price: float | None = None,
        quantity: int | None = None,
        limit_price: float | None = None,
        status: str = "SUBMITTED",
    ) -> WebullExecutionRecord:
        now = self.clock()

        if now.tzinfo is None:
            raise WebullExecutionLedgerError(
                "LEDGER_CLOCK_MUST_BE_TIMEZONE_AWARE"
            )

        records = self.load()

        key = client_order_id.strip()
        record = records.get(key)

        if record is None:
            raise WebullExecutionLedgerError(
                "EXECUTION_ORDER_NOT_FOUND"
            )

        effective_quantity = (
            record.quantity
            if quantity is None
            else int(quantity)
        )

        effective_limit_price = (
            record.limit_price
            if limit_price is None
            else float(limit_price)
        )

        return self._replace_record(
            client_order_id,
            status=status,
            broker_order_id=broker_order_id,
            broker_status=(
                broker_status.strip().upper()
            ),
            quantity=effective_quantity,
            limit_price=effective_limit_price,
            filled_quantity=(
                float(filled_quantity)
            ),
            average_fill_price=(
                average_fill_price
            ),
            last_reconciled_at=(
                now.astimezone(UTC)
            ),
            last_error=None,
        )
