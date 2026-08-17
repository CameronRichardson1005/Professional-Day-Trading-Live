from __future__ import annotations

import json
import math
import os

from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

from .config import (
    WEBULL_SANDBOX_CLOSE_LEDGER_FILE,
)
from .webull_account_parser import (
    ParsedWebullPosition,
)


class WebullReduceOnlyCloseError(RuntimeError):
    pass


@dataclass(frozen=True)
class WebullReduceOnlyCloseIntent:
    """
    A SELL order that may only reduce an already-confirmed
    long Webull position.

    This is deliberately separate from WebullTradeIntent,
    which remains BUY-only.
    """

    client_order_id: str
    symbol: str
    quantity: int
    limit_price: float
    confirmed_position_quantity: float
    created_at: datetime

    strategy_name: str = "REDUCE_ONLY_CLOSE"
    side: str = "SELL"
    order_type: str = "LIMIT"
    time_in_force: str = "DAY"
    support_trading_session: str = "CORE"

    def __post_init__(self) -> None:
        key = self.client_order_id.strip()
        symbol = self.symbol.strip().upper()

        if not key:
            raise WebullReduceOnlyCloseError(
                "CLIENT_ORDER_ID_REQUIRED"
            )

        if not symbol:
            raise WebullReduceOnlyCloseError(
                "SYMBOL_REQUIRED"
            )

        if (
            isinstance(self.quantity, bool)
            or not isinstance(self.quantity, int)
            or self.quantity <= 0
        ):
            raise WebullReduceOnlyCloseError(
                "INVALID_CLOSE_QUANTITY"
            )

        try:
            price = float(self.limit_price)
            held = float(
                self.confirmed_position_quantity
            )
        except (TypeError, ValueError) as error:
            raise WebullReduceOnlyCloseError(
                "INVALID_CLOSE_NUMERIC_VALUE"
            ) from error

        if (
            not math.isfinite(price)
            or price <= 0
        ):
            raise WebullReduceOnlyCloseError(
                "INVALID_CLOSE_LIMIT_PRICE"
            )

        if (
            not math.isfinite(held)
            or held <= 0
        ):
            raise WebullReduceOnlyCloseError(
                "INVALID_CONFIRMED_POSITION_QUANTITY"
            )

        if float(self.quantity) > held:
            raise WebullReduceOnlyCloseError(
                "CLOSE_QUANTITY_EXCEEDS_POSITION"
            )

        if self.created_at.tzinfo is None:
            raise WebullReduceOnlyCloseError(
                "CLOSE_TIMESTAMP_MUST_BE_TIMEZONE_AWARE"
            )

        object.__setattr__(
            self,
            "client_order_id",
            key,
        )

        object.__setattr__(
            self,
            "symbol",
            symbol,
        )

        object.__setattr__(
            self,
            "limit_price",
            round(price, 4),
        )

        object.__setattr__(
            self,
            "confirmed_position_quantity",
            round(held, 5),
        )

        object.__setattr__(
            self,
            "created_at",
            self.created_at.astimezone(UTC),
        )

    def broker_payload(self) -> dict[str, str]:
        """
        Exact simple-stock SELL shape.

        There is intentionally no SHORT side anywhere in this
        intent type.
        """

        return {
            "combo_type": "NORMAL",
            "client_order_id": self.client_order_id,
            "symbol": self.symbol,
            "instrument_type": "EQUITY",
            "market": "US",
            "order_type": "LIMIT",
            "limit_price": (
                f"{self.limit_price:.4f}"
            ),
            "quantity": str(self.quantity),
            "support_trading_session": "CORE",
            "side": "SELL",
            "time_in_force": "DAY",
            "entrust_type": "QTY",
        }


def select_reduce_only_position(
    *,
    positions: tuple[ParsedWebullPosition, ...]
    | list[ParsedWebullPosition],
    symbol: str,
) -> ParsedWebullPosition:
    """
    Select exactly one confirmed positive long position.

    Zero matches and duplicate symbol records both fail closed.
    """

    key = symbol.strip().upper()

    if not key:
        raise WebullReduceOnlyCloseError(
            "SYMBOL_REQUIRED"
        )

    matches = [
        position
        for position in positions
        if position.symbol == key
    ]

    if not matches:
        raise WebullReduceOnlyCloseError(
            "LONG_POSITION_NOT_FOUND"
        )

    if len(matches) != 1:
        raise WebullReduceOnlyCloseError(
            "DUPLICATE_POSITION_RECORD"
        )

    position = matches[0]

    if (
        not math.isfinite(
            float(position.quantity)
        )
        or float(position.quantity) <= 0
    ):
        raise WebullReduceOnlyCloseError(
            "LONG_POSITION_QUANTITY_INVALID"
        )

    return position


def build_reduce_only_close_intent(
    *,
    client_order_id: str,
    positions: tuple[ParsedWebullPosition, ...]
    | list[ParsedWebullPosition],
    symbol: str,
    quantity: int,
    limit_price: float,
    created_at: datetime,
) -> WebullReduceOnlyCloseIntent:
    position = select_reduce_only_position(
        positions=positions,
        symbol=symbol,
    )

    return WebullReduceOnlyCloseIntent(
        client_order_id=client_order_id,
        symbol=position.symbol,
        quantity=quantity,
        limit_price=limit_price,
        confirmed_position_quantity=(
            position.quantity
        ),
        created_at=created_at,
    )


@dataclass(frozen=True)
class WebullReduceOnlyCloseRecord:
    client_order_id: str
    symbol: str
    side: str
    quantity: int
    limit_price: float
    confirmed_position_quantity: float

    status: str

    created_at: datetime
    updated_at: datetime

    broker_order_id: str | None = None
    broker_status: str | None = None

    filled_quantity: float = 0.0
    average_fill_price: float | None = None

    last_reconciled_at: datetime | None = None
    last_error: str | None = None


class WebullReduceOnlyCloseLedger:
    """
    Durable close-order state kept separate from the BUY-order
    execution ledger.

    Writes are atomic and permissions are forced to 0600.
    """

    VERSION = 1

    VALID_STATUSES = {
        "PREPARED",
        "SUBMITTING",
        "SUBMITTED",
        "SUBMISSION_UNKNOWN",
        "BROKER_STATE_UNKNOWN",
        "PARTIALLY_FILLED",
        "FILLED",
        "CANCEL_PENDING",
        "CANCELLED",
        "REJECTED",
        "ERROR",
    }

    def __init__(
        self,
        path: Path | str = (
            WEBULL_SANDBOX_CLOSE_LEDGER_FILE
        ),
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.path = Path(path)
        self.temp_path = self.path.with_suffix(
            self.path.suffix + ".tmp"
        )

        self.clock = (
            clock
            if clock is not None
            else lambda: datetime.now(UTC)
        )

    @staticmethod
    def _format_datetime(
        value: datetime | None,
    ) -> str | None:
        if value is None:
            return None

        if value.tzinfo is None:
            raise WebullReduceOnlyCloseError(
                "CLOSE_LEDGER_TIMESTAMP_NOT_AWARE"
            )

        return (
            value.astimezone(UTC)
            .isoformat()
            .replace("+00:00", "Z")
        )

    @staticmethod
    def _parse_datetime(
        value,
        *,
        required: bool,
    ) -> datetime | None:
        if value in {None, ""}:
            if required:
                raise WebullReduceOnlyCloseError(
                    "CLOSE_LEDGER_TIMESTAMP_REQUIRED"
                )

            return None

        if not isinstance(value, str):
            raise WebullReduceOnlyCloseError(
                "CLOSE_LEDGER_TIMESTAMP_INVALID"
            )

        try:
            result = datetime.fromisoformat(
                value.replace("Z", "+00:00")
            )
        except ValueError as error:
            raise WebullReduceOnlyCloseError(
                "CLOSE_LEDGER_TIMESTAMP_INVALID"
            ) from error

        if result.tzinfo is None:
            raise WebullReduceOnlyCloseError(
                "CLOSE_LEDGER_TIMESTAMP_NOT_AWARE"
            )

        return result.astimezone(UTC)

    @classmethod
    def _validate(
        cls,
        record: WebullReduceOnlyCloseRecord,
    ) -> WebullReduceOnlyCloseRecord:
        key = record.client_order_id.strip()
        symbol = record.symbol.strip().upper()
        side = record.side.strip().upper()
        status = record.status.strip().upper()

        if not key:
            raise WebullReduceOnlyCloseError(
                "CLIENT_ORDER_ID_REQUIRED"
            )

        if not symbol:
            raise WebullReduceOnlyCloseError(
                "SYMBOL_REQUIRED"
            )

        if side != "SELL":
            raise WebullReduceOnlyCloseError(
                "CLOSE_LEDGER_SIDE_MUST_BE_SELL"
            )

        if status not in cls.VALID_STATUSES:
            raise WebullReduceOnlyCloseError(
                "INVALID_CLOSE_STATUS"
            )

        if (
            isinstance(record.quantity, bool)
            or not isinstance(record.quantity, int)
            or record.quantity <= 0
        ):
            raise WebullReduceOnlyCloseError(
                "INVALID_CLOSE_QUANTITY"
            )

        if (
            not math.isfinite(
                float(record.limit_price)
            )
            or float(record.limit_price) <= 0
        ):
            raise WebullReduceOnlyCloseError(
                "INVALID_CLOSE_LIMIT_PRICE"
            )

        held = float(
            record.confirmed_position_quantity
        )

        if (
            not math.isfinite(held)
            or held <= 0
            or float(record.quantity) > held
        ):
            raise WebullReduceOnlyCloseError(
                "CLOSE_QUANTITY_EXCEEDS_POSITION"
            )

        filled = float(
            record.filled_quantity
        )

        if (
            not math.isfinite(filled)
            or filled < 0
            or filled > record.quantity
        ):
            raise WebullReduceOnlyCloseError(
                "INVALID_CLOSE_FILLED_QUANTITY"
            )

        if (
            record.average_fill_price is not None
            and (
                not math.isfinite(
                    float(
                        record.average_fill_price
                    )
                )
                or float(
                    record.average_fill_price
                ) <= 0
            )
        ):
            raise WebullReduceOnlyCloseError(
                "INVALID_CLOSE_AVERAGE_FILL_PRICE"
            )

        for timestamp in (
            record.created_at,
            record.updated_at,
            record.last_reconciled_at,
        ):
            if (
                timestamp is not None
                and timestamp.tzinfo is None
            ):
                raise WebullReduceOnlyCloseError(
                    "CLOSE_LEDGER_TIMESTAMP_NOT_AWARE"
                )

        return replace(
            record,
            client_order_id=key,
            symbol=symbol,
            side="SELL",
            status=status,
            limit_price=round(
                float(record.limit_price),
                4,
            ),
            confirmed_position_quantity=round(
                held,
                5,
            ),
            filled_quantity=round(
                filled,
                5,
            ),
            average_fill_price=(
                None
                if record.average_fill_price is None
                else round(
                    float(
                        record.average_fill_price
                    ),
                    4,
                )
            ),
            created_at=(
                record.created_at.astimezone(UTC)
            ),
            updated_at=(
                record.updated_at.astimezone(UTC)
            ),
            last_reconciled_at=(
                None
                if record.last_reconciled_at is None
                else record.last_reconciled_at
                .astimezone(UTC)
            ),
        )

    @classmethod
    def _serialize(
        cls,
        record: WebullReduceOnlyCloseRecord,
    ) -> dict:
        record = cls._validate(record)
        payload = asdict(record)

        payload["created_at"] = (
            cls._format_datetime(
                record.created_at
            )
        )

        payload["updated_at"] = (
            cls._format_datetime(
                record.updated_at
            )
        )

        payload["last_reconciled_at"] = (
            cls._format_datetime(
                record.last_reconciled_at
            )
        )

        return payload

    @classmethod
    def _parse(
        cls,
        payload,
    ) -> WebullReduceOnlyCloseRecord:
        if not isinstance(payload, dict):
            raise WebullReduceOnlyCloseError(
                "INVALID_CLOSE_LEDGER_RECORD"
            )

        try:
            record = WebullReduceOnlyCloseRecord(
                client_order_id=str(
                    payload["client_order_id"]
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
                limit_price=float(
                    payload["limit_price"]
                ),
                confirmed_position_quantity=float(
                    payload[
                        "confirmed_position_quantity"
                    ]
                ),
                status=str(
                    payload["status"]
                ),
                created_at=(
                    cls._parse_datetime(
                        payload.get(
                            "created_at"
                        ),
                        required=True,
                    )
                ),
                updated_at=(
                    cls._parse_datetime(
                        payload.get(
                            "updated_at"
                        ),
                        required=True,
                    )
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
                        0.0,
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
            raise WebullReduceOnlyCloseError(
                "INVALID_CLOSE_LEDGER_RECORD"
            ) from error

        return cls._validate(record)

    def load(
        self,
    ) -> dict[str, WebullReduceOnlyCloseRecord]:
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
            raise WebullReduceOnlyCloseError(
                "CLOSE_LEDGER_UNREADABLE"
            ) from error

        if (
            not isinstance(payload, dict)
            or payload.get("version")
            != self.VERSION
            or not isinstance(
                payload.get("records"),
                list,
            )
        ):
            raise WebullReduceOnlyCloseError(
                "CLOSE_LEDGER_INVALID"
            )

        result = {}

        for raw in payload["records"]:
            record = self._parse(raw)

            if record.client_order_id in result:
                raise WebullReduceOnlyCloseError(
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
            WebullReduceOnlyCloseRecord,
        ],
    ) -> None:
        validated = {}

        for key, record in records.items():
            record = self._validate(record)

            if key != record.client_order_id:
                raise WebullReduceOnlyCloseError(
                    "CLOSE_LEDGER_KEY_ID_MISMATCH"
                )

            if key in validated:
                raise WebullReduceOnlyCloseError(
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

            raise WebullReduceOnlyCloseError(
                "CLOSE_LEDGER_WRITE_FAILED"
            ) from error

    def add_intent(
        self,
        intent: WebullReduceOnlyCloseIntent,
    ) -> WebullReduceOnlyCloseRecord:
        records = self.load()

        if intent.client_order_id in records:
            raise WebullReduceOnlyCloseError(
                "DUPLICATE_CLIENT_ORDER_ID"
            )

        record = WebullReduceOnlyCloseRecord(
            client_order_id=(
                intent.client_order_id
            ),
            symbol=intent.symbol,
            side="SELL",
            quantity=intent.quantity,
            limit_price=intent.limit_price,
            confirmed_position_quantity=(
                intent.confirmed_position_quantity
            ),
            status="PREPARED",
            created_at=intent.created_at,
            updated_at=intent.created_at,
        )

        record = self._validate(record)

        records[
            record.client_order_id
        ] = record

        self.save(records)

        return record

    def mark_state(
        self,
        *,
        client_order_id: str,
        status: str,
        last_error: str | None = None,
    ) -> WebullReduceOnlyCloseRecord:
        records = self.load()
        key = client_order_id.strip()

        record = records.get(key)

        if record is None:
            raise WebullReduceOnlyCloseError(
                "CLOSE_ORDER_NOT_FOUND"
            )

        now = self.clock()

        if now.tzinfo is None:
            raise WebullReduceOnlyCloseError(
                "CLOSE_LEDGER_CLOCK_NOT_AWARE"
            )

        updated = replace(
            record,
            status=status,
            updated_at=now.astimezone(UTC),
            last_error=last_error,
        )

        updated = self._validate(updated)
        records[key] = updated
        self.save(records)

        return updated

    def record_broker_state(
        self,
        *,
        client_order_id: str,
        broker_status: str,
        status: str,
        broker_order_id: str | None = None,
        filled_quantity: float = 0.0,
        average_fill_price: float | None = None,
    ) -> WebullReduceOnlyCloseRecord:
        records = self.load()
        key = client_order_id.strip()

        record = records.get(key)

        if record is None:
            raise WebullReduceOnlyCloseError(
                "CLOSE_ORDER_NOT_FOUND"
            )

        now = self.clock()

        if now.tzinfo is None:
            raise WebullReduceOnlyCloseError(
                "CLOSE_LEDGER_CLOCK_NOT_AWARE"
            )

        updated = replace(
            record,
            status=status,
            broker_order_id=broker_order_id,
            broker_status=(
                broker_status.strip().upper()
            ),
            filled_quantity=(
                float(filled_quantity)
            ),
            average_fill_price=(
                average_fill_price
            ),
            last_reconciled_at=(
                now.astimezone(UTC)
            ),
            updated_at=(
                now.astimezone(UTC)
            ),
            last_error=None,
        )

        updated = self._validate(updated)
        records[key] = updated
        self.save(records)

        return updated
