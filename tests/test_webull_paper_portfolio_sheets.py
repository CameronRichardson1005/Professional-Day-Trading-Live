from types import SimpleNamespace

from trading_bot.sheets_client import SheetsClient


def portfolio():
    return SimpleNamespace(
        starting_cash=10_000.0,
        cash=9_965.0,
        buying_power=9_965.0,
        open_cost_basis=40.0,
        market_value=42.0,
        realized_pnl=5.0,
        unrealized_pnl=2.0,
        total_pnl=7.0,
        equity=10_007.0,
        open_position_count=1,
        closed_position_count=2,
        pending_order_count=1,
        no_entry_count=1,
        overdrawn=False,
    )


def risk_status(
    *,
    trading_allowed=True,
    reason="PAPER_TRADING_ALLOWED",
):
    return SimpleNamespace(
        trading_allowed=trading_allowed,
        reason=reason,
        available_for_new_orders=9_850.0,
        pending_reserved_cash=115.0,
        daily_realized_pnl=-10.0,
        max_daily_loss=50.0,
        remaining_daily_loss=40.0,
    )


def test_write_paper_portfolio_uses_dedicated_sheet():
    client = object.__new__(SheetsClient)

    worksheet = object()
    seen = {}

    def get_or_create_worksheet(
        *,
        title,
        rows,
        cols,
    ):
        seen["title"] = title
        seen["rows"] = rows
        seen["cols"] = cols
        return worksheet

    def replace_date_rows(
        *,
        worksheet,
        columns,
        date_str,
        replacement_rows,
        last_column,
        sheet_name,
    ):
        seen["worksheet"] = worksheet
        seen["columns"] = columns
        seen["date_str"] = date_str
        seen["rows_data"] = replacement_rows
        seen["last_column"] = last_column
        seen["sheet_name"] = sheet_name

    client.get_or_create_worksheet = (
        get_or_create_worksheet
    )
    client._replace_date_rows = replace_date_rows

    client.write_paper_portfolio(
        date_str="2026-08-07",
        portfolio=portfolio(),
        risk_status=risk_status(),
    )

    assert seen["title"] == "Paper Portfolio"
    assert seen["sheet_name"] == "Paper Portfolio"
    assert seen["date_str"] == "2026-08-07"
    assert seen["last_column"] == "X"
    assert len(seen["columns"]) == 24

    row = seen["rows_data"][0]

    assert row[0] == "2026-08-07"
    assert row[1] == 10_000.0
    assert row[2] == 9_965.0
    assert row[3] == 9_965.0
    assert row[4] == 40.0
    assert row[5] == 42.0
    assert row[6] == 5.0
    assert row[7] == 2.0
    assert row[8] == 7.0
    assert row[9] == 10_007.0
    assert row[10] == 1
    assert row[11] == 2
    assert row[12] == 1
    assert row[13] == 1
    assert row[14] == "NO"

    assert row[15] == "YES"
    assert row[16] == "PAPER_TRADING_ALLOWED"
    assert row[17] == 9_850.0
    assert row[18] == 115.0
    assert row[19] == -10.0
    assert row[20] == 50.0
    assert row[21] == 40.0

    assert row[22] == "YES"
    assert row[23] == "NO"


def test_write_paper_portfolio_marks_risk_halt():
    client = object.__new__(SheetsClient)

    worksheet = object()
    seen = {}

    client.get_or_create_worksheet = (
        lambda **kwargs: worksheet
    )
    client._replace_date_rows = (
        lambda **kwargs: seen.update(kwargs)
    )

    client.write_paper_portfolio(
        date_str="2026-08-07",
        portfolio=portfolio(),
        risk_status=risk_status(
            trading_allowed=False,
            reason="PAPER_DAILY_LOSS_LIMIT_REACHED",
        ),
    )

    row = seen["replacement_rows"][0]

    assert row[15] == "NO"
    assert row[16] == (
        "PAPER_DAILY_LOSS_LIMIT_REACHED"
    )
    assert row[22] == "YES"
    assert row[23] == "NO"


def test_write_paper_portfolio_handles_missing_risk_status():
    client = object.__new__(SheetsClient)

    worksheet = object()
    seen = {}

    client.get_or_create_worksheet = (
        lambda **kwargs: worksheet
    )
    client._replace_date_rows = (
        lambda **kwargs: seen.update(kwargs)
    )

    client.write_paper_portfolio(
        date_str="2026-08-07",
        portfolio=portfolio(),
        risk_status=None,
    )

    row = seen["replacement_rows"][0]

    assert row[15] == "UNKNOWN"
    assert row[16] == "RISK STATUS UNAVAILABLE"
    assert row[22] == "YES"
    assert row[23] == "NO"
