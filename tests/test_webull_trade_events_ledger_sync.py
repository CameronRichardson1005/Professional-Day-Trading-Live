from types import SimpleNamespace

import pytest

from trading_bot.webull_trade_events_ledger_sync import (
    WebullTradeEventsLedgerSynchronizer,
    WebullTradeEventsLedgerSyncError,
)


ACCOUNT_ID = "sandbox-account"
CLIENT_ORDER_ID = "client-order-1"


def event(
    *,
    account_id=ACCOUNT_ID,
    client_order_id=CLIENT_ORDER_ID,
    symbol="AAPL",
    side="BUY",
    order_status="CANCELLED",
    scene_type="CANCEL_SUCCESS",
    qty="1.00",
    filled_qty="0.000",
    **extra,
):
    result = {
        "kind": "ORDER_STATUS_CHANGED",
        "account_id": account_id,
        "client_order_id": (
            client_order_id
        ),
        "symbol": symbol,
        "side": side,
        "order_status": order_status,
        "scene_type": scene_type,
        "qty": qty,
        "filled_qty": filled_qty,
    }

    result.update(
        extra
    )

    return result


def record(
    *,
    client_order_id=CLIENT_ORDER_ID,
    execution_mode="SANDBOX",
    symbol="AAPL",
    side="BUY",
):
    return SimpleNamespace(
        client_order_id=(
            client_order_id
        ),
        execution_mode=(
            execution_mode
        ),
        symbol=symbol,
        side=side,
    )


class FakeLedger:
    def __init__(
        self,
        *,
        records=None,
        error=None,
    ):
        self.records = (
            {}
            if records is None
            else records
        )

        self.error = error
        self.load_calls = 0

    def load(self):
        self.load_calls += 1

        if self.error is not None:
            raise self.error

        return self.records


def build_sync(
    *,
    ledger=None,
    reconcile=None,
):
    if ledger is None:
        ledger = FakeLedger(
            records={
                CLIENT_ORDER_ID: (
                    record()
                )
            }
        )

    if reconcile is None:
        def reconcile(
            *,
            client_order_id,
        ):
            return SimpleNamespace(
                client_order_id=(
                    client_order_id
                ),
                status="CANCELLED",
            )

    return (
        WebullTradeEventsLedgerSynchronizer(
            expected_account_id=(
                ACCOUNT_ID
            ),
            ledger=ledger,
            reconcile_order=reconcile,
        )
    )


def test_cancel_event_triggers_authoritative_reconcile():
    calls = []

    def reconcile(
        *,
        client_order_id,
    ):
        calls.append(
            client_order_id
        )

        return SimpleNamespace(
            client_order_id=(
                client_order_id
            ),
            status="CANCELLED",
        )

    sync = build_sync(
        reconcile=reconcile
    )

    result = sync(
        event()
    )

    assert calls == [
        CLIENT_ORDER_ID
    ]

    assert result.status == "CANCELLED"


def test_fill_event_triggers_authoritative_reconcile():
    calls = []

    def reconcile(
        *,
        client_order_id,
    ):
        calls.append(
            client_order_id
        )

        return SimpleNamespace(
            client_order_id=(
                client_order_id
            ),
            status="FILLED",
        )

    sync = build_sync(
        reconcile=reconcile
    )

    result = sync(
        event(
            order_status="FILLED",
            scene_type="FINAL_FILLED",
            filled_qty="1.00",
            filled_price="300.12",
            filled_time=(
                "2026-08-18T14:00:00Z"
            ),
        )
    )

    assert calls == [
        CLIENT_ORDER_ID
    ]

    assert result.status == "FILLED"


def test_invalid_event_fails_before_reconcile():
    calls = []

    def reconcile(
        *,
        client_order_id,
    ):
        calls.append(
            client_order_id
        )

    sync = build_sync(
        reconcile=reconcile
    )

    with pytest.raises(
        WebullTradeEventsLedgerSyncError,
        match=(
            "^TRADE_EVENTS_LEDGER_EVENT_INVALID$"
        ),
    ):
        sync(
            event(
                qty="0",
            )
        )

    assert calls == []


def test_account_mismatch_fails_closed():
    sync = build_sync()

    with pytest.raises(
        WebullTradeEventsLedgerSyncError,
        match=(
            "^TRADE_EVENTS_LEDGER_ACCOUNT_MISMATCH$"
        ),
    ):
        sync(
            event(
                account_id="other-account"
            )
        )


def test_unknown_local_order_fails_closed():
    ledger = FakeLedger(
        records={}
    )

    sync = build_sync(
        ledger=ledger
    )

    with pytest.raises(
        WebullTradeEventsLedgerSyncError,
        match=(
            "^TRADE_EVENTS_LEDGER_ORDER_NOT_FOUND$"
        ),
    ):
        sync(
            event()
        )


def test_non_sandbox_local_order_fails_closed():
    ledger = FakeLedger(
        records={
            CLIENT_ORDER_ID: record(
                execution_mode="LIVE"
            )
        }
    )

    sync = build_sync(
        ledger=ledger
    )

    with pytest.raises(
        WebullTradeEventsLedgerSyncError,
        match=(
            "^TRADE_EVENTS_LEDGER_MODE_MISMATCH$"
        ),
    ):
        sync(
            event()
        )


def test_symbol_mismatch_fails_closed():
    ledger = FakeLedger(
        records={
            CLIENT_ORDER_ID: record(
                symbol="MSFT"
            )
        }
    )

    sync = build_sync(
        ledger=ledger
    )

    with pytest.raises(
        WebullTradeEventsLedgerSyncError,
        match=(
            "^TRADE_EVENTS_LEDGER_SYMBOL_MISMATCH$"
        ),
    ):
        sync(
            event()
        )


def test_side_mismatch_fails_closed():
    ledger = FakeLedger(
        records={
            CLIENT_ORDER_ID: record(
                side="SELL"
            )
        }
    )

    sync = build_sync(
        ledger=ledger
    )

    with pytest.raises(
        WebullTradeEventsLedgerSyncError,
        match=(
            "^TRADE_EVENTS_LEDGER_SIDE_MISMATCH$"
        ),
    ):
        sync(
            event()
        )


def test_ledger_load_failure_is_sanitized():
    ledger = FakeLedger(
        error=RuntimeError(
            "secret transport detail"
        )
    )

    sync = build_sync(
        ledger=ledger
    )

    with pytest.raises(
        WebullTradeEventsLedgerSyncError,
        match=(
            "^TRADE_EVENTS_LEDGER_LOAD_FAILED$"
        ),
    ) as captured:
        sync(
            event()
        )

    assert (
        "secret transport detail"
        not in str(
            captured.value
        )
    )


def test_reconcile_failure_is_sanitized():
    def reconcile(
        *,
        client_order_id,
    ):
        del client_order_id

        raise RuntimeError(
            "secret broker detail"
        )

    sync = build_sync(
        reconcile=reconcile
    )

    with pytest.raises(
        WebullTradeEventsLedgerSyncError,
        match=(
            "^TRADE_EVENTS_LEDGER_RECONCILE_FAILED$"
        ),
    ) as captured:
        sync(
            event()
        )

    assert (
        "secret broker detail"
        not in str(
            captured.value
        )
    )


def test_reconcile_result_must_match_client_order_id():
    def reconcile(
        *,
        client_order_id,
    ):
        del client_order_id

        return SimpleNamespace(
            client_order_id=(
                "different-order"
            ),
            status="CANCELLED",
        )

    sync = build_sync(
        reconcile=reconcile
    )

    with pytest.raises(
        WebullTradeEventsLedgerSyncError,
        match=(
            "^TRADE_EVENTS_LEDGER_RECONCILE_ID_MISMATCH$"
        ),
    ):
        sync(
            event()
        )
