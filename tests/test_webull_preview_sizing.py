from unittest.mock import patch

import pytest

from trading_bot.models import Stock
from trading_bot.webull_preview_client import (
    WebullPreviewClient,
)


def invest_stock(
    *,
    limit_buy: float,
    trading_stop: float,
) -> Stock:
    stock = Stock(symbol="TEST")
    stock.signal = "INVEST"
    stock.limit_buy = limit_buy
    stock.limit_sell = limit_buy + 1.0
    stock.trading_stop_loss = trading_stop
    return stock


def test_risk_budget_limits_quantity():
    stock = invest_stock(
        limit_buy=10.0,
        trading_stop=9.0,
    )

    with (
        patch(
            "trading_bot.webull_preview_client."
            "WEBULL_PREVIEW_RISK_DOLLARS",
            25.0,
        ),
        patch(
            "trading_bot.webull_preview_client."
            "WEBULL_PREVIEW_MAX_SHARES",
            1000,
        ),
        patch(
            "trading_bot.webull_preview_client."
            "WEBULL_PREVIEW_MAX_POSITION_VALUE",
            5000.0,
        ),
    ):
        request = WebullPreviewClient.build_request(stock)

    assert request.quantity == 25
    assert request.planned_risk == 25.0
    assert request.estimated_position_value == 250.0
    assert request.max_position_value == 5000.0
    assert request.sizing_constraint == "RISK_BUDGET"


def test_position_value_limits_quantity():
    stock = invest_stock(
        limit_buy=100.0,
        trading_stop=99.99,
    )

    with (
        patch(
            "trading_bot.webull_preview_client."
            "WEBULL_PREVIEW_RISK_DOLLARS",
            25.0,
        ),
        patch(
            "trading_bot.webull_preview_client."
            "WEBULL_PREVIEW_MAX_SHARES",
            1000,
        ),
        patch(
            "trading_bot.webull_preview_client."
            "WEBULL_PREVIEW_MAX_POSITION_VALUE",
            5000.0,
        ),
    ):
        request = WebullPreviewClient.build_request(stock)

    assert request.quantity == 50
    assert request.estimated_position_value == 5000.0
    assert request.max_position_value == 5000.0
    assert request.sizing_constraint == "POSITION_VALUE"


def test_max_shares_limits_quantity():
    stock = invest_stock(
        limit_buy=5.0,
        trading_stop=4.99,
    )

    with (
        patch(
            "trading_bot.webull_preview_client."
            "WEBULL_PREVIEW_RISK_DOLLARS",
            25.0,
        ),
        patch(
            "trading_bot.webull_preview_client."
            "WEBULL_PREVIEW_MAX_SHARES",
            100,
        ),
        patch(
            "trading_bot.webull_preview_client."
            "WEBULL_PREVIEW_MAX_POSITION_VALUE",
            5000.0,
        ),
    ):
        request = WebullPreviewClient.build_request(stock)

    assert request.quantity == 100
    assert request.estimated_position_value == 500.0
    assert request.sizing_constraint == "MAX_SHARES"


def test_price_above_position_cap_is_rejected():
    stock = invest_stock(
        limit_buy=6000.0,
        trading_stop=5999.0,
    )

    with patch(
        "trading_bot.webull_preview_client."
        "WEBULL_PREVIEW_MAX_POSITION_VALUE",
        5000.0,
    ):
        with pytest.raises(
            ValueError,
            match="exceeds the maximum position value",
        ):
            WebullPreviewClient.build_request(stock)
