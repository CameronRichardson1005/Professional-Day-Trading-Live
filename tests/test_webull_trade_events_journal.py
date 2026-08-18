import json

import pytest

from trading_bot.webull_trade_events_journal import (
    WebullTradeEventsHealthState,
    WebullTradeEventsJournal,
    WebullTradeEventsJournalError,
)


def event():
    return {
        "kind": "ORDER_STATUS_CHANGED",
        "account_id": "sandbox-1",
        "order_id": "broker-1",
        "client_order_id": "client-1",
        "symbol": "SOUN",
        "side": "BUY",
        "order_status": "PARTIAL_FILLED",
        "scene_type": "FILLED",
        "qty": "2",
        "filled_qty": "1",
        "category": "US_STOCK",
        "order_type": "LIMIT",
        "filled_price": "4.25",
        "filled_time": (
            "2026-08-18T13:31:00.000Z"
        ),
    }


def test_new_event_is_durably_written(
    tmp_path,
):
    path = (
        tmp_path
        / "events.jsonl"
    )

    journal = (
        WebullTradeEventsJournal(
            path=path
        )
    )

    assert (
        journal.append(
            event()
        )
        is True
    )

    lines = (
        path.read_text(
            encoding="utf-8"
        )
        .splitlines()
    )

    assert len(
        lines
    ) == 1

    record = json.loads(
        lines[0]
    )

    assert (
        record["record_type"]
        == "ORDER_EVENT"
    )

    assert (
        record[
            "event"
        ][
            "client_order_id"
        ]
        == "client-1"
    )


def test_exact_duplicate_is_not_written_twice(
    tmp_path,
):
    path = (
        tmp_path
        / "events.jsonl"
    )

    journal = (
        WebullTradeEventsJournal(
            path=path
        )
    )

    assert journal.append(
        event()
    )

    assert (
        journal.append(
            event()
        )
        is False
    )

    assert len(
        path.read_text(
            encoding="utf-8"
        ).splitlines()
    ) == 1


def test_conflicting_duplicate_fails_closed(
    tmp_path,
):
    journal = (
        WebullTradeEventsJournal(
            path=(
                tmp_path
                / "events.jsonl"
            )
        )
    )

    original = event()

    journal.append(
        original
    )

    conflicting = dict(
        original
    )

    conflicting[
        "symbol"
    ] = "BBAI"

    with pytest.raises(
        WebullTradeEventsJournalError,
        match=(
            "TRADE_EVENTS_JOURNAL_DUPLICATE_CONFLICT"
        ),
    ):
        journal.append(
            conflicting
        )


def test_unknown_field_is_rejected(
    tmp_path,
):
    journal = (
        WebullTradeEventsJournal(
            path=(
                tmp_path
                / "events.jsonl"
            )
        )
    )

    unsafe = event()

    unsafe[
        "signature"
    ] = "must-not-persist"

    with pytest.raises(
        WebullTradeEventsJournalError,
        match=(
            "TRADE_EVENTS_JOURNAL_UNKNOWN_FIELD"
        ),
    ):
        journal.append(
            unsafe
        )


def test_filled_quantity_cannot_exceed_order_quantity(
    tmp_path,
):
    journal = (
        WebullTradeEventsJournal(
            path=(
                tmp_path
                / "events.jsonl"
            )
        )
    )

    invalid = event()

    invalid[
        "filled_qty"
    ] = "3"

    with pytest.raises(
        WebullTradeEventsJournalError,
        match=(
            "TRADE_EVENTS_JOURNAL_FILLED_QTY_EXCEEDS_QTY"
        ),
    ):
        journal.append(
            invalid
        )


def test_malformed_existing_journal_fails_closed(
    tmp_path,
):
    path = (
        tmp_path
        / "events.jsonl"
    )

    path.write_text(
        "{not-json}\n",
        encoding="utf-8",
    )

    with pytest.raises(
        WebullTradeEventsJournalError,
        match=(
            "TRADE_EVENTS_JOURNAL_JSON_INVALID"
        ),
    ):
        WebullTradeEventsJournal(
            path=path
        )


def test_restart_reloads_duplicate_index(
    tmp_path,
):
    path = (
        tmp_path
        / "events.jsonl"
    )

    first = (
        WebullTradeEventsJournal(
            path=path
        )
    )

    first.append(
        event()
    )

    restarted = (
        WebullTradeEventsJournal(
            path=path
        )
    )

    assert (
        restarted.event_count()
        == 1
    )

    assert (
        restarted.append(
            event()
        )
        is False
    )


def test_failed_write_does_not_commit_memory_state(
    tmp_path,
    monkeypatch,
):
    journal = (
        WebullTradeEventsJournal(
            path=(
                tmp_path
                / "events.jsonl"
            )
        )
    )

    original_persist = (
        journal._persist_record
    )

    def fail_write(
        persisted_event,
    ):
        del persisted_event

        raise WebullTradeEventsJournalError(
            "TRADE_EVENTS_JOURNAL_WRITE_FAILED"
        )

    monkeypatch.setattr(
        journal,
        "_persist_record",
        fail_write,
    )

    with pytest.raises(
        WebullTradeEventsJournalError,
        match=(
            "TRADE_EVENTS_JOURNAL_WRITE_FAILED"
        ),
    ):
        journal.append(
            event()
        )

    assert (
        journal.event_count()
        == 0
    )

    monkeypatch.setattr(
        journal,
        "_persist_record",
        original_persist,
    )

    assert (
        journal.append(
            event()
        )
        is True
    )


def test_connected_alone_is_not_trusted():
    health = (
        WebullTradeEventsHealthState()
    )

    health.handle_control({
        "type": "CONNECTED",
    })

    assert health.connected is True

    assert (
        health.reconciliation_required
        is True
    )

    assert health.trusted is False


def test_reconcile_requires_live_connection():
    health = (
        WebullTradeEventsHealthState()
    )

    with pytest.raises(
        WebullTradeEventsJournalError,
        match=(
            "TRADE_EVENTS_RECONCILE_REQUIRES_CONNECTION"
        ),
    ):
        health.mark_reconciled()


def test_connected_then_reconciled_becomes_trusted():
    health = (
        WebullTradeEventsHealthState()
    )

    health.handle_control({
        "type": "CONNECTED",
    })

    health.mark_reconciled()

    assert health.trusted is True

    assert (
        health.reconciliation_required
        is False
    )

    assert health.fatal_reason is None


def test_fatal_control_immediately_removes_trust():
    health = (
        WebullTradeEventsHealthState()
    )

    health.handle_control({
        "type": "CONNECTED",
    })

    health.mark_reconciled()

    assert health.trusted

    health.handle_control({
        "type": "FATAL",
        "reason": (
            "TRADE_EVENTS_STREAM_FAILED"
        ),
    })

    assert health.connected is False

    assert (
        health.reconciliation_required
        is True
    )

    assert health.trusted is False

    assert (
        health.fatal_reason
        == "TRADE_EVENTS_STREAM_FAILED"
    )


def test_reconnect_after_failure_still_requires_reconciliation():
    health = (
        WebullTradeEventsHealthState()
    )

    health.handle_control({
        "type": "CONNECTED",
    })

    health.mark_reconciled()

    health.handle_control({
        "type": "FATAL",
        "reason": (
            "TRADE_EVENTS_STREAM_FAILED"
        ),
    })

    health.handle_control({
        "type": "CONNECTED",
    })

    assert health.connected is True
    assert health.trusted is False

    assert (
        health.reconciliation_required
        is True
    )

    health.mark_reconciled()

    assert health.trusted is True
