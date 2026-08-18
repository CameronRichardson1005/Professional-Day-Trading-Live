from queue import Queue

import pytest

from trading_bot.webull_trade_events_journal import (
    WebullTradeEventsJournal,
)
from trading_bot.webull_trade_events_parent import (
    WebullTradeEventsParentController,
    WebullTradeEventsParentError,
)


def valid_event():
    return {
        "kind": "ORDER_STATUS_CHANGED",
        "account_id": "sandbox-1",
        "order_id": "broker-1",
        "client_order_id": "client-1",
        "symbol": "SOUN",
        "side": "BUY",
        "order_status": "FILLED",
        "scene_type": "FILLED",
        "qty": "1",
        "filled_qty": "1",
        "filled_price": "5.25",
        "filled_time": (
            "2026-08-18T13:35:00Z"
        ),
    }


def make_controller(
    tmp_path,
    *,
    reconcile=None,
    handler=None,
    health_check=None,
):
    events = Queue()
    control = Queue()

    journal = WebullTradeEventsJournal(
        path=tmp_path / "events.jsonl",
    )

    reconcile_calls = []

    if reconcile is None:
        def reconcile():
            reconcile_calls.append(
                True
            )

    controller = (
        WebullTradeEventsParentController(
            event_queue=events,
            control_queue=control,
            journal=journal,
            reconcile=reconcile,
            event_handler=handler,
            ensure_worker_healthy=(
                health_check
            ),
        )
    )

    return (
        controller,
        events,
        control,
        journal,
        reconcile_calls,
    )


def test_connected_requires_reconciliation_before_trust(
    tmp_path,
):
    (
        controller,
        _,
        control,
        _,
        reconcile_calls,
    ) = make_controller(
        tmp_path
    )

    assert controller.health.trusted is False

    control.put_nowait({
        "type": "CONNECTED",
    })

    result = controller.poll_once()

    assert reconcile_calls == [True]
    assert result.control_messages == 1
    assert result.trusted is True
    assert controller.health.trusted is True


def test_failed_reconciliation_remains_untrusted(
    tmp_path,
):
    def fail_reconcile():
        raise RuntimeError(
            "broker unavailable"
        )

    (
        controller,
        _,
        control,
        _,
        _,
    ) = make_controller(
        tmp_path,
        reconcile=fail_reconcile,
    )

    control.put_nowait({
        "type": "CONNECTED",
    })

    with pytest.raises(
        WebullTradeEventsParentError,
        match=(
            "TRADE_EVENTS_RECONCILIATION_FAILED"
        ),
    ):
        controller.poll_once()

    assert controller.health.trusted is False
    assert controller.health.connected is True
    assert (
        controller.health
        .reconciliation_required
        is True
    )


def test_event_is_journaled_before_handler(
    tmp_path,
):
    observed_counts = []

    journal_holder = {}

    def handler(event):
        del event

        observed_counts.append(
            journal_holder[
                "journal"
            ].event_count()
        )

    (
        controller,
        events,
        control,
        journal,
        _,
    ) = make_controller(
        tmp_path,
        handler=handler,
    )

    journal_holder[
        "journal"
    ] = journal

    control.put_nowait({
        "type": "CONNECTED",
    })

    events.put_nowait(
        valid_event()
    )

    result = controller.poll_once()

    assert observed_counts == [1]
    assert result.journaled_events == 1
    assert result.dispatched_events == 1
    assert journal.event_count() == 1

    contents = (
        (tmp_path / "events.jsonl")
        .read_text(
            encoding="utf-8"
        )
    )

    assert "client-1" in contents


def test_exact_duplicate_is_not_dispatched_twice(
    tmp_path,
):
    handled = []

    def handler(event):
        handled.append(
            event[
                "client_order_id"
            ]
        )

    (
        controller,
        events,
        control,
        journal,
        _,
    ) = make_controller(
        tmp_path,
        handler=handler,
    )

    control.put_nowait({
        "type": "CONNECTED",
    })

    event = valid_event()

    events.put_nowait(event)
    events.put_nowait(dict(event))

    result = controller.poll_once()

    assert handled == ["client-1"]
    assert journal.event_count() == 1
    assert result.journaled_events == 1
    assert result.duplicate_events == 1
    assert result.dispatched_events == 1


def test_fatal_stream_still_journals_but_does_not_dispatch(
    tmp_path,
):
    handled = []

    (
        controller,
        events,
        control,
        journal,
        _,
    ) = make_controller(
        tmp_path,
        handler=lambda event: (
            handled.append(event)
        ),
    )

    control.put_nowait({
        "type": "FATAL",
        "reason": "simulated failure",
    })

    events.put_nowait(
        valid_event()
    )

    result = controller.poll_once()

    assert result.trusted is False
    assert result.journaled_events == 1
    assert result.dispatched_events == 0
    assert journal.event_count() == 1
    assert handled == []


def test_journal_failure_revokes_trust(
    tmp_path,
):
    (
        controller,
        events,
        control,
        _,
        _,
    ) = make_controller(
        tmp_path
    )

    control.put_nowait({
        "type": "CONNECTED",
    })

    controller.poll_once()

    assert controller.health.trusted is True

    bad = valid_event()
    bad[
        "unknown_field"
    ] = "not allowed"

    events.put_nowait(
        bad
    )

    with pytest.raises(
        WebullTradeEventsParentError,
        match="TRADE_EVENTS_JOURNAL_FAILED",
    ):
        controller.poll_once()

    assert controller.health.trusted is False

    assert (
        controller.health.fatal_reason
        == "TRADE_EVENTS_JOURNAL_FAILED"
    )


def test_worker_health_failure_revokes_trust(
    tmp_path,
):
    state = {
        "healthy": True,
    }

    def health_check():
        if not state[
            "healthy"
        ]:
            raise RuntimeError(
                "worker gone"
            )

    (
        controller,
        _,
        control,
        _,
        _,
    ) = make_controller(
        tmp_path,
        health_check=health_check,
    )

    control.put_nowait({
        "type": "CONNECTED",
    })

    controller.poll_once()

    assert controller.health.trusted is True

    state[
        "healthy"
    ] = False

    with pytest.raises(
        WebullTradeEventsParentError,
        match=(
            "TRADE_EVENTS_WORKER_NOT_HEALTHY"
        ),
    ):
        controller.poll_once()

    assert controller.health.trusted is False

    assert (
        controller.health.fatal_reason
        == "TRADE_EVENTS_WORKER_NOT_HEALTHY"
    )


def test_fatal_control_reason_wins_over_dead_worker(
    tmp_path,
):
    def dead_worker_check():
        raise RuntimeError(
            "worker already exited"
        )

    (
        controller,
        _,
        control,
        _,
        _,
    ) = make_controller(
        tmp_path,
        health_check=dead_worker_check,
    )

    control.put_nowait({
        "type": "FATAL",
        "reason": "TRADE_EVENTS_STREAM_FAILED",
    })

    result = controller.poll_once()

    assert result.trusted is False
    assert result.control_messages == 1

    assert (
        controller.health.fatal_reason
        == "TRADE_EVENTS_STREAM_FAILED"
    )
