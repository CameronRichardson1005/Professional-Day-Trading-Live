from types import SimpleNamespace

from trading_bot.sheets_client import SheetsClient


class FakeWorksheet:
    def __init__(self):
        self.title = "Trade Previews"
        self.values = None
        self.cleared = False

    def clear(self):
        self.cleared = True

    def resize(self, **kwargs):
        pass

    def update(self, **kwargs):
        self.values = kwargs["values"]

    def get_all_values(self):
        return self.values or []


def test_trade_previews_sheet_is_today_only_and_concise():
    client = object.__new__(SheetsClient)

    worksheet = FakeWorksheet()

    client.get_or_create_worksheet = (
        lambda **kwargs: worksheet
    )

    client.format_worksheet = (
        lambda worksheet: None
    )

    client.write_trade_previews_today(
        date_str="2026-08-11",
        previews=[
            {
                "time": "09:47:00",
                "strategy": "Manipulation",
                "symbol": "OPEN",
                "entry": 4.12,
                "exit": 4.45,
                "quantity": 25,
                "status": "PREVIEW READY",
            },
            {
                "time": "10:05:00",
                "strategy": "Quick Flip",
                "symbol": "MARA",
                "entry": 9.65,
                "exit": "9.80 / 10.05",
                "quantity": 20,
                "status": "PREVIEW READY",
            },
        ],
    )

    assert worksheet.cleared is True

    assert worksheet.values[0] == [
        "Time",
        "Strategy",
        "Stock",
        "Entry",
        "Exit",
        "Quantity",
        "Status",
    ]

    assert worksheet.values[1][2] == "OPEN"
    assert worksheet.values[2][2] == "MARA"

    assert len(
        worksheet.values[0]
    ) == 7
