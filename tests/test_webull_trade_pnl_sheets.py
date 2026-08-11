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
    assert row[4] == 20.0
    assert row[5] == 9.65
    assert row[6] == 9.80
    assert row[9] == 3.00
    assert row[11] == 0.0
    assert row[12] == "CLOSED"
    assert row[13] == "WEBULL ORDER HISTORY"

    assert client.formatted_titles == [
        "Daily Trade P&L",
    ]


def test_write_webull_trade_pnl_marks_remaining_position():
    client, calls = make_client()

    trade = SimpleNamespace(
        symbol="RIVN",
        buy_time=datetime(
            2026,
            8,
            11,
            9,
            50,
            tzinfo=EASTERN,
        ),
        sell_time=datetime(
            2026,
            8,
            11,
            10,
            10,
            tzinfo=EASTERN,
        ),
        quantity=10.0,
        buy_price=16.04,
        sell_price=16.22,
        gross_cost=160.40,
        gross_proceeds=162.20,
        realized_pnl=1.80,
        return_pct=1.1222,
    )

    client.write_webull_trade_pnl(
        date_str="2026-08-11",
        trades=[trade],
        remaining={
            "RIVN": 40.0,
        },
    )

    row = calls[0][
        "replacement_rows"
    ][0]

    assert row[11] == 40.0
    assert row[12] == "PARTIALLY CLOSED"


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
