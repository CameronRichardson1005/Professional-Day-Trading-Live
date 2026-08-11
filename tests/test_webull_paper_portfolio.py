from dataclasses import replace
from datetime import UTC, datetime

import pytest

from trading_bot.webull_paper_order_store import (
    WebullPaperOrderRecord,
    WebullPaperOrderStore,
)
from trading_bot.webull_paper_portfolio import (
    WebullPaperPortfolioError,
    build_webull_paper_portfolio,
    configured_paper_starting_cash,
    load_webull_paper_portfolio,
)


NOW = datetime(
    2026,
    8,
    7,
    14,
    0,
    tzinfo=UTC,
)


def order(
    *,
    paper_order_id,
    symbol="OPEN",
    quantity=10,
    fill_price=10.0,
):
    return WebullPaperOrderRecord(
        paper_order_id=paper_order_id,
        approval_reference=(
            f"approval-{paper_order_id}"
        ),
        idempotency_key=(
            f"idem-{paper_order_id}"
        ),
        symbol=symbol,
        side="BUY",
        quantity=quantity,
        limit_price=fill_price,
        proposed_exposure=round(
            quantity * fill_price,
            2,
        ),
        status="PAPER SUBMITTED",
        created_at=NOW,
        submitted_at=NOW,
        safety_reason="APPROVED",
        target_price=fill_price + 1.0,
        stop_price=fill_price - 0.5,
    )


def open_order(
    *,
    paper_order_id,
    symbol="OPEN",
    quantity=10,
    fill_price=10.0,
):
    base = order(
        paper_order_id=paper_order_id,
        symbol=symbol,
        quantity=quantity,
        fill_price=fill_price,
    )

    return replace(
        base,
        lifecycle_status="OPEN",
        filled_at=NOW,
        fill_price=fill_price,
        highest_price=fill_price,
        lowest_price=fill_price,
        mfe_pct=0.0,
        mae_pct=0.0,
    )


def closed_order(
    *,
    paper_order_id,
    symbol="OPEN",
    quantity=10,
    fill_price=10.0,
    exit_price=11.0,
    reason="TARGET",
):
    base = open_order(
        paper_order_id=paper_order_id,
        symbol=symbol,
        quantity=quantity,
        fill_price=fill_price,
    )

    pnl = round(
        (exit_price - fill_price)
        * quantity,
        6,
    )

    return_pct = round(
        (
            exit_price - fill_price
        )
        / fill_price
        * 100.0,
        6,
    )

    return replace(
        base,
        lifecycle_status="CLOSED",
        closed_at=NOW,
        exit_price=exit_price,
        exit_reason=reason,
        realized_pnl=pnl,
        return_pct=return_pct,
    )


def no_entry_order(
    *,
    paper_order_id,
):
    base = order(
        paper_order_id=paper_order_id,
    )

    return replace(
        base,
        lifecycle_status="CLOSED",
        closed_at=NOW,
        exit_reason="NO ENTRY",
    )


def test_empty_portfolio_equals_starting_cash():
    portfolio = build_webull_paper_portfolio(
        records=[],
        starting_cash=10_000,
    )

    assert portfolio.starting_cash == 10_000
    assert portfolio.cash == 10_000
    assert portfolio.buying_power == 10_000
    assert portfolio.market_value == 0
    assert portfolio.realized_pnl == 0
    assert portfolio.unrealized_pnl == 0
    assert portfolio.total_pnl == 0
    assert portfolio.equity == 10_000
    assert portfolio.open_position_count == 0


def test_open_position_reduces_cash_and_marks_equity():
    record = open_order(
        paper_order_id="1",
        quantity=10,
        fill_price=10.0,
    )

    portfolio = build_webull_paper_portfolio(
        records=[record],
        latest_prices={
            "OPEN": 10.50,
        },
        starting_cash=10_000,
    )

    assert portfolio.cash == 9_900
    assert portfolio.buying_power == 9_900
    assert portfolio.open_cost_basis == 100
    assert portfolio.market_value == 105
    assert portfolio.unrealized_pnl == 5
    assert portfolio.realized_pnl == 0
    assert portfolio.total_pnl == 5
    assert portfolio.equity == 10_005

    position = portfolio.open_positions[0]

    assert position.symbol == "OPEN"
    assert position.quantity == 10
    assert position.mark_price == 10.50
    assert position.mark_status == "MARKED"
    assert position.unrealized_return_pct == 5.0


def test_closed_winner_returns_capital_and_pnl_to_cash():
    record = closed_order(
        paper_order_id="1",
        quantity=10,
        fill_price=10,
        exit_price=11,
    )

    portfolio = build_webull_paper_portfolio(
        records=[record],
        starting_cash=10_000,
    )

    assert portfolio.cash == 10_010
    assert portfolio.buying_power == 10_010
    assert portfolio.realized_pnl == 10
    assert portfolio.market_value == 0
    assert portfolio.equity == 10_010
    assert portfolio.total_pnl == 10
    assert portfolio.closed_position_count == 1


def test_closed_loss_reduces_cash():
    record = closed_order(
        paper_order_id="1",
        quantity=10,
        fill_price=10,
        exit_price=9.5,
        reason="STOP",
    )

    portfolio = build_webull_paper_portfolio(
        records=[record],
        starting_cash=10_000,
    )

    assert portfolio.realized_pnl == -5
    assert portfolio.cash == 9_995
    assert portfolio.equity == 9_995


def test_mixed_closed_and_open_positions():
    records = [
        closed_order(
            paper_order_id="1",
            symbol="OPEN",
            quantity=10,
            fill_price=10,
            exit_price=11,
        ),
        closed_order(
            paper_order_id="2",
            symbol="SOUN",
            quantity=20,
            fill_price=5,
            exit_price=4.75,
            reason="STOP",
        ),
        open_order(
            paper_order_id="3",
            symbol="BBAI",
            quantity=10,
            fill_price=4,
        ),
    ]

    portfolio = build_webull_paper_portfolio(
        records=records,
        latest_prices={
            "BBAI": 4.20,
        },
        starting_cash=10_000,
    )

    # Closed P&L = +10 - 5 = +5.
    assert portfolio.realized_pnl == 5

    # Open capital = $40.
    assert portfolio.cash == 9_965

    # Marked open position = $42, +$2 unrealized.
    assert portfolio.market_value == 42
    assert portfolio.unrealized_pnl == 2

    assert portfolio.total_pnl == 7
    assert portfolio.equity == 10_007


def test_pending_and_no_entry_do_not_use_cash():
    records = [
        order(
            paper_order_id="1",
        ),
        no_entry_order(
            paper_order_id="2",
        ),
    ]

    portfolio = build_webull_paper_portfolio(
        records=records,
        starting_cash=10_000,
    )

    assert portfolio.cash == 10_000
    assert portfolio.equity == 10_000
    assert portfolio.pending_order_count == 1
    assert portfolio.no_entry_count == 1


def test_restart_without_market_mark_uses_fill_fallback():
    record = open_order(
        paper_order_id="1",
        fill_price=10,
    )

    portfolio = build_webull_paper_portfolio(
        records=[record],
        starting_cash=10_000,
    )

    position = portfolio.open_positions[0]

    assert position.mark_price == 10
    assert position.mark_status == "FILL FALLBACK"
    assert position.unrealized_pnl == 0
    assert portfolio.equity == 10_000


def test_multiple_open_orders_same_symbol_are_preserved():
    records = [
        open_order(
            paper_order_id="1",
            symbol="OPEN",
            quantity=10,
            fill_price=10,
        ),
        open_order(
            paper_order_id="2",
            symbol="OPEN",
            quantity=5,
            fill_price=11,
        ),
    ]

    portfolio = build_webull_paper_portfolio(
        records=records,
        latest_prices={
            "OPEN": 12,
        },
        starting_cash=10_000,
    )

    assert portfolio.open_position_count == 2
    assert portfolio.open_cost_basis == 155
    assert portfolio.market_value == 180
    assert portfolio.unrealized_pnl == 25
    assert portfolio.equity == 10_025


def test_overdrawn_cash_account_has_zero_buying_power():
    record = open_order(
        paper_order_id="1",
        quantity=20,
        fill_price=10,
    )

    portfolio = build_webull_paper_portfolio(
        records=[record],
        latest_prices={
            "OPEN": 10,
        },
        starting_cash=100,
    )

    assert portfolio.cash == -100
    assert portfolio.buying_power == 0
    assert portfolio.overdrawn is True


def test_load_reconstructs_from_durable_store(tmp_path):
    store = WebullPaperOrderStore(
        tmp_path / "paper-orders.json"
    )

    store.add(
        open_order(
            paper_order_id="1",
        )
    )

    restarted_store = WebullPaperOrderStore(
        store.path
    )

    portfolio = load_webull_paper_portfolio(
        store=restarted_store,
        starting_cash=10_000,
        latest_prices={
            "OPEN": 10.25,
        },
    )

    assert portfolio.open_position_count == 1
    assert portfolio.market_value == 102.5
    assert portfolio.unrealized_pnl == 2.5


def test_configured_starting_cash_defaults(
    monkeypatch,
):
    monkeypatch.delenv(
        "WEBULL_PAPER_STARTING_CASH",
        raising=False,
    )

    assert configured_paper_starting_cash() == 10_000


def test_configured_starting_cash_reads_environment(
    monkeypatch,
):
    monkeypatch.setenv(
        "WEBULL_PAPER_STARTING_CASH",
        "25000",
    )

    assert configured_paper_starting_cash() == 25_000


@pytest.mark.parametrize(
    "value",
    [
        "0",
        "-1",
        "nan",
        "inf",
        "not-a-number",
    ],
)
def test_invalid_starting_cash_fails_closed(
    monkeypatch,
    value,
):
    monkeypatch.setenv(
        "WEBULL_PAPER_STARTING_CASH",
        value,
    )

    with pytest.raises(
        WebullPaperPortfolioError,
        match="INVALID_PAPER_STARTING_CASH",
    ):
        configured_paper_starting_cash()


def test_latest_prices_uses_latest_completed_bar():
    from trading_bot.webull_paper_portfolio import (
        latest_prices_from_completed_bars,
    )

    prices = latest_prices_from_completed_bars(
        {
            "open": [
                {
                    "t": "2026-08-07T14:01:00Z",
                    "c": 10.10,
                },
                {
                    "t": "2026-08-07T14:03:00Z",
                    "c": 10.30,
                },
                {
                    "t": "2026-08-07T14:02:00Z",
                    "c": 10.20,
                },
            ]
        }
    )

    assert prices == {
        "OPEN": 10.30,
    }


def test_latest_prices_supports_multiple_symbols():
    from trading_bot.webull_paper_portfolio import (
        latest_prices_from_completed_bars,
    )

    prices = latest_prices_from_completed_bars(
        {
            "OPEN": [
                {
                    "t": "2026-08-07T14:01:00Z",
                    "c": 4.25,
                }
            ],
            "SOUN": [
                {
                    "t": "2026-08-07T14:01:00Z",
                    "c": 6.50,
                }
            ],
        }
    )

    assert prices == {
        "OPEN": 4.25,
        "SOUN": 6.50,
    }


def test_latest_prices_rejects_nonpositive_close():
    from trading_bot.webull_paper_portfolio import (
        latest_prices_from_completed_bars,
    )

    with pytest.raises(
        WebullPaperPortfolioError,
        match="INVALID_PORTFOLIO_MARK_PRICE",
    ):
        latest_prices_from_completed_bars(
            {
                "OPEN": [
                    {
                        "t": "2026-08-07T14:01:00Z",
                        "c": 0,
                    }
                ]
            }
        )


def test_latest_prices_requires_timezone():
    from trading_bot.webull_paper_portfolio import (
        latest_prices_from_completed_bars,
    )

    with pytest.raises(
        WebullPaperPortfolioError,
        match=(
            "PORTFOLIO_MARK_TIMESTAMP_"
            "MUST_BE_TIMEZONE_AWARE"
        ),
    ):
        latest_prices_from_completed_bars(
            {
                "OPEN": [
                    {
                        "t": "2026-08-07T14:01:00",
                        "c": 4.25,
                    }
                ]
            }
        )


def test_latest_prices_empty_cache_is_empty():
    from trading_bot.webull_paper_portfolio import (
        latest_prices_from_completed_bars,
    )

    assert (
        latest_prices_from_completed_bars({})
        == {}
    )
