from __future__ import annotations

from typing import Any, Callable

from .webull_trade_events_journal import (
    WebullTradeEventsJournalError,
    validate_persisted_trade_event,
)


class WebullTradeEventsLedgerSyncError(
    RuntimeError
):
    pass


class WebullTradeEventsLedgerSynchronizer:
    """
    Convert a trusted Trade Events notification into an
    authoritative read-only broker reconciliation.

    The Trade Event itself is NOT treated as the source of
    execution truth.

    Ordering is deliberately:

        Webull event
            -> worker sanitization
            -> durable parent journal + fsync
            -> trusted handler
            -> read-only broker reconciliation
            -> execution ledger

    No placement, replacement, cancellation, or close operation
    is exposed by this class.
    """

    def __init__(
        self,
        *,
        expected_account_id: str,
        ledger: Any,
        reconcile_order: Callable[..., Any],
    ) -> None:
        account_id = str(
            expected_account_id
        ).strip()

        if not account_id:
            raise WebullTradeEventsLedgerSyncError(
                "TRADE_EVENTS_LEDGER_ACCOUNT_ID_REQUIRED"
            )

        if not callable(
            getattr(
                ledger,
                "load",
                None,
            )
        ):
            raise WebullTradeEventsLedgerSyncError(
                "TRADE_EVENTS_LEDGER_INVALID"
            )

        if not callable(
            reconcile_order
        ):
            raise WebullTradeEventsLedgerSyncError(
                "TRADE_EVENTS_LEDGER_RECONCILE_INVALID"
            )

        self.expected_account_id = (
            account_id
        )

        self.ledger = ledger

        self.reconcile_order = (
            reconcile_order
        )

    def __call__(
        self,
        event: Any,
    ) -> Any:
        try:
            validated = (
                validate_persisted_trade_event(
                    event
                )
            )
        except WebullTradeEventsJournalError as error:
            raise WebullTradeEventsLedgerSyncError(
                "TRADE_EVENTS_LEDGER_EVENT_INVALID"
            ) from error

        account_id = str(
            validated[
                "account_id"
            ]
        ).strip()

        if (
            account_id
            != self.expected_account_id
        ):
            raise WebullTradeEventsLedgerSyncError(
                "TRADE_EVENTS_LEDGER_ACCOUNT_MISMATCH"
            )

        client_order_id = str(
            validated[
                "client_order_id"
            ]
        ).strip()

        try:
            records = self.ledger.load()
        except Exception as error:
            raise WebullTradeEventsLedgerSyncError(
                "TRADE_EVENTS_LEDGER_LOAD_FAILED"
            ) from error

        if not isinstance(
            records,
            dict,
        ):
            raise WebullTradeEventsLedgerSyncError(
                "TRADE_EVENTS_LEDGER_LOAD_INVALID"
            )

        record = records.get(
            client_order_id
        )

        if record is None:
            raise WebullTradeEventsLedgerSyncError(
                "TRADE_EVENTS_LEDGER_ORDER_NOT_FOUND"
            )

        execution_mode = str(
            getattr(
                record,
                "execution_mode",
                "",
            )
        ).strip().upper()

        if execution_mode != "SANDBOX":
            raise WebullTradeEventsLedgerSyncError(
                "TRADE_EVENTS_LEDGER_MODE_MISMATCH"
            )

        local_symbol = str(
            getattr(
                record,
                "symbol",
                "",
            )
        ).strip().upper()

        event_symbol = str(
            validated[
                "symbol"
            ]
        ).strip().upper()

        if (
            not local_symbol
            or event_symbol
            != local_symbol
        ):
            raise WebullTradeEventsLedgerSyncError(
                "TRADE_EVENTS_LEDGER_SYMBOL_MISMATCH"
            )

        local_side = str(
            getattr(
                record,
                "side",
                "",
            )
        ).strip().upper()

        event_side = str(
            validated[
                "side"
            ]
        ).strip().upper()

        if (
            not local_side
            or event_side
            != local_side
        ):
            raise WebullTradeEventsLedgerSyncError(
                "TRADE_EVENTS_LEDGER_SIDE_MISMATCH"
            )

        # Quantity and price are deliberately not copied from the
        # event. They may legitimately change after a replacement.
        #
        # client_order_id is used to ask Webull for the current
        # authoritative state instead.
        try:
            result = self.reconcile_order(
                client_order_id=(
                    client_order_id
                ),
            )
        except Exception as error:
            raise WebullTradeEventsLedgerSyncError(
                "TRADE_EVENTS_LEDGER_RECONCILE_FAILED"
            ) from error

        reconciled_client_order_id = str(
            getattr(
                result,
                "client_order_id",
                "",
            )
        ).strip()

        if (
            reconciled_client_order_id
            != client_order_id
        ):
            raise WebullTradeEventsLedgerSyncError(
                "TRADE_EVENTS_LEDGER_RECONCILE_ID_MISMATCH"
            )

        return result
