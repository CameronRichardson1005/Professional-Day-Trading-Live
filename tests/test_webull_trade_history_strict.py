from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from trading_bot.webull_trade_history import (
    WebullFill,
    WebullTradeHistoryError,
    calculate_fifo_realized_trades_strict,
    parse_webull_fills_strict,
    strict_daily_realized_pnl,
)


EASTERN = ZoneInfo(
    "America/New_York"
)


def milliseconds(
    year,
    month,
    day,
    hour,
    minute,
):
    value = datetime(
        year,
        month,
        day,
        hour,
        minute,
        tzinfo=EASTERN,
    )

    return int(
        value.timestamp()
        * 1000
    )


def fill(
    *,
    symbol="SOUN",
    side,
    quantity,
    price,
    year=2026,
    month=8,
    day=18,
    hour=10,
    minute=0,
):
    return WebullFill(
        symbol=symbol,
        side=side,
        quantity=quantity,
        price=price,
        filled_at=datetime(
            year,
            month,
            day,
            hour,
            minute,
            tzinfo=EASTERN,
        ),
    )


def test_overnight_inventory_is_used_for_today_sell():
    fills = [
        fill(
            side="BUY",
            quantity=10,
            price=10.0,
            day=17,
            hour=15,
        ),
        fill(
            side="SELL",
            quantity=10,
            price=9.5,
            day=18,
            hour=10,
        ),
    ]

    trades, remaining = (
        calculate_fifo_realized_trades_strict(
            fills,
            "2026-08-18",
        )
    )

    assert len(trades) == 1
    assert trades[0].realized_pnl == -5.0
    assert remaining == {}


def test_prior_sell_consumes_fifo_before_target_day():
    fills = [
        fill(
            side="BUY",
            quantity=5,
            price=10.0,
            day=16,
        ),
        fill(
            side="BUY",
            quantity=5,
            price=12.0,
            day=17,
        ),
        fill(
            side="SELL",
            quantity=5,
            price=11.0,
            day=17,
            hour=14,
        ),
        fill(
            side="SELL",
            quantity=5,
            price=11.0,
            day=18,
            hour=10,
        ),
    ]

    trades, remaining = (
        calculate_fifo_realized_trades_strict(
            fills,
            "2026-08-18",
        )
    )

    assert len(trades) == 1
    assert trades[0].buy_price == 12.0
    assert trades[0].realized_pnl == -5.0
    assert remaining == {}


def test_unmatched_sell_fails_closed():
    fills = [
        fill(
            side="SELL",
            quantity=1,
            price=10.0,
        )
    ]

    with pytest.raises(
        WebullTradeHistoryError,
        match=(
            "SELL_EXCEEDS_KNOWN_LONG_INVENTORY"
        ),
    ):
        calculate_fifo_realized_trades_strict(
            fills,
            "2026-08-18",
        )


def test_cancelled_partial_fill_is_not_discarded():
    payload = [
        {
            "orders": [
                {
                    "symbol": "SOUN",
                    "side": "BUY",
                    "status": "CANCELLED",
                    "filled_quantity": "2",
                    "filled_price": "10.25",
                    "filled_time": milliseconds(
                        2026,
                        8,
                        18,
                        10,
                        0,
                    ),
                }
            ]
        }
    ]

    fills = parse_webull_fills_strict(
        payload
    )

    assert len(fills) == 1
    assert fills[0].quantity == 2.0
    assert fills[0].price == 10.25


def test_zero_fill_cancelled_order_is_ignored():
    payload = [
        {
            "orders": [
                {
                    "symbol": "SOUN",
                    "side": "BUY",
                    "status": "CANCELLED",
                    "filled_quantity": "0",
                }
            ]
        }
    ]

    assert (
        parse_webull_fills_strict(
            payload
        )
        == []
    )


def test_positive_fill_missing_price_fails_closed():
    payload = [
        {
            "orders": [
                {
                    "symbol": "SOUN",
                    "side": "BUY",
                    "status": "FILLED",
                    "filled_quantity": "1",
                    "filled_time": milliseconds(
                        2026,
                        8,
                        18,
                        10,
                        0,
                    ),
                }
            ]
        }
    ]

    with pytest.raises(
        WebullTradeHistoryError,
        match=(
            "STRICT_FILLED_PRICE_INVALID"
        ),
    ):
        parse_webull_fills_strict(
            payload
        )


def test_future_fill_does_not_affect_target_day():
    fills = [
        fill(
            side="BUY",
            quantity=1,
            price=10.0,
            day=18,
        ),
        fill(
            side="SELL",
            quantity=1,
            price=9.0,
            day=18,
            hour=11,
        ),
        fill(
            side="BUY",
            quantity=50,
            price=1.0,
            day=19,
        ),
    ]

    assert (
        strict_daily_realized_pnl(
            fills,
            "2026-08-18",
        )
        == -1.0
    )


def test_carry_inventory_remains_after_target_date():
    fills = [
        fill(
            side="BUY",
            quantity=3,
            price=10.0,
            day=17,
        ),
        fill(
            side="SELL",
            quantity=1,
            price=11.0,
            day=18,
        ),
    ]

    trades, remaining = (
        calculate_fifo_realized_trades_strict(
            fills,
            "2026-08-18",
        )
    )

    assert len(trades) == 1
    assert trades[0].realized_pnl == 1.0
    assert remaining == {
        "SOUN": 2.0,
    }
