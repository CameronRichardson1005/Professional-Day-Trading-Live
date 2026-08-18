from __future__ import annotations

import json
import os
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


class WebullTradeEventsJournalError(
    RuntimeError
):
    pass


_ALLOWED_EVENT_FIELDS = {
    "kind",
    "account_id",
    "order_id",
    "client_order_id",
    "symbol",
    "side",
    "order_status",
    "scene_type",
    "qty",
    "filled_qty",
    "category",
    "order_type",
    "filled_price",
    "filled_time",
}

_REQUIRED_EVENT_FIELDS = {
    "kind",
    "account_id",
    "client_order_id",
    "symbol",
    "side",
    "order_status",
    "scene_type",
    "qty",
    "filled_qty",
}


def _required_text(
    event: dict[str, Any],
    field: str,
) -> str:
    value = event.get(
        field
    )

    if (
        not isinstance(
            value,
            str,
        )
        or not value.strip()
    ):
        raise WebullTradeEventsJournalError(
            f"TRADE_EVENTS_JOURNAL_{field.upper()}_INVALID"
        )

    return value.strip()


def _decimal_text(
    event: dict[str, Any],
    field: str,
    *,
    minimum: Decimal,
) -> Decimal:
    text = _required_text(
        event,
        field,
    )

    try:
        value = Decimal(
            text
        )
    except (
        InvalidOperation,
        ValueError,
    ) as error:
        raise WebullTradeEventsJournalError(
            f"TRADE_EVENTS_JOURNAL_{field.upper()}_INVALID"
        ) from error

    if (
        not value.is_finite()
        or value < minimum
    ):
        raise WebullTradeEventsJournalError(
            f"TRADE_EVENTS_JOURNAL_{field.upper()}_INVALID"
        )

    return value


def validate_persisted_trade_event(
    event: Any,
) -> dict[str, Any]:
    if not isinstance(
        event,
        dict,
    ):
        raise WebullTradeEventsJournalError(
            "TRADE_EVENTS_JOURNAL_EVENT_INVALID"
        )

    unknown = (
        set(
            event
        )
        - _ALLOWED_EVENT_FIELDS
    )

    if unknown:
        raise WebullTradeEventsJournalError(
            "TRADE_EVENTS_JOURNAL_UNKNOWN_FIELD"
        )

    missing = (
        _REQUIRED_EVENT_FIELDS
        - set(
            event
        )
    )

    if missing:
        raise WebullTradeEventsJournalError(
            "TRADE_EVENTS_JOURNAL_REQUIRED_FIELD_MISSING"
        )

    if (
        _required_text(
            event,
            "kind",
        )
        != "ORDER_STATUS_CHANGED"
    ):
        raise WebullTradeEventsJournalError(
            "TRADE_EVENTS_JOURNAL_KIND_INVALID"
        )

    _required_text(
        event,
        "account_id",
    )

    _required_text(
        event,
        "client_order_id",
    )

    _required_text(
        event,
        "symbol",
    )

    side = _required_text(
        event,
        "side",
    ).upper()

    if side not in {
        "BUY",
        "SELL",
    }:
        raise WebullTradeEventsJournalError(
            "TRADE_EVENTS_JOURNAL_SIDE_INVALID"
        )

    _required_text(
        event,
        "order_status",
    )

    _required_text(
        event,
        "scene_type",
    )

    quantity = _decimal_text(
        event,
        "qty",
        minimum=Decimal(
            "0.0000000001"
        ),
    )

    filled_quantity = (
        _decimal_text(
            event,
            "filled_qty",
            minimum=Decimal(
                "0"
            ),
        )
    )

    if (
        filled_quantity
        > quantity
    ):
        raise WebullTradeEventsJournalError(
            "TRADE_EVENTS_JOURNAL_FILLED_QTY_EXCEEDS_QTY"
        )

    if filled_quantity > 0:
        filled_price = (
            _decimal_text(
                event,
                "filled_price",
                minimum=Decimal(
                    "0.0000000001"
                ),
            )
        )

        if filled_price <= 0:
            raise WebullTradeEventsJournalError(
                "TRADE_EVENTS_JOURNAL_FILLED_PRICE_INVALID"
            )

        _required_text(
            event,
            "filled_time",
        )

    for field in (
        "order_id",
        "category",
        "order_type",
        "filled_time",
    ):
        if field not in event:
            continue

        value = event[
            field
        ]

        if (
            value is not None
            and (
                not isinstance(
                    value,
                    str,
                )
                or not value.strip()
            )
        ):
            raise WebullTradeEventsJournalError(
                f"TRADE_EVENTS_JOURNAL_{field.upper()}_INVALID"
            )

    if (
        "filled_price"
        in event
        and filled_quantity == 0
    ):
        _decimal_text(
            event,
            "filled_price",
            minimum=Decimal(
                "0"
            ),
        )

    return dict(
        event
    )


def _event_identity(
    event: dict[str, Any],
) -> tuple[str, ...]:
    return (
        str(
            event.get(
                "account_id",
                "",
            )
        ),
        str(
            event.get(
                "client_order_id",
                "",
            )
        ),
        str(
            event.get(
                "scene_type",
                "",
            )
        ),
        str(
            event.get(
                "order_status",
                "",
            )
        ),
        str(
            event.get(
                "qty",
                "",
            )
        ),
        str(
            event.get(
                "filled_qty",
                "",
            )
        ),
        str(
            event.get(
                "filled_time",
                "",
            )
        ),
        str(
            event.get(
                "order_type",
                "",
            )
        ),
    )


def _canonical_event(
    event: dict[str, Any],
) -> str:
    return json.dumps(
        event,
        sort_keys=True,
        separators=(
            ",",
            ":",
        ),
        ensure_ascii=True,
    )


class WebullTradeEventsJournal:
    """
    Durable parent-side journal for sanitized Trade Events.

    An event is fsync'd before append() returns True.

    Exact repeated events are ignored.

    If the same event identity appears with conflicting
    contents, the journal fails closed rather than choosing
    one version.

    Existing journal contents are strictly revalidated during
    startup.
    """

    def __init__(
        self,
        *,
        path: str | Path,
    ) -> None:
        self.path = Path(
            path
        )

        self._events_by_identity: dict[
            tuple[str, ...],
            str,
        ] = {}

        self._load_existing()

    def _load_existing(
        self,
    ) -> None:
        if not self.path.exists():
            return

        try:
            lines = (
                self.path.read_text(
                    encoding="utf-8"
                )
                .splitlines()
            )
        except Exception as error:
            raise WebullTradeEventsJournalError(
                "TRADE_EVENTS_JOURNAL_READ_FAILED"
            ) from error

        for line_number, line in enumerate(
            lines,
            start=1,
        ):
            if not line.strip():
                raise WebullTradeEventsJournalError(
                    "TRADE_EVENTS_JOURNAL_EMPTY_RECORD"
                )

            try:
                record = json.loads(
                    line
                )
            except Exception as error:
                raise WebullTradeEventsJournalError(
                    "TRADE_EVENTS_JOURNAL_JSON_INVALID"
                ) from error

            if (
                not isinstance(
                    record,
                    dict,
                )
                or set(
                    record
                )
                != {
                    "record_type",
                    "event",
                }
                or record.get(
                    "record_type"
                )
                != "ORDER_EVENT"
            ):
                raise WebullTradeEventsJournalError(
                    "TRADE_EVENTS_JOURNAL_RECORD_INVALID"
                )

            try:
                event = (
                    validate_persisted_trade_event(
                        record.get(
                            "event"
                        )
                    )
                )
            except WebullTradeEventsJournalError as error:
                raise WebullTradeEventsJournalError(
                    f"TRADE_EVENTS_JOURNAL_RECORD_INVALID_LINE_{line_number}"
                ) from error

            self._index_event(
                event
            )

    def _index_event(
        self,
        event: dict[str, Any],
    ) -> bool:
        identity = _event_identity(
            event
        )

        canonical = _canonical_event(
            event
        )

        previous = (
            self._events_by_identity.get(
                identity
            )
        )

        if previous is None:
            self._events_by_identity[
                identity
            ] = canonical

            return True

        if previous == canonical:
            return False

        raise WebullTradeEventsJournalError(
            "TRADE_EVENTS_JOURNAL_DUPLICATE_CONFLICT"
        )

    def _persist_record(
        self,
        event: dict[str, Any],
    ) -> None:
        record = {
            "record_type": (
                "ORDER_EVENT"
            ),
            "event": event,
        }

        encoded = (
            json.dumps(
                record,
                sort_keys=True,
                separators=(
                    ",",
                    ":",
                ),
                ensure_ascii=True,
            )
            + "\n"
        )

        try:
            self.path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            with self.path.open(
                "a",
                encoding="utf-8",
            ) as handle:
                handle.write(
                    encoded
                )

                handle.flush()

                os.fsync(
                    handle.fileno()
                )
        except Exception as error:
            raise WebullTradeEventsJournalError(
                "TRADE_EVENTS_JOURNAL_WRITE_FAILED"
            ) from error

    def append(
        self,
        event: Any,
    ) -> bool:
        validated = (
            validate_persisted_trade_event(
                event
            )
        )

        identity = (
            _event_identity(
                validated
            )
        )

        canonical = (
            _canonical_event(
                validated
            )
        )

        previous = (
            self._events_by_identity.get(
                identity
            )
        )

        if previous is not None:
            if previous == canonical:
                return False

            raise WebullTradeEventsJournalError(
                "TRADE_EVENTS_JOURNAL_DUPLICATE_CONFLICT"
            )

        self._persist_record(
            validated
        )

        self._events_by_identity[
            identity
        ] = canonical

        return True

    def event_count(
        self,
    ) -> int:
        return len(
            self._events_by_identity
        )


class WebullTradeEventsHealthState:
    """
    Parent-side trust state for the Trade Events stream.

    CONNECTED alone never makes the stream trusted.

    Every startup, restart, disconnect, or fatal condition
    requires explicit broker reconciliation before the stream
    becomes trusted again.
    """

    def __init__(
        self,
    ) -> None:
        self.connected = False
        self.reconciliation_required = True
        self.fatal_reason: str | None = None

    @property
    def trusted(
        self,
    ) -> bool:
        return bool(
            self.connected
            and not self.reconciliation_required
            and self.fatal_reason is None
        )

    def handle_control(
        self,
        message: Any,
    ) -> None:
        if not isinstance(
            message,
            dict,
        ):
            raise WebullTradeEventsJournalError(
                "TRADE_EVENTS_CONTROL_INVALID"
            )

        message_type = str(
            message.get(
                "type",
                "",
            )
        ).strip().upper()

        if message_type == "CONNECTED":
            if set(
                message
            ) != {
                "type",
            }:
                raise WebullTradeEventsJournalError(
                    "TRADE_EVENTS_CONNECTED_CONTROL_INVALID"
                )

            self.connected = True

            return

        if message_type == "FATAL":
            if set(
                message
            ) != {
                "type",
                "reason",
            }:
                raise WebullTradeEventsJournalError(
                    "TRADE_EVENTS_FATAL_CONTROL_INVALID"
                )

            reason = str(
                message.get(
                    "reason",
                    "",
                )
            ).strip()

            if not reason:
                raise WebullTradeEventsJournalError(
                    "TRADE_EVENTS_FATAL_REASON_REQUIRED"
                )

            self.connected = False
            self.reconciliation_required = True
            self.fatal_reason = (
                reason
            )

            return

        raise WebullTradeEventsJournalError(
            "TRADE_EVENTS_CONTROL_TYPE_UNSUPPORTED"
        )

    def mark_worker_lost(
        self,
        reason: str = (
            "TRADE_EVENTS_WORKER_NOT_RUNNING"
        ),
    ) -> None:
        reason = str(
            reason
        ).strip()

        if not reason:
            raise WebullTradeEventsJournalError(
                "TRADE_EVENTS_WORKER_LOSS_REASON_REQUIRED"
            )

        self.connected = False
        self.reconciliation_required = True
        self.fatal_reason = reason

    def mark_reconciled(
        self,
    ) -> None:
        if not self.connected:
            raise WebullTradeEventsJournalError(
                "TRADE_EVENTS_RECONCILE_REQUIRES_CONNECTION"
            )

        self.fatal_reason = None
        self.reconciliation_required = False
