from dataclasses import replace
from datetime import UTC, datetime

from trading_bot.webull_paper_order_store import (
    WebullPaperOrderRecord,
    WebullPaperOrderStore,
)
from trading_bot.webull_paper_performance import (
    build_webull_paper_daily_performance,
    load_webull_paper_daily_performance,
)


def base_order(
    *,
    paper_order_id,
    symbol,
    submitted_at=None,
):
    submitted_at = submitted_at or datetime(
        2026,
        8,
        7,
        14,
        0,
        tzinfo=UTC,
    )

    return WebullPaperOrderRecord(
        paper_order_id=paper_order_id,
        approval_reference=(
            f"approval-{paper_order_id}"
        ),
        idempotency_key=f"idem-{paper_order_id}",
        symbol=symbol,
        side="BUY",
        quantity=10,
        limit_price=10.0,
        proposed_exposure=100.0,
        status="PAPER SUBMITTED",
        created_at=submitted_at,
        submitted_at=submitted_at,
        safety_reason="APPROVED",
        target_price=11.0,
        stop_price=9.5,
    )


def closed_order(
    *,
    paper_order_id,
    symbol,
    pnl,
    return_pct,
    reason,
    mfe_pct,
    mae_pct,
):
    order = base_order(
        paper_order_id=paper_order_id,
        symbol=symbol,
    )

    return replace(
        order,
        lifecycle_status="CLOSED",
        filled_at=datetime(
            2026,
            8,
            7,
            14,
            1,
            tzinfo=UTC,
        ),
        fill_price=10.0,
        highest_price=10.0 * (
            1 + mfe_pct / 100.0
        ),
        lowest_price=10.0 * (
            1 + mae_pct / 100.0
        ),
        mfe_pct=mfe_pct,
        mae_pct=mae_pct,
        closed_at=datetime(
            2026,
            8,
            7,
            14,
            30,
            tzinfo=UTC,
        ),
        exit_price=10.0 * (
            1 + return_pct / 100.0
        ),
        exit_reason=reason,
        realized_pnl=pnl,
        return_pct=return_pct,
    )


def test_daily_report_calculates_core_metrics():
    records = [
        closed_order(
            paper_order_id="1",
            symbol="OPEN",
            pnl=4.50,
            return_pct=4.5,
            reason="TARGET",
            mfe_pct=5.0,
            mae_pct=-1.0,
        ),
        closed_order(
            paper_order_id="2",
            symbol="SOUN",
            pnl=-2.00,
            return_pct=-2.0,
            reason="STOP",
            mfe_pct=1.5,
            mae_pct=-2.5,
        ),
        closed_order(
            paper_order_id="3",
            symbol="BBAI",
            pnl=1.50,
            return_pct=1.5,
            reason="TIME EXIT",
            mfe_pct=2.5,
            mae_pct=-0.5,
        ),
    ]

    report = build_webull_paper_daily_performance(
        date_str="2026-08-07",
        records=records,
    )

    assert report.orders_approved == 3
    assert report.trades_entered == 3
    assert report.open_trades == 0
    assert report.closed_trades == 3

    assert report.target_exits == 1
    assert report.stop_exits == 1
    assert report.time_exits == 1

    assert report.profitable_trades == 2
    assert report.losing_trades == 1
    assert report.breakeven_trades == 0

    assert report.win_rate_pct == round(
        2 / 3 * 100,
        6,
    )

    assert report.realized_pnl == 4.0
    assert report.average_pnl_per_trade == round(
        4.0 / 3,
        6,
    )
    assert report.expectancy_per_trade == round(
        4.0 / 3,
        6,
    )

    assert report.average_return_pct == round(
        (4.5 - 2.0 + 1.5) / 3,
        6,
    )

    assert report.average_winner == 3.0
    assert report.average_loser == -2.0

    assert report.average_mfe_pct == 3.0
    assert report.average_mae_pct == round(
        (-1.0 - 2.5 - 0.5) / 3,
        6,
    )

    assert report.best_trade_symbol == "OPEN"
    assert report.best_trade_pnl == 4.50
    assert report.worst_trade_symbol == "SOUN"
    assert report.worst_trade_pnl == -2.00


def test_no_entry_counts_as_order_but_not_trade():
    order = base_order(
        paper_order_id="1",
        symbol="OPEN",
    )

    no_entry = replace(
        order,
        lifecycle_status="CLOSED",
        closed_at=datetime(
            2026,
            8,
            7,
            15,
            0,
            tzinfo=UTC,
        ),
        exit_reason="NO ENTRY",
    )

    report = build_webull_paper_daily_performance(
        date_str="2026-08-07",
        records=[no_entry],
    )

    assert report.orders_approved == 1
    assert report.no_entry == 1
    assert report.trades_entered == 0
    assert report.closed_trades == 0
    assert report.realized_pnl == 0
    assert report.win_rate_pct is None


def test_open_trade_not_in_realized_metrics():
    order = base_order(
        paper_order_id="1",
        symbol="OPEN",
    )

    open_trade = replace(
        order,
        lifecycle_status="OPEN",
        filled_at=datetime(
            2026,
            8,
            7,
            14,
            1,
            tzinfo=UTC,
        ),
        fill_price=10.0,
        highest_price=10.5,
        lowest_price=9.8,
        mfe_pct=5.0,
        mae_pct=-2.0,
    )

    report = build_webull_paper_daily_performance(
        date_str="2026-08-07",
        records=[open_trade],
    )

    assert report.orders_approved == 1
    assert report.trades_entered == 1
    assert report.open_trades == 1
    assert report.closed_trades == 0
    assert report.realized_pnl == 0
    assert report.average_return_pct is None
    assert report.win_rate_pct is None


def test_zero_orders_returns_empty_report():
    report = build_webull_paper_daily_performance(
        date_str="2026-08-07",
        records=[],
    )

    assert report.orders_approved == 0
    assert report.trades_entered == 0
    assert report.closed_trades == 0
    assert report.realized_pnl == 0

    assert report.win_rate_pct is None
    assert report.average_pnl_per_trade is None
    assert report.average_winner is None
    assert report.average_loser is None
    assert report.best_trade_symbol is None
    assert report.worst_trade_symbol is None


def test_breakeven_trade_is_not_win_or_loss():
    record = closed_order(
        paper_order_id="1",
        symbol="OPEN",
        pnl=0.0,
        return_pct=0.0,
        reason="TIME EXIT",
        mfe_pct=1.0,
        mae_pct=-1.0,
    )

    report = build_webull_paper_daily_performance(
        date_str="2026-08-07",
        records=[record],
    )

    assert report.profitable_trades == 0
    assert report.losing_trades == 0
    assert report.breakeven_trades == 1
    assert report.win_rate_pct == 0.0


def test_report_filters_by_new_york_trading_date():
    # 01:00 UTC on Aug 8 is still Aug 7 in New York.
    record = base_order(
        paper_order_id="1",
        symbol="OPEN",
        submitted_at=datetime(
            2026,
            8,
            8,
            1,
            0,
            tzinfo=UTC,
        ),
    )

    report = build_webull_paper_daily_performance(
        date_str="2026-08-07",
        records=[record],
    )

    assert report.orders_approved == 1


def test_other_trading_dates_are_excluded():
    record = base_order(
        paper_order_id="1",
        symbol="OPEN",
        submitted_at=datetime(
            2026,
            8,
            6,
            14,
            0,
            tzinfo=UTC,
        ),
    )

    report = build_webull_paper_daily_performance(
        date_str="2026-08-07",
        records=[record],
    )

    assert report.orders_approved == 0


def test_legacy_pending_record_does_not_break_report():
    legacy = base_order(
        paper_order_id="1",
        symbol="OPEN",
    )

    legacy = replace(
        legacy,
        target_price=None,
        stop_price=None,
    )

    report = build_webull_paper_daily_performance(
        date_str="2026-08-07",
        records=[legacy],
    )

    assert report.orders_approved == 1
    assert report.trades_entered == 0
    assert report.realized_pnl == 0


def test_report_loads_records_from_store(tmp_path):
    store = WebullPaperOrderStore(
        tmp_path / "paper-orders.json"
    )

    store.add(
        base_order(
            paper_order_id="1",
            symbol="OPEN",
        )
    )

    report = load_webull_paper_daily_performance(
        date_str="2026-08-07",
        store=store,
    )

    assert report.orders_approved == 1


def test_report_converts_to_plain_dictionary():
    report = build_webull_paper_daily_performance(
        date_str="2026-08-07",
        records=[],
    )

    payload = report.to_dict()

    assert payload["date"] == "2026-08-07"
    assert payload["orders_approved"] == 0
    assert payload["realized_pnl"] == 0
