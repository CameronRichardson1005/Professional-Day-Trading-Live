from types import SimpleNamespace

from trading_bot.sheets_client import SheetsClient


class FakeWorksheet:
    def __init__(self, values=None):
        self.values = values or []
        self.updated = None
        self.cleared = []

    def get_all_values(self):
        return self.values

    def update(
        self,
        *,
        values,
        range_name,
        value_input_option,
    ):
        self.updated = {
            "values": values,
            "range_name": range_name,
            "value_input_option": value_input_option,
        }
        self.values = values

    def batch_clear(self, ranges):
        self.cleared.extend(ranges)


def make_client(worksheet):
    client = object.__new__(SheetsClient)

    client.get_or_create_worksheet = (
        lambda **kwargs: worksheet
    )

    return client


def make_report():
    return SimpleNamespace(
        date="2026-08-07",
        orders_approved=5,
        trades_entered=4,
        open_trades=0,
        closed_trades=4,
        no_entry=1,
        target_exits=2,
        stop_exits=1,
        time_exits=1,
        profitable_trades=3,
        losing_trades=1,
        breakeven_trades=0,
        win_rate_pct=75.0,
        realized_pnl=8.42,
        average_pnl_per_trade=2.105,
        average_return_pct=1.84,
        average_winner=3.47,
        average_loser=-1.99,
        expectancy_per_trade=2.105,
        average_mfe_pct=3.4,
        average_mae_pct=-1.1,
        best_trade_symbol="OPEN",
        best_trade_pnl=4.5,
        worst_trade_symbol="SOUN",
        worst_trade_pnl=-1.99,
    )


def test_write_paper_performance_creates_expected_row():
    worksheet = FakeWorksheet()
    client = make_client(worksheet)

    client.write_paper_performance(
        report=make_report(),
    )

    values = worksheet.updated["values"]

    assert values[0][0] == "Date"
    assert values[0][-1] == "Worst Trade P&L"

    row = values[1]

    assert row[0] == "2026-08-07"
    assert row[1] == 5
    assert row[2] == 4
    assert row[12] == 75.0
    assert row[13] == 8.42
    assert row[21] == "OPEN"
    assert row[22] == 4.5
    assert row[23] == "SOUN"
    assert row[24] == -1.99

    assert (
        worksheet.updated["range_name"]
        == "A1:Y2"
    )


def test_write_replaces_same_date_not_duplicates():
    report = make_report()

    header = [
        "Date",
        "Orders Approved",
        "Trades Entered",
        "Open Trades",
        "Closed Trades",
        "No Entry",
        "Target Exits",
        "Stop Exits",
        "Time Exits",
        "Profitable Trades",
        "Losing Trades",
        "Breakeven Trades",
        "Win Rate %",
        "Realized P&L",
        "Average P&L / Trade",
        "Average Return %",
        "Average Winner",
        "Average Loser",
        "Expectancy / Trade",
        "Average MFE %",
        "Average MAE %",
        "Best Trade",
        "Best Trade P&L",
        "Worst Trade",
        "Worst Trade P&L",
    ]

    old_row = [
        "2026-08-07",
        *["OLD"] * 24,
    ]

    other_date = [
        "2026-08-06",
        *["KEEP"] * 24,
    ]

    worksheet = FakeWorksheet(
        [header, old_row, other_date]
    )

    client = make_client(worksheet)

    client.write_paper_performance(
        report=report,
    )

    values = worksheet.updated["values"]

    assert len(values) == 3

    assert values[1][0] == "2026-08-06"
    assert values[2][0] == "2026-08-07"
    assert values[2][13] == 8.42


def test_empty_metrics_are_written_as_blank_cells():
    report = SimpleNamespace(
        date="2026-08-07",
        orders_approved=0,
        trades_entered=0,
        open_trades=0,
        closed_trades=0,
        no_entry=0,
        target_exits=0,
        stop_exits=0,
        time_exits=0,
        profitable_trades=0,
        losing_trades=0,
        breakeven_trades=0,
        win_rate_pct=None,
        realized_pnl=0,
        average_pnl_per_trade=None,
        average_return_pct=None,
        average_winner=None,
        average_loser=None,
        expectancy_per_trade=None,
        average_mfe_pct=None,
        average_mae_pct=None,
        best_trade_symbol=None,
        best_trade_pnl=None,
        worst_trade_symbol=None,
        worst_trade_pnl=None,
    )

    worksheet = FakeWorksheet()
    client = make_client(worksheet)

    client.write_paper_performance(
        report=report,
    )

    row = worksheet.updated["values"][1]

    assert row[12] == ""
    assert row[13] == 0
    assert row[14] == ""
    assert row[21] == ""
    assert row[24] == ""
