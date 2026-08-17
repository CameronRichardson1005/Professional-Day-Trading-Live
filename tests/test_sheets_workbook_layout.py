from trading_bot.sheets_client import SheetsClient


class FakeWorksheet:
    def __init__(self, title, sheet_id):
        self.title = title
        self.id = sheet_id


class FakeSpreadsheet:
    def __init__(self, worksheets):
        self._worksheets = list(worksheets)
        self.reorder_calls = []
        self.batch_calls = []

    def worksheets(self):
        return list(self._worksheets)

    def reorder_worksheets(self, worksheets):
        self.reorder_calls.append(
            [ws.title for ws in worksheets]
        )
        self._worksheets = list(worksheets)

    def batch_update(self, payload):
        self.batch_calls.append(payload)


def test_daily_sheet_layout_policy():
    scanner = (
        SheetsClient
        ._trading_sheet_layout_policy(
            "Scanner Dashboard"
        )
    )

    assert scanner is not None
    assert scanner["widths"][3] == 135
    assert scanner["hidden_columns"] == [
        (2, 3),
        (5, 7),
        (8, 9),
    ]

    manipulation = (
        SheetsClient
        ._trading_sheet_layout_policy(
            "Manipulation Signals"
        )
    )

    assert manipulation is not None
    assert manipulation["widths"][14] == 220
    assert (15, 26) in (
        manipulation["hidden_columns"]
    )

    quick_flip = (
        SheetsClient
        ._trading_sheet_layout_policy(
            "Quick Flip Signals"
        )
    )

    assert quick_flip is not None
    assert quick_flip["widths"][14] == 120
    assert quick_flip["hidden_columns"] == [
        (8, 14),
        (15, 18),
    ]


def test_non_trading_sheet_has_no_layout_policy():
    assert (
        SheetsClient
        ._trading_sheet_layout_policy(
            "Some Other Sheet"
        )
        is None
    )


def test_trading_workbook_structure():
    visible = [
        "Trade Previews",
        "Scanner Dashboard",
        "Manipulation Signals",
        "Quick Flip Signals",
        "Daily Trade P&L",
        "Daily P&L Summary",
    ]

    hidden = [
        "Quick Flip Previews",
        (
            "Manipulation Selling Pressure "
            "Research"
        ),
        "Committed Allocation History",
    ]

    desired = visible + hidden

    # Deliberately start in the wrong order.
    worksheets = [
        FakeWorksheet(
            title,
            index,
        )
        for index, title in enumerate(
            reversed(desired),
            start=1,
        )
    ]

    spreadsheet = FakeSpreadsheet(
        worksheets
    )

    client = object.__new__(
        SheetsClient
    )
    client.spreadsheet = spreadsheet

    applied = (
        client
        ._apply_trading_workbook_structure(
            worksheets=worksheets,
        )
    )

    assert applied is True
    assert spreadsheet.reorder_calls == [
        desired
    ]

    requests = (
        spreadsheet
        .batch_calls[-1]["requests"]
    )

    hidden_by_id = {
        request[
            "updateSheetProperties"
        ]["properties"]["sheetId"]:
        request[
            "updateSheetProperties"
        ]["properties"]["hidden"]
        for request in requests
    }

    by_title = {
        worksheet.title: worksheet
        for worksheet in worksheets
    }

    for title in visible:
        assert hidden_by_id[
            by_title[title].id
        ] is False

    for title in hidden:
        assert hidden_by_id[
            by_title[title].id
        ] is True


def test_structure_is_noop_for_other_workbook():
    worksheets = [
        FakeWorksheet(
            "Scanner Dashboard",
            1,
        )
    ]

    spreadsheet = FakeSpreadsheet(
        worksheets
    )

    client = object.__new__(
        SheetsClient
    )
    client.spreadsheet = spreadsheet

    applied = (
        client
        ._apply_trading_workbook_structure(
            worksheets=worksheets,
        )
    )

    assert applied is False
    assert spreadsheet.reorder_calls == []
    assert spreadsheet.batch_calls == []


def test_trade_previews_display_requests():
    columns = [
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

    values = [
        columns,
        [
            "2026-08-17",
            "11:00:00",
            "4",
            "Manipulation",
            "SOUN",
            "7.09",
            "7.1863",
            "1",
            "16.67%",
            "$7.46",
            "PREVIEW READY",
        ],
        [
            "2026-08-17",
            "10:25:00",
            "",
            "Quick Flip",
            "RIVN",
            "14.85",
            "15.05 / 15.36",
            "",
            "0.00%",
            "$0.00",
            "BLOCKED BY MANIPULATION",
        ],
        [
            "2026-08-17",
            "10:30:00",
            "",
            "Quick Flip",
            "TEST",
            "",
            "",
            "",
            "",
            "",
            "PREVIEW FAILED",
        ],
    ]

    requests = []

    (
        SheetsClient
        ._append_trade_previews_display_requests(
            requests=requests,
            columns=columns,
            values=values,
            sheet_id=123,
            row_count=len(values),
        )
    )

    number_formats = {}

    for request in requests:
        repeat = request.get(
            "repeatCell",
            {}
        )

        cell_format = (
            repeat.get(
                "cell",
                {}
            )
            .get(
                "userEnteredFormat",
                {}
            )
        )

        number_format = (
            cell_format.get(
                "numberFormat"
            )
        )

        if number_format is None:
            continue

        column_index = (
            repeat["range"][
                "startColumnIndex"
            ]
        )

        number_formats[
            column_index
        ] = number_format

    assert number_formats[1] == {
        "type": "TIME",
        "pattern": "h:mm AM/PM",
    }

    assert number_formats[5] == {
        "type": "CURRENCY",
        "pattern": "$0.0000",
    }

    assert number_formats[6] == {
        "type": "CURRENCY",
        "pattern": "$0.0000",
    }

    assert number_formats[8] == {
        "type": "PERCENT",
        "pattern": "0.00%",
    }

    assert number_formats[9] == {
        "type": "CURRENCY",
        "pattern": "$0.00",
    }

    status_backgrounds = {}

    for request in requests:
        repeat = request.get(
            "repeatCell",
            {}
        )

        cell_range = repeat.get(
            "range",
            {}
        )

        if (
            cell_range.get(
                "startColumnIndex"
            )
            != 10
        ):
            continue

        background = (
            repeat.get(
                "cell",
                {}
            )
            .get(
                "userEnteredFormat",
                {}
            )
            .get(
                "backgroundColor"
            )
        )

        if background is None:
            continue

        status_backgrounds[
            cell_range[
                "startRowIndex"
            ]
        ] = background

    assert status_backgrounds[1] == {
        "red": 0.82,
        "green": 0.94,
        "blue": 0.82,
    }

    assert status_backgrounds[2] == {
        "red": 1.00,
        "green": 0.88,
        "blue": 0.78,
    }

    assert status_backgrounds[3] == {
        "red": 0.96,
        "green": 0.78,
        "blue": 0.78,
    }


def test_trade_previews_approved_widths():
    policy = (
        SheetsClient
        ._trading_sheet_layout_policy(
            "Trade Previews"
        )
    )

    assert policy is not None

    assert policy["widths"] == {
        0: 105,
        1: 105,
        2: 60,
        3: 125,
        4: 80,
        5: 100,
        6: 145,
        7: 90,
        8: 115,
        9: 180,
        10: 225,
    }


def test_new_york_clock_time_formatter():
    from datetime import datetime, timezone

    value = datetime(
        2026,
        8,
        17,
        14,
        25,
        tzinfo=timezone.utc,
    )

    assert (
        SheetsClient
        ._format_new_york_clock_time(
            value
        )
        == "10:25 AM"
    )


def test_final_scanner_and_quick_flip_widths():
    scanner = (
        SheetsClient
        ._trading_sheet_layout_policy(
            "Scanner Dashboard"
        )
    )

    assert scanner is not None
    assert scanner["widths"][10] == 260

    quick_flip = (
        SheetsClient
        ._trading_sheet_layout_policy(
            "Quick Flip Signals"
        )
    )

    assert quick_flip is not None
    assert quick_flip["widths"][4] == 150
    assert quick_flip["widths"][14] == 120


def test_quick_flip_visible_price_formats():
    columns = [
        "Date",
        "Symbol",
        "Status",
        "Signal",
        "Pattern",
        "Entry",
        "TP1",
        "TP2",
        "Confirmation Time",
    ]

    values = [
        columns,
        [
            "2026-08-17",
            "RIVN",
            "INVEST",
            "INVEST",
            "HAMMER",
            "14.85",
            "15.05",
            "15.36",
            "10:25 AM",
        ],
    ]

    worksheet = FakeWorksheet(
        "Quick Flip Signals",
        301,
    )

    spreadsheet = FakeSpreadsheet(
        [worksheet]
    )

    client = object.__new__(
        SheetsClient
    )

    client.spreadsheet = spreadsheet
    client._worksheet_values_cache = {
        "Quick Flip Signals": values,
    }

    client.format_worksheet(
        worksheet
    )

    requests = (
        spreadsheet
        .batch_calls[-1]["requests"]
    )

    formats = {}

    for request in requests:
        repeat = request.get(
            "repeatCell",
            {}
        )

        number_format = (
            repeat.get(
                "cell",
                {}
            )
            .get(
                "userEnteredFormat",
                {}
            )
            .get(
                "numberFormat"
            )
        )

        if number_format is None:
            continue

        column_index = (
            repeat["range"][
                "startColumnIndex"
            ]
        )

        formats[
            column_index
        ] = number_format

    assert formats[5] == {
        "type": "CURRENCY",
        "pattern": "$#,##0.0000",
    }

    assert formats[6] == {
        "type": "CURRENCY",
        "pattern": "$#,##0.0000",
    }

    assert formats[7] == {
        "type": "CURRENCY",
        "pattern": "$#,##0.0000",
    }


def test_daily_pnl_summary_formats():
    columns = [
        "Date",
        "Closed Trades",
        "Winning Trades",
        "Losing Trades",
        "Breakeven Trades",
        "Win Rate %",
        "Gross Profit",
        "Gross Loss",
        "Realized P&L",
        "Source",
    ]

    values = [
        columns,
        [
            "2026-08-17",
            "2",
            "2",
            "0",
            "0",
            "100",
            "12",
            "0",
            "12",
            "WEBULL ORDER HISTORY",
        ],
    ]

    worksheet = FakeWorksheet(
        "Daily P&L Summary",
        302,
    )

    spreadsheet = FakeSpreadsheet(
        [worksheet]
    )

    client = object.__new__(
        SheetsClient
    )

    client.spreadsheet = spreadsheet
    client._worksheet_values_cache = {
        "Daily P&L Summary": values,
    }

    client.format_worksheet(
        worksheet
    )

    requests = (
        spreadsheet
        .batch_calls[-1]["requests"]
    )

    formats = {}

    for request in requests:
        repeat = request.get(
            "repeatCell",
            {}
        )

        number_format = (
            repeat.get(
                "cell",
                {}
            )
            .get(
                "userEnteredFormat",
                {}
            )
            .get(
                "numberFormat"
            )
        )

        if number_format is None:
            continue

        column_index = (
            repeat["range"][
                "startColumnIndex"
            ]
        )

        formats[
            column_index
        ] = number_format

    assert formats[5] == {
        "type": "NUMBER",
        "pattern": '0.00"%"',
    }

    for column_index in (
        6,
        7,
        8,
    ):
        assert formats[
            column_index
        ] == {
            "type": "CURRENCY",
            "pattern": "$#,##0.00",
        }
