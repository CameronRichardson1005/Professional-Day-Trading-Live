from types import SimpleNamespace

from trading_bot.models import Stock
from trading_bot.sheets_client import SheetsClient


def make_client():
    client = object.__new__(SheetsClient)
    captured = {}

    client.get_or_create_worksheet = (
        lambda **kwargs: SimpleNamespace()
    )

    def replace_date_rows(**kwargs):
        captured.update(kwargs)

    client._replace_date_rows = replace_date_rows
    return client, captured


def test_fibonacci_strategy_sheet_fields():
    client, captured = make_client()

    stock = Stock(symbol="OPEN")
    stock.strategy_name = "FIBONACCI_61_8"
    stock.strategy_status = (
        "ACTIVE PAPER/PREVIEW — NOT SUBMITTED"
    )
    stock.signal = "INVEST"
    stock.limit_buy = 4.25
    stock.limit_sell = 4.60
    stock.stop_loss = 4.10
    stock.trading_stop_loss = 4.10
    stock.reward_risk = 2.33
    stock.confirmation_time = "10:08"
    stock.retracement_price = 4.18
    stock.impulse_atr_multiple = 0.72
    stock.pullback_volume_ratio = 0.64
    stock.atr = 0.40
    stock.opening_bar = {
        "o": 4.00,
        "h": 4.20,
        "l": 3.95,
        "c": 4.15,
    }

    client.write_strategy_results(
        date_str="2026-08-03",
        stocks={"OPEN": stock},
    )

    columns = captured["columns"]
    row = captured["replacement_rows"][0]
    values = dict(zip(columns, row))

    assert values["Strategy"] == "FIBONACCI_61_8"
    assert values["Signal"] == "INVEST"
    assert values["Entry"] == 4.25
    assert values["Target"] == 4.60
    assert values["Trading Stop Loss"] == 4.10
    assert values["Reward / Risk"] == 2.33
    assert values["Confirmation Time"] == "10:08"
    assert values["Retracement Price"] == 4.18
    assert values["Impulse ATR Multiple"] == 0.72
    assert values["Pullback Volume Ratio"] == 0.64


def test_missing_optional_strategy_values_are_safe():
    client, captured = make_client()

    stock = Stock(symbol="PLTR")
    stock.strategy_name = "FIBONACCI_61_8"
    stock.strategy_status = (
        "ACTIVE PAPER/PREVIEW — NOT SUBMITTED"
    )
    stock.signal = "NO INVEST"
    stock.strategy_rejection_reason = (
        "NO_QUALIFYING_SETUP"
    )

    client.write_strategy_results(
        date_str="2026-08-03",
        stocks={"PLTR": stock},
    )

    columns = captured["columns"]
    row = captured["replacement_rows"][0]
    values = dict(zip(columns, row))

    assert values["Entry"] == ""
    assert values["Target"] == ""
    assert values["Stop Loss"] == ""
    assert values["Reward / Risk"] == ""
    assert values["Opening Open"] == ""
    assert (
        values["Rejection Reason"]
        == "NO_QUALIFYING_SETUP"
    )


def test_manipulation_fields_remain_available():
    client, captured = make_client()

    stock = Stock(symbol="BBAI")
    stock.strategy_name = "MANIPULATION_OPENING_15M"
    stock.strategy_status = (
        "PRESERVED HISTORICAL STRATEGY"
    )
    stock.signal = "INVEST"
    stock.is_manipulation = True
    stock.is_red = True
    stock.candle_range = 0.25
    stock.atr_threshold = 0.20

    client.write_strategy_results(
        date_str="2026-08-03",
        stocks={"BBAI": stock},
    )

    columns = captured["columns"]
    row = captured["replacement_rows"][0]
    values = dict(zip(columns, row))

    assert values["Manipulation Candle"] == "YES"
    assert values["Red Candle"] == "YES"
    assert values["Candle Range"] == 0.25
    assert values["ATR Threshold"] == 0.20
