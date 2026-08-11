from trading_bot.webull_trade_history import (
    calculate_fifo_realized_trades,
    fills_for_date,
    parse_webull_fills,
    summarize_realized_trades,
)


def sample_payload():
    return [
        {
            "combo_type": "NORMAL",
            "orders": [
                {
                    "symbol": "MARA",
                    "side": "BUY",
                    "status": "FILLED",
                    "filled_quantity": "20",
                    "filled_price": "9.65",
                    "filled_time": 1786456473406,
                }
            ],
        },
        {
            "combo_type": "NORMAL",
            "orders": [
                {
                    "symbol": "MARA",
                    "side": "SELL",
                    "status": "FILLED",
                    "filled_quantity": "20",
                    "filled_price": "9.80",
                    "filled_time": 1786457149318,
                }
            ],
        },
        {
            "combo_type": "NORMAL",
            "orders": [
                {
                    "symbol": "RIVN",
                    "side": "BUY",
                    "status": "FILLED",
                    "filled_quantity": "50",
                    "filled_price": "16.04",
                    "filled_time": 1786455980109,
                }
            ],
        },
        {
            "combo_type": "NORMAL",
            "orders": [
                {
                    "symbol": "RIVN",
                    "side": "SELL",
                    "status": "FILLED",
                    "filled_quantity": "50",
                    "filled_price": "16.22",
                    "filled_time": 1786457105382,
                }
            ],
        },
        {
            "combo_type": "NORMAL",
            "orders": [
                {
                    "symbol": "SOUN",
                    "side": "BUY",
                    "status": "CANCELLED",
                    "filled_quantity": "0",
                    "limit_price": "7.46",
                }
            ],
        },
    ]


def test_parser_keeps_only_real_fills():
    fills = parse_webull_fills(
        sample_payload()
    )

    assert len(fills) == 4
    assert all(
        fill.quantity > 0
        for fill in fills
    )


def test_fills_are_filtered_by_new_york_date():
    fills = parse_webull_fills(
        sample_payload()
    )

    dated = fills_for_date(
        fills,
        "2026-08-11",
    )

    assert len(dated) == 4


def test_fifo_realized_pnl_matches_webull_fills():
    fills = parse_webull_fills(
        sample_payload()
    )

    trades, remaining = (
        calculate_fifo_realized_trades(
            fills,
            "2026-08-11",
        )
    )

    assert remaining == {}
    assert len(trades) == 2

    by_symbol = {
        trade.symbol: trade
        for trade in trades
    }

    assert (
        by_symbol["MARA"]
        .realized_pnl
        == 3.00
    )

    assert (
        by_symbol["RIVN"]
        .realized_pnl
        == 9.00
    )


def test_daily_summary_calculates_realized_total():
    fills = parse_webull_fills(
        sample_payload()
    )

    trades, _ = (
        calculate_fifo_realized_trades(
            fills,
            "2026-08-11",
        )
    )

    summary = summarize_realized_trades(
        trades,
        "2026-08-11",
    )

    assert summary.closed_trades == 2
    assert summary.winning_trades == 2
    assert summary.losing_trades == 0
    assert summary.realized_pnl == 12.00
    assert summary.win_rate_pct == 100.0
