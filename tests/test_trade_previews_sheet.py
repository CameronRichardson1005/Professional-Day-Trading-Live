from trading_bot.sheets_client import SheetsClient


class FakeWorksheet:
    def __init__(self):
        self.title = "Trade Previews"
        self.cleared = False
        self.values = None
        self.range_name = None
        self.value_input_option = None
        self.rows = None
        self.cols = None

    def clear(self):
        self.cleared = True

    def resize(self, *, rows, cols):
        self.rows = rows
        self.cols = cols

    def update(
        self,
        *,
        range_name,
        values,
        value_input_option,
    ):
        self.range_name = range_name
        self.values = values
        self.value_input_option = value_input_option


def build_client():
    client = object.__new__(SheetsClient)
    worksheet = FakeWorksheet()

    client.get_or_create_worksheet = (
        lambda **kwargs: worksheet
    )

    client.format_worksheet = (
        lambda worksheet: None
    )

    return client, worksheet


def test_trade_previews_sheet_shows_capital_allocation():
    client, worksheet = build_client()

    client.write_trade_previews_today(
        date_str="2026-08-11",
        previews=[
            {
                "time": "09:47:00",
                "rank": 2,
                "strategy": "Manipulation",
                "symbol": "OPEN",
                "entry": 4.12,
                "exit": 4.45,
                "quantity": 25,
                "allocation_weight": 0.50,
                "recommended_allocation": 450.0,
                "status": "PREVIEW READY",
            },
            {
                "time": "10:05:00",
                "rank": 1,
                "strategy": "Quick Flip",
                "symbol": "MARA",
                "entry": 9.65,
                "exit": "9.80 / 10.05",
                "quantity": 20,
                "allocation_weight": 0.50,
                "recommended_allocation": 450.0,
                "status": "PREVIEW READY",
            },
        ],
    )

    assert worksheet.cleared is True

    assert worksheet.values[0] == [
        "Date",
        "Time",
        "Rank",
        "Strategy",
        "Stock",
        "Entry",
        "Exit",
        "Quantity",
        "Allocation %",
        "Recommended Allocation $",
        "Status",
    ]

    # Rank 1 must be displayed first.
    assert worksheet.values[1] == [
        "2026-08-11",
        "10:05:00",
        1,
        "Quick Flip",
        "MARA",
        9.65,
        "9.80 / 10.05",
        20,
        "50.00%",
        "$450.00",
        "PREVIEW READY",
    ]

    assert worksheet.values[2] == [
        "2026-08-11",
        "09:47:00",
        2,
        "Manipulation",
        "OPEN",
        4.12,
        4.45,
        25,
        "50.00%",
        "$450.00",
        "PREVIEW READY",
    ]

    assert worksheet.range_name == "A1:K3"
    assert worksheet.cols == 11


def test_trade_previews_preserves_blocked_status():
    client, worksheet = build_client()

    client.write_trade_previews_today(
        date_str="2026-08-11",
        previews=[
            {
                "time": "10:25:00",
                "rank": "",
                "strategy": "Quick Flip",
                "symbol": "BBAI",
                "entry": 3.32,
                "exit": "3.40 / 3.50",
                "quantity": "",
                "allocation_weight": 0.0,
                "recommended_allocation": 0.0,
                "status": "BLOCKED BY MANIPULATION",
            },
        ],
    )

    assert worksheet.values[1] == [
        "2026-08-11",
        "10:25:00",
        "",
        "Quick Flip",
        "BBAI",
        3.32,
        "3.40 / 3.50",
        "",
        "0.00%",
        "$0.00",
        "BLOCKED BY MANIPULATION",
    ]


def test_trade_previews_ignores_non_display_statuses():
    client, worksheet = build_client()

    client.write_trade_previews_today(
        date_str="2026-08-11",
        previews=[
            {
                "time": "10:30:00",
                "rank": 1,
                "strategy": "Quick Flip",
                "symbol": "OPEN",
                "entry": 4.0,
                "exit": 4.2,
                "quantity": 1,
                "allocation_weight": 1.0,
                "recommended_allocation": 100.0,
                "status": "NOT INVEST",
            },
        ],
    )

    assert worksheet.values == [[
        "Date",
        "Time",
        "Rank",
        "Strategy",
        "Stock",
        "Entry",
        "Exit",
        "Quantity",
        "Allocation %",
        "Recommended Allocation $",
        "Status",
    ]]
