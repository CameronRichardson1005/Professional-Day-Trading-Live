from datetime import UTC, datetime, timedelta

from trading_bot.webull_paper_lifecycle import (
    WebullPaperLifecycleTracker,
)
from trading_bot.webull_paper_order_store import (
    WebullPaperOrderRecord,
    WebullPaperOrderStore,
)


def make_order(
    *,
    submitted_at=None,
):
    submitted_at = (
        submitted_at
        or datetime(
            2026,
            8,
            7,
            14,
            0,
            tzinfo=UTC,
        )
    )

    return WebullPaperOrderRecord(
        paper_order_id="paper-1",
        approval_reference="approval-1",
        idempotency_key="idem-1",
        symbol="OPEN",
        side="BUY",
        quantity=10,
        limit_price=4.25,
        proposed_exposure=42.50,
        status="PAPER SUBMITTED",
        created_at=submitted_at,
        submitted_at=submitted_at,
        safety_reason="APPROVED",
        target_price=4.60,
        stop_price=4.10,
    )


def bar(
    minute,
    *,
    high,
    low,
    close=None,
):
    return {
        "t": (
            datetime(
                2026,
                8,
                7,
                14,
                minute,
                tzinfo=UTC,
            )
            .isoformat()
            .replace("+00:00", "Z")
        ),
        "o": 4.20,
        "h": high,
        "l": low,
        "c": (
            close
            if close is not None
            else high
        ),
        "v": 1000,
    }


def setup_tracker(tmp_path):
    store = WebullPaperOrderStore(
        tmp_path / "paper-orders.json"
    )
    store.add(make_order())

    return (
        store,
        WebullPaperLifecycleTracker(
            store=store
        ),
    )


def test_entry_remains_pending_until_high_reaches_entry(
    tmp_path,
):
    store, tracker = setup_tracker(tmp_path)

    tracker.process_bars(
        bars_by_symbol={
            "OPEN": [
                bar(
                    1,
                    high=4.24,
                    low=4.15,
                )
            ]
        }
    )

    record = store.load()["paper-1"]

    assert record.lifecycle_status == "ENTRY PENDING"
    assert record.filled_at is None


def test_entry_high_reaching_limit_opens_trade(
    tmp_path,
):
    store, tracker = setup_tracker(tmp_path)

    tracker.process_bars(
        bars_by_symbol={
            "OPEN": [
                bar(
                    1,
                    high=4.30,
                    low=4.20,
                )
            ]
        }
    )

    record = store.load()["paper-1"]

    assert record.lifecycle_status == "OPEN"
    assert record.fill_price == 4.25
    assert record.filled_at is not None
    assert record.highest_price == 4.30
    assert record.lowest_price == 4.20
    assert record.mfe_pct is not None
    assert record.mae_pct is not None


def test_target_closes_trade_and_calculates_pnl(
    tmp_path,
):
    store, tracker = setup_tracker(tmp_path)

    tracker.process_bars(
        bars_by_symbol={
            "OPEN": [
                bar(
                    1,
                    high=4.30,
                    low=4.20,
                ),
                bar(
                    2,
                    high=4.62,
                    low=4.28,
                ),
            ]
        }
    )

    record = store.load()["paper-1"]

    assert record.lifecycle_status == "CLOSED"
    assert record.exit_reason == "TARGET"
    assert record.exit_price == 4.60
    assert record.realized_pnl == 3.50
    assert record.return_pct == round(
        (4.60 - 4.25) / 4.25 * 100,
        6,
    )


def test_stop_closes_trade(
    tmp_path,
):
    store, tracker = setup_tracker(tmp_path)

    tracker.process_bars(
        bars_by_symbol={
            "OPEN": [
                bar(
                    1,
                    high=4.30,
                    low=4.20,
                ),
                bar(
                    2,
                    high=4.31,
                    low=4.08,
                ),
            ]
        }
    )

    record = store.load()["paper-1"]

    assert record.lifecycle_status == "CLOSED"
    assert record.exit_reason == "STOP"
    assert record.exit_price == 4.10
    assert record.realized_pnl == -1.50


def test_same_minute_stop_and_target_is_stop(
    tmp_path,
):
    store, tracker = setup_tracker(tmp_path)

    tracker.process_bars(
        bars_by_symbol={
            "OPEN": [
                bar(
                    1,
                    high=4.65,
                    low=4.05,
                )
            ]
        }
    )

    record = store.load()["paper-1"]

    assert record.lifecycle_status == "CLOSED"
    assert record.exit_reason == "STOP"
    assert record.exit_price == 4.10


def test_excursions_survive_restart(
    tmp_path,
):
    store, tracker = setup_tracker(tmp_path)

    tracker.process_bars(
        bars_by_symbol={
            "OPEN": [
                bar(
                    1,
                    high=4.35,
                    low=4.18,
                )
            ]
        }
    )

    restarted_store = WebullPaperOrderStore(
        store.path
    )
    restarted_tracker = (
        WebullPaperLifecycleTracker(
            store=restarted_store
        )
    )

    restarted_tracker.process_bars(
        bars_by_symbol={
            "OPEN": [
                bar(
                    2,
                    high=4.45,
                    low=4.15,
                )
            ]
        }
    )

    record = restarted_store.load()[
        "paper-1"
    ]

    assert record.lifecycle_status == "OPEN"
    assert record.highest_price == 4.45
    assert record.lowest_price == 4.15


def test_pre_submission_bars_are_ignored(
    tmp_path,
):
    submitted_at = datetime(
        2026,
        8,
        7,
        14,
        2,
        30,
        tzinfo=UTC,
    )

    store = WebullPaperOrderStore(
        tmp_path / "paper-orders.json"
    )

    store.add(
        make_order(
            submitted_at=submitted_at
        )
    )

    tracker = WebullPaperLifecycleTracker(
        store=store
    )

    tracker.process_bars(
        bars_by_symbol={
            "OPEN": [
                bar(
                    1,
                    high=4.70,
                    low=4.00,
                ),
                bar(
                    2,
                    high=4.70,
                    low=4.00,
                ),
            ]
        }
    )

    record = store.load()["paper-1"]

    assert record.lifecycle_status == "ENTRY PENDING"


def test_closed_trade_is_idempotent(
    tmp_path,
):
    store, tracker = setup_tracker(tmp_path)

    bars = {
        "OPEN": [
            bar(
                1,
                high=4.65,
                low=4.20,
            )
        ]
    }

    tracker.process_bars(
        bars_by_symbol=bars
    )

    first = store.load()["paper-1"]

    tracker.process_bars(
        bars_by_symbol=bars
    )

    second = store.load()["paper-1"]

    assert second == first
    assert second.lifecycle_status == "CLOSED"


def test_unfilled_order_expires_as_no_entry(
    tmp_path,
):
    store, tracker = setup_tracker(tmp_path)

    cutoff = datetime(
        2026,
        8,
        7,
        14,
        5,
        tzinfo=UTC,
    )

    tracker.finalize_at_cutoff(
        cutoff=cutoff,
        bars_by_symbol={
            "OPEN": [
                bar(
                    1,
                    high=4.24,
                    low=4.15,
                    close=4.20,
                )
            ]
        },
    )

    record = store.load()["paper-1"]

    assert record.lifecycle_status == "CLOSED"
    assert record.exit_reason == "NO ENTRY"
    assert record.closed_at == cutoff
    assert record.filled_at is None
    assert record.fill_price is None
    assert record.exit_price is None
    assert record.realized_pnl is None
    assert record.return_pct is None


def test_open_order_time_exits_at_last_completed_close(
    tmp_path,
):
    store, tracker = setup_tracker(tmp_path)

    cutoff = datetime(
        2026,
        8,
        7,
        14,
        5,
        tzinfo=UTC,
    )

    tracker.finalize_at_cutoff(
        cutoff=cutoff,
        bars_by_symbol={
            "OPEN": [
                bar(
                    1,
                    high=4.30,
                    low=4.20,
                    close=4.27,
                ),
                bar(
                    4,
                    high=4.40,
                    low=4.22,
                    close=4.35,
                ),
            ]
        },
    )

    record = store.load()["paper-1"]

    assert record.lifecycle_status == "CLOSED"
    assert record.exit_reason == "TIME EXIT"
    assert record.exit_price == 4.35
    assert record.closed_at == cutoff
    assert record.realized_pnl == 1.0
    assert record.return_pct == round(
        (4.35 - 4.25) / 4.25 * 100,
        6,
    )


def test_bar_at_cutoff_is_not_used(
    tmp_path,
):
    store, tracker = setup_tracker(tmp_path)

    cutoff = datetime(
        2026,
        8,
        7,
        14,
        5,
        tzinfo=UTC,
    )

    tracker.finalize_at_cutoff(
        cutoff=cutoff,
        bars_by_symbol={
            "OPEN": [
                bar(
                    4,
                    high=4.24,
                    low=4.15,
                    close=4.20,
                ),
                bar(
                    5,
                    high=4.70,
                    low=4.00,
                    close=4.60,
                ),
            ]
        },
    )

    record = store.load()["paper-1"]

    assert record.lifecycle_status == "CLOSED"
    assert record.exit_reason == "NO ENTRY"
    assert record.filled_at is None


def test_target_before_cutoff_beats_time_exit(
    tmp_path,
):
    store, tracker = setup_tracker(tmp_path)

    cutoff = datetime(
        2026,
        8,
        7,
        14,
        5,
        tzinfo=UTC,
    )

    tracker.finalize_at_cutoff(
        cutoff=cutoff,
        bars_by_symbol={
            "OPEN": [
                bar(
                    1,
                    high=4.30,
                    low=4.20,
                    close=4.27,
                ),
                bar(
                    3,
                    high=4.62,
                    low=4.30,
                    close=4.58,
                ),
            ]
        },
    )

    record = store.load()["paper-1"]

    assert record.lifecycle_status == "CLOSED"
    assert record.exit_reason == "TARGET"
    assert record.exit_price == 4.60


def test_open_trade_ignores_cached_bars_before_fill(
    tmp_path,
):
    store = WebullPaperOrderStore(
        tmp_path / "paper-orders.json"
    )

    submitted_at = datetime(
        2026,
        8,
        7,
        14,
        0,
        tzinfo=UTC,
    )
    filled_at = datetime(
        2026,
        8,
        7,
        14,
        3,
        tzinfo=UTC,
    )

    store.add(
        WebullPaperOrderRecord(
            paper_order_id="paper-1",
            approval_reference="approval-1",
            idempotency_key="idem-1",
            symbol="OPEN",
            side="BUY",
            quantity=10,
            limit_price=4.25,
            proposed_exposure=42.50,
            status="PAPER SUBMITTED",
            created_at=submitted_at,
            submitted_at=submitted_at,
            safety_reason="APPROVED",
            target_price=4.60,
            stop_price=4.10,
            lifecycle_status="OPEN",
            filled_at=filled_at,
            fill_price=4.25,
            highest_price=4.30,
            lowest_price=4.20,
        )
    )

    tracker = WebullPaperLifecycleTracker(
        store=store
    )

    tracker.process_bars(
        bars_by_symbol={
            "OPEN": [
                # This would hit both stop and target,
                # but it occurred BEFORE the fill.
                bar(
                    1,
                    high=4.70,
                    low=4.00,
                    close=4.30,
                ),
                bar(
                    4,
                    high=4.35,
                    low=4.18,
                    close=4.30,
                ),
            ]
        }
    )

    record = store.load()["paper-1"]

    assert record.lifecycle_status == "OPEN"
    assert record.highest_price == 4.35
    assert record.lowest_price == 4.18


def test_open_trade_ignores_cached_bars_before_fill(
    tmp_path,
):
    store = WebullPaperOrderStore(
        tmp_path / "paper-orders.json"
    )

    submitted_at = datetime(
        2026,
        8,
        7,
        14,
        0,
        tzinfo=UTC,
    )
    filled_at = datetime(
        2026,
        8,
        7,
        14,
        3,
        tzinfo=UTC,
    )

    store.add(
        WebullPaperOrderRecord(
            paper_order_id="paper-1",
            approval_reference="approval-1",
            idempotency_key="idem-1",
            symbol="OPEN",
            side="BUY",
            quantity=10,
            limit_price=4.25,
            proposed_exposure=42.50,
            status="PAPER SUBMITTED",
            created_at=submitted_at,
            submitted_at=submitted_at,
            safety_reason="APPROVED",
            target_price=4.60,
            stop_price=4.10,
            lifecycle_status="OPEN",
            filled_at=filled_at,
            fill_price=4.25,
            highest_price=4.30,
            lowest_price=4.20,
        )
    )

    tracker = WebullPaperLifecycleTracker(
        store=store
    )

    tracker.process_bars(
        bars_by_symbol={
            "OPEN": [
                # This would hit both stop and target,
                # but it occurred BEFORE the fill.
                bar(
                    1,
                    high=4.70,
                    low=4.00,
                    close=4.30,
                ),
                bar(
                    4,
                    high=4.35,
                    low=4.18,
                    close=4.30,
                ),
            ]
        }
    )

    record = store.load()["paper-1"]

    assert record.lifecycle_status == "OPEN"
    assert record.highest_price == 4.35
    assert record.lowest_price == 4.18
