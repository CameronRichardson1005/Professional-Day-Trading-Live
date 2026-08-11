import pytest

from trading_bot.webull_account_parser import (
    WebullResponseError,
    parse_account_balance,
    parse_account_list,
    parse_open_orders,
    parse_positions,
)


def test_parses_single_cash_account():
    result = parse_account_list([
        {
            "account_id": "account-1",
            "account_type": "CASH",
        }
    ])

    assert result.account_id == "account-1"
    assert result.account_type == "CASH"


def test_rejects_margin_account_only_at_safety_layer():
    result = parse_account_list([
        {
            "account_id": "account-1",
            "account_type": "MARGIN",
        }
    ])

    assert result.account_type == "MARGIN"


def test_rejects_multiple_accounts():
    with pytest.raises(
        WebullResponseError,
        match="Exactly one",
    ):
        parse_account_list([
            {
                "account_id": "one",
                "account_type": "CASH",
            },
            {
                "account_id": "two",
                "account_type": "CASH",
            },
        ])


def test_rejects_unknown_account_type():
    with pytest.raises(
        WebullResponseError,
        match="not CASH or MARGIN",
    ):
        parse_account_list([
            {
                "account_id": "account-1",
                "account_type": "UNKNOWN",
            }
        ])


def test_parses_available_cash():
    result = parse_account_balance({
        "available_cash": "1000.25",
    })

    assert result.available_cash == 1000.25


def test_balance_fails_when_cash_missing():
    with pytest.raises(
        WebullResponseError,
        match="Available cash field was missing",
    ):
        parse_account_balance({
            "buying_power": "4000",
        })


def test_parses_position_market_value():
    result = parse_positions([
        {
            "symbol": "AAPL",
            "quantity": "2",
            "market_price": "100",
            "market_value": "200",
        }
    ])

    assert len(result) == 1
    assert result[0].market_value == 200.0


def test_uses_larger_reported_position_value():
    result = parse_positions([
        {
            "symbol": "AAPL",
            "quantity": "2",
            "market_price": "100",
            "market_value": "250",
        }
    ])

    assert result[0].market_value == 250.0


def test_uses_larger_calculated_position_value():
    result = parse_positions([
        {
            "symbol": "AAPL",
            "quantity": "2",
            "market_price": "100",
            "market_value": "190",
        }
    ])

    assert result[0].market_value == 200.0


def test_open_buy_order_reserves_remaining_exposure():
    result = parse_open_orders([
        {
            "symbol": "AAPL",
            "side": "BUY",
            "quantity": "10",
            "filled_quantity": "4",
            "remain_quantity": "6",
            "limit_price": "20",
        }
    ])

    assert len(result) == 1
    assert result[0].remaining_quantity == 6.0
    assert result[0].reserved_exposure == 120.0


def test_open_sell_order_reserves_no_buy_exposure():
    result = parse_open_orders([
        {
            "symbol": "AAPL",
            "side": "SELL",
            "quantity": "5",
            "filled_quantity": "0",
            "limit_price": "20",
        }
    ])

    assert result[0].reserved_exposure == 0.0


def test_rejects_disagreeing_remaining_quantity():
    with pytest.raises(
        WebullResponseError,
        match="remaining quantity fields disagreed",
    ):
        parse_open_orders([
            {
                "symbol": "AAPL",
                "side": "BUY",
                "quantity": "10",
                "filled_quantity": "4",
                "remain_quantity": "5",
                "limit_price": "20",
            }
        ])


def test_rejects_negative_numbers():
    with pytest.raises(
        WebullResponseError,
        match="cannot be negative",
    ):
        parse_account_balance({
            "available_cash": "-1",
        })


def test_parses_webull_us_currency_asset_balance():
    result = parse_account_balance({
        "account_currency_assets": [
            {
                "currency": "USD",
                "buying_power": "4000.00",
                "cash_balance": "1000.00",
                "settled_cash": "900.00",
                "unsettled_cash": "100.00",
                "market_value": "0.00",
            }
        ],
        "total_asset_currency": "USD",
        "total_cash_balance": "1000.00",
    })

    # Settled cash is used rather than buying power,
    # unsettled cash, or the larger cash balance.
    assert result.available_cash == 900.0


def test_never_uses_buying_power_as_cash():
    with pytest.raises(
        WebullResponseError,
        match="USD settled cash field was missing",
    ):
        parse_account_balance({
            "account_currency_assets": [
                {
                    "currency": "USD",
                    "buying_power": "4000.00",
                    "cash_balance": "1000.00",
                }
            ],
            "total_asset_currency": "USD",
            "total_cash_balance": "1000.00",
        })


def test_rejects_non_usd_total_asset_currency():
    with pytest.raises(
        WebullResponseError,
        match="Total asset currency must be USD",
    ):
        parse_account_balance({
            "account_currency_assets": [
                {
                    "currency": "USD",
                    "cash_balance": "1000.00",
                    "settled_cash": "1000.00",
                }
            ],
            "total_asset_currency": "AUD",
            "total_cash_balance": "1000.00",
        })


def test_rejects_missing_usd_currency_asset():
    with pytest.raises(
        WebullResponseError,
        match="Exactly one USD",
    ):
        parse_account_balance({
            "account_currency_assets": [
                {
                    "currency": "AUD",
                    "cash_balance": "1000.00",
                    "settled_cash": "1000.00",
                }
            ],
            "total_asset_currency": "AUD",
        })


def test_rejects_duplicate_usd_currency_assets():
    with pytest.raises(
        WebullResponseError,
        match="Exactly one USD",
    ):
        parse_account_balance({
            "account_currency_assets": [
                {
                    "currency": "USD",
                    "cash_balance": "500.00",
                    "settled_cash": "500.00",
                },
                {
                    "currency": "USD",
                    "cash_balance": "500.00",
                    "settled_cash": "500.00",
                },
            ],
            "total_asset_currency": "USD",
        })


def test_parses_nested_webull_us_open_orders():
    result = parse_open_orders([
        {
            "client_order_id": "combo-1",
            "combo_order_id": "combo-order-1",
            "combo_type": "NORMAL",
            "orders": [
                {
                    "symbol": "OPEN",
                    "side": "BUY",
                    "total_quantity": "20",
                    "filled_quantity": "5",
                    "limit_price": "4.00",
                    "status": "WORKING",
                }
            ],
        }
    ])

    assert len(result) == 1
    assert result[0].symbol == "OPEN"
    assert result[0].remaining_quantity == 15.0
    assert result[0].reserved_exposure == 60.0


def test_parses_multiple_nested_combo_orders():
    result = parse_open_orders([
        {
            "orders": [
                {
                    "symbol": "OPEN",
                    "side": "BUY",
                    "total_quantity": "10",
                    "filled_quantity": "2",
                    "limit_price": "5.00",
                }
            ]
        },
        {
            "orders": [
                {
                    "symbol": "SOUN",
                    "side": "SELL",
                    "total_quantity": "4",
                    "filled_quantity": "0",
                    "limit_price": "10.00",
                }
            ]
        },
    ])

    assert len(result) == 2
    assert result[0].reserved_exposure == 40.0
    assert result[1].reserved_exposure == 0.0


def test_rejects_invalid_nested_order_list():
    with pytest.raises(
        WebullResponseError,
        match="Nested open orders must be a list",
    ):
        parse_open_orders([
            {
                "orders": {
                    "symbol": "OPEN",
                }
            }
        ])
