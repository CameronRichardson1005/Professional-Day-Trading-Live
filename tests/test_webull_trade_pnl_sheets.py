from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from trading_bot.sheets_client import SheetsClient


EASTERN = ZoneInfo("America/New_York")


def make_client():
    client = object.__new__(SheetsClient)

    calls = []

    client.get_or_create_worksheet = (
        lambda **kwargs: SimpleNamespace(
            title=kwargs["title"]
        )
    )

    def fake_replace(**kwargs):
        calls.append(kwargs)

    client._replace_date_rows = fake_replace

    client.formatted_titles = []

    def fake_format(worksheet):
        client.formatted_titles.append(
            worksheet.title
        )

    client.format_worksheet = fake_format

    return client, calls


def test_write_webull_trade_pnl():
    client, calls = make_client()

    trade = SimpleNamespace(
        symbol="MARA",
        buy_time=datetime(
            2026,
            8,
            11,
            9,
            54,
            tzinfo=EASTERN,
        ),
        sell_time=datetime(
            2026,
            8,
            11,
            10,
            5,
            tzinfo=EASTERN,
        ),
        quantity=20.0,
        buy_price=9.65,
        sell_price=9.80,
        gross_cost=193.00,
        gross_proceeds=196.00,
        realized_pnl=3.00,
        return_pct=1.5544,
    )

    client.write_webull_trade_pnl(
        date_str="2026-08-11",
        trades=[trade],
        remaining={},
    )

    assert len(calls) == 1

    call = calls[0]

    assert call["sheet_name"] == (
        "Daily Trade P&L"
    )

    assert call["date_str"] == (
        "2026-08-11"
    )

    row = call["replacement_rows"][0]

    assert row[0] == "2026-08-11"
    assert row[1] == "MARA"
    assert row == [
        "2026-08-11",
        "MARA",
        20.0,
        9.65,
        9.80,
        3.00,
        1.5544,
        3.00,
    ]

    assert client.formatted_titles == [
        "Daily Trade P&L",
    ]


def test_write_webull_trade_pnl_calculates_running_total():
    client, calls = make_client()

    first = SimpleNamespace(
        symbol="RIVN",
        quantity=10.0,
        buy_price=16.04,
        sell_price=16.22,
        realized_pnl=1.80,
        return_pct=1.1222,
    )

    second = SimpleNamespace(
        symbol="OPEN",
        quantity=5.0,
        buy_price=3.50,
        sell_price=3.40,
        realized_pnl=-0.50,
        return_pct=-2.8571,
    )

    client.write_webull_trade_pnl(
        date_str="2026-08-11",
        trades=[
            first,
            second,
        ],
        remaining={},
    )

    rows = calls[0]["replacement_rows"]

    assert rows[0] == [
        "2026-08-11",
        "RIVN",
        10.0,
        16.04,
        16.22,
        1.80,
        1.1222,
        1.80,
    ]

    assert rows[1] == [
        "2026-08-11",
        "OPEN",
        5.0,
        3.50,
        3.40,
        -0.50,
        -2.8571,
        1.30,
    ]



def test_write_webull_pnl_summary():
    client, calls = make_client()

    summary = SimpleNamespace(
        date="2026-08-11",
        closed_trades=2,
        winning_trades=2,
        losing_trades=0,
        breakeven_trades=0,
        win_rate_pct=100.0,
        gross_profit=12.0,
        gross_loss=0.0,
        realized_pnl=12.0,
    )

    client.write_webull_pnl_summary(
        summary=summary,
    )

    assert len(calls) == 1

    call = calls[0]

    assert call["sheet_name"] == (
        "Daily P&L Summary"
    )

    assert call["replacement_rows"] == [[
        "2026-08-11",
        2,
        2,
        0,
        0,
        100.0,
        12.0,
        0.0,
        12.0,
        "WEBULL ORDER HISTORY",
    ]]

    assert client.formatted_titles == [
        "Daily P&L Summary",
    ]
