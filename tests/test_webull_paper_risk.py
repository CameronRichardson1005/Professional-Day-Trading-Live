from dataclasses import replace
from datetime import UTC, datetime

import pytest

from trading_bot.webull_paper_order_store import (
    WebullPaperOrderRecord,
)
from trading_bot.webull_paper_risk import (
    WebullPaperRiskError,
    configured_paper_max_daily_loss,
    evaluate_webull_paper_risk,
)


NOW = datetime(
    2026,
    8,
    7,
    15,
    0,
    tzinfo=UTC,
)


def record(
    *,
    paper_order_id="1",
    lifecycle_status="ENTRY PENDING",
    exposure=100.0,
):
    return WebullPaperOrderRecord(
        paper_order_id=paper_order_id,
        approval_reference=f"approval-{paper_order_id}",
        idempotency_key=f"key-{paper_order_id}",
        symbol="OPEN",
        side="BUY",
        quantity=10,
        limit_price=exposure / 10,
        proposed_exposure=exposure,
        status="PAPER SUBMITTED",
        created_at=NOW,
        submitted_at=NOW,
        safety_reason="APPROVED_BY_SAFETY_GATE",
        target_price=(exposure / 10) + 1,
        stop_price=(exposure / 10) - 1,
        lifecycle_status=lifecycle_status,
    )


def open_record(
    *,
    paper_order_id="open",
    exposure=100.0,
):
    base = record(
        paper_order_id=paper_order_id,
        exposure=exposure,
    )

    return replace(
        base,
        lifecycle_status="OPEN",
        filled_at=NOW,
        fill_price=exposure / 10,
        highest_price=exposure / 10,
        lowest_price=exposure / 10,
        mfe_pct=0.0,
        mae_pct=0.0,
    )


def closed_record(
    *,
    paper_order_id="closed",
    realized_pnl=-25.0,
    submitted_at=NOW,
):
    base = record(
        paper_order_id=paper_order_id,
        exposure=100.0,
    )

    fill_price = 10.0
    exit_price = (
        fill_price
        + realized_pnl / base.quantity
    )

    return replace(
        base,
        submitted_at=submitted_at,
        lifecycle_status="CLOSED",
        filled_at=submitted_at,
        fill_price=fill_price,
        highest_price=max(
            fill_price,
            exit_price,
        ),
        lowest_price=min(
            fill_price,
            exit_price,
        ),
        mfe_pct=max(
            (exit_price - fill_price)
            / fill_price
            * 100,
            0.0,
        ),
        mae_pct=min(
            (exit_price - fill_price)
            / fill_price
            * 100,
            0.0,
        ),
        closed_at=submitted_at,
        exit_price=exit_price,
        exit_reason="STOP",
        realized_pnl=realized_pnl,
        return_pct=(
            realized_pnl
            / 100.0
            * 100.0
        ),
    )


def test_empty_account_allows_affordable_order():
    result = evaluate_webull_paper_risk(
        records=[],
        proposed_exposure=500,
        now=NOW,
        starting_cash=10_000,
        max_daily_loss=50,
    )

    assert result.allowed
    assert result.reason == "PAPER_RISK_APPROVED"
    assert result.available_for_new_orders == 10_000
    assert result.projected_available_cash == 9_500


def test_pending_orders_reserve_cash():
    result = evaluate_webull_paper_risk(
        records=[
            record(
                exposure=600,
            )
        ],
        proposed_exposure=500,
        now=NOW,
        starting_cash=1_000,
        max_daily_loss=50,
    )

    assert not result.allowed
    assert result.reason == (
        "PAPER_INSUFFICIENT_AVAILABLE_CASH"
    )
    assert result.pending_reserved_cash == 600
    assert result.available_for_new_orders == 400


def test_open_positions_reduce_cash():
    result = evaluate_webull_paper_risk(
        records=[
            open_record(
                exposure=700,
            )
        ],
        proposed_exposure=400,
        now=NOW,
        starting_cash=1_000,
        max_daily_loss=50,
    )

    assert not result.allowed
    assert result.cash == 300
    assert result.available_for_new_orders == 300


def test_exact_remaining_cash_is_allowed():
    result = evaluate_webull_paper_risk(
        records=[
            record(
                exposure=600,
            )
        ],
        proposed_exposure=400,
        now=NOW,
        starting_cash=1_000,
        max_daily_loss=50,
    )

    assert result.allowed
    assert result.projected_available_cash == 0


def test_daily_loss_limit_blocks_new_order():
    result = evaluate_webull_paper_risk(
        records=[
            closed_record(
                realized_pnl=-50,
            )
        ],
        proposed_exposure=100,
        now=NOW,
        starting_cash=10_000,
        max_daily_loss=50,
    )

    assert not result.allowed
    assert result.reason == (
        "PAPER_DAILY_LOSS_LIMIT_REACHED"
    )
    assert result.daily_realized_pnl == -50


def test_loss_below_limit_still_allows_order():
    result = evaluate_webull_paper_risk(
        records=[
            closed_record(
                realized_pnl=-49.99,
            )
        ],
        proposed_exposure=100,
        now=NOW,
        starting_cash=10_000,
        max_daily_loss=50,
    )

    assert result.allowed


def test_prior_day_loss_does_not_trigger_today():
    yesterday = datetime(
        2026,
        8,
        6,
        15,
        0,
        tzinfo=UTC,
    )

    result = evaluate_webull_paper_risk(
        records=[
            closed_record(
                realized_pnl=-100,
                submitted_at=yesterday,
            )
        ],
        proposed_exposure=100,
        now=NOW,
        starting_cash=10_000,
        max_daily_loss=50,
    )

    assert result.allowed
    assert result.daily_realized_pnl == 0


def test_default_daily_loss_is_fifty(
    monkeypatch,
):
    monkeypatch.delenv(
        "WEBULL_PAPER_MAX_DAILY_LOSS",
        raising=False,
    )

    assert configured_paper_max_daily_loss() == 50


def test_daily_loss_reads_environment(
    monkeypatch,
):
    monkeypatch.setenv(
        "WEBULL_PAPER_MAX_DAILY_LOSS",
        "75",
    )

    assert configured_paper_max_daily_loss() == 75


@pytest.mark.parametrize(
    "value",
    [
        "0",
        "-1",
        "nan",
        "inf",
        "bad",
    ],
)
def test_invalid_daily_loss_fails_closed(
    monkeypatch,
    value,
):
    monkeypatch.setenv(
        "WEBULL_PAPER_MAX_DAILY_LOSS",
        value,
    )

    with pytest.raises(
        WebullPaperRiskError,
        match="INVALID_PAPER_MAX_DAILY_LOSS",
    ):
        configured_paper_max_daily_loss()


def test_risk_status_reports_trading_allowed():
    from trading_bot.webull_paper_risk import (
        build_webull_paper_risk_status,
    )

    status = build_webull_paper_risk_status(
        records=[],
        now=NOW,
        starting_cash=1000,
        max_daily_loss=50,
    )

    assert status.trading_allowed is True
    assert status.reason == "PAPER_TRADING_ALLOWED"
    assert status.available_for_new_orders == 1000
    assert status.remaining_daily_loss == 50
    assert status.simulation_only is True
    assert status.broker_submitted is False


def test_risk_status_reports_daily_loss_halt():
    from trading_bot.webull_paper_risk import (
        build_webull_paper_risk_status,
    )

    status = build_webull_paper_risk_status(
        records=[
            closed_record(
                realized_pnl=-50,
            )
        ],
        now=NOW,
        starting_cash=1000,
        max_daily_loss=50,
    )

    assert status.trading_allowed is False
    assert status.reason == (
        "PAPER_DAILY_LOSS_LIMIT_REACHED"
    )
    assert status.daily_realized_pnl == -50
    assert status.remaining_daily_loss == 0


def test_risk_status_reserves_pending_cash():
    from trading_bot.webull_paper_risk import (
        build_webull_paper_risk_status,
    )

    status = build_webull_paper_risk_status(
        records=[
            record(
                exposure=750,
            )
        ],
        now=NOW,
        starting_cash=1000,
        max_daily_loss=50,
    )

    assert status.trading_allowed is True
    assert status.pending_reserved_cash == 750
    assert status.available_for_new_orders == 250


def test_risk_status_blocks_when_no_cash_remains():
    from trading_bot.webull_paper_risk import (
        build_webull_paper_risk_status,
    )

    status = build_webull_paper_risk_status(
        records=[
            record(
                exposure=1000,
            )
        ],
        now=NOW,
        starting_cash=1000,
        max_daily_loss=50,
    )

    assert status.trading_allowed is False
    assert status.reason == "PAPER_NO_AVAILABLE_CASH"
    assert status.available_for_new_orders == 0
