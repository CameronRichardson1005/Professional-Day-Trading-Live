import gspread
from google.oauth2.service_account import Credentials

from .config import (
    CREDS_FILE,
    SCOPES,
    SHEETS_REQUEST_TIMEOUT,
    SPREADSHEET_ID,
)

WHITE = {
    "red": 1,
    "green": 1,
    "blue": 1,
}

LIGHT_BLUE = {
    "red": 0.68,
    "green": 0.85,
    "blue": 0.9,
}

LIGHT_RED = {
    "red": 1,
    "green": 0.75,
    "blue": 0.75,
}

LIGHT_GREEN = {
    "red": 0.78,
    "green": 0.93,
    "blue": 0.78,
}

class SheetsClient:
    def __init__(
        self,
        spreadsheet_id: str | None = None,
    ) -> None:
        self.credentials = Credentials.from_service_account_file(
            CREDS_FILE,
            scopes=SCOPES,
        )

        self.google_client = gspread.authorize(self.credentials)
        self.google_client.set_timeout(
            SHEETS_REQUEST_TIMEOUT
        )

        selected_spreadsheet_id = (
            SPREADSHEET_ID
            if spreadsheet_id is None
            else str(spreadsheet_id).strip()
        )

        if not selected_spreadsheet_id:
            raise ValueError(
                "Google spreadsheet ID cannot be empty."
            )

        self.spreadsheet_id = (
            selected_spreadsheet_id
        )

        self.spreadsheet = (
            self.google_client.open_by_key(
                self.spreadsheet_id
            )
        )

    def get_or_create_worksheet(
        self,
        title: str,
        rows: int = 100,
        cols: int = 20,
    ):
        try:
            return self.spreadsheet.worksheet(title)

        except gspread.exceptions.WorksheetNotFound:
            return self.spreadsheet.add_worksheet(
                title=title,
                rows=rows,
                cols=cols,
            )
    @staticmethod
    def _validate_header(
        existing_values: list[list[str]],
        expected_columns: list[str],
        sheet_name: str,
    ) -> None:
        if not existing_values:
            return

        first_row = existing_values[0]

        # Google Sheets may represent a newly-created blank
        # worksheet as [[]]. Treat a row containing no values as
        # an empty sheet so the production writer can establish
        # its header normally.
        if not first_row or not any(
            str(value).strip()
            for value in first_row
        ):
            return

        if first_row != expected_columns:
            raise RuntimeError(
                f"{sheet_name} has unexpected columns. "
                "The sheet was not modified."
            )

    @staticmethod
    def _normalise_row(
        row: list,
        column_count: int,
    ) -> list:
        normalised = list(row[:column_count])

        if len(normalised) < column_count:
            normalised.extend(
                [""] * (column_count - len(normalised))
            )

        return normalised

    def _rewrite_table(
        self,
        worksheet,
        columns: list[str],
        rows: list[list],
        last_column: str,
    ) -> None:
        existing_row_count = len(worksheet.get_all_values())
        table = [columns, *rows]

        worksheet.update(
            values=table,
            range_name=(
                f"A1:{last_column}{len(table)}"
            ),
            value_input_option="USER_ENTERED",
        )

        if existing_row_count > len(table):
            worksheet.batch_clear(
                [
                    (
                        f"A{len(table) + 1}:"
                        f"{last_column}{existing_row_count}"
                    )
                ]
            )

    def _replace_date_rows(
        self,
        worksheet,
        columns: list[str],
        date_str: str,
        replacement_rows: list[list],
        last_column: str,
        sheet_name: str,
    ) -> None:
        existing_values = worksheet.get_all_values()

        self._validate_header(
            existing_values=existing_values,
            expected_columns=columns,
            sheet_name=sheet_name,
        )

        preserved_rows = []

        for row in existing_values[1:]:
            normalised = self._normalise_row(
                row=row,
                column_count=len(columns),
            )

            if normalised[0] != date_str:
                preserved_rows.append(normalised)

        self._rewrite_table(
            worksheet=worksheet,
            columns=columns,
            rows=[
                *preserved_rows,
                *replacement_rows,
            ],
            last_column=last_column,
        )
    def test_connection(self) -> list[str]:
        worksheets = self.spreadsheet.worksheets()

        return [
            worksheet.title
            for worksheet in worksheets
        ]

    def update_tracking_minute(
            self,
            worksheet,
            updates: list[dict],
    ) -> None:
        """
        Write all stock values and formatting for one minute using
        one values request and one formatting request.
        """
        value_updates = []
        format_requests = []

        sheet_id = worksheet.id

        # Keep columns wide enough that words are not
        # displayed one letter per line.
        column_widths = []

        for column_index in range(column_count):
            cell_values = [
                str(row[column_index])
                for row in values
                if column_index < len(row)
            ]

            longest_word = max(
                (
                    len(word)
                    for value in cell_values
                    for word in value.split()
                ),
                default=0,
            )

            longest_cell = max(
                (
                    len(value)
                    for value in cell_values
                ),
                default=0,
            )

            width = max(
                100,
                longest_word * 8 + 28,
                min(
                    longest_cell * 7 + 28,
                    240,
                ),
            )

            column_widths.append(
                min(width, 260)
            )

        for update in updates:
            row_number = update["row"]
            row_index = row_number - 1

            value_updates.append(
                {
                    "range": f"C{row_number}:F{row_number}",
                    "values": [
                        [
                            update["running_high"],
                            update["running_low"],
                            update["time_label"],
                            update["candle_color"],
                        ]
                    ],
                }
            )

            format_requests.extend(
                [
                    self._background_request(
                        sheet_id=sheet_id,
                        row_index=row_index,
                        column_index=2,
                        color=(
                            LIGHT_BLUE
                            if update["new_high"]
                            else WHITE
                        ),
                    ),
                    self._background_request(
                        sheet_id=sheet_id,
                        row_index=row_index,
                        column_index=3,
                        color=(
                            LIGHT_RED
                            if update["new_low"]
                            else WHITE
                        ),
                    ),
                    self._background_request(
                        sheet_id=sheet_id,
                        row_index=row_index,
                        column_index=5,
                        color=(
                            LIGHT_GREEN
                            if update["candle_color"] == "GREEN"
                            else WHITE
                        ),
                    ),
                ]
            )

        if value_updates:
            worksheet.batch_update(value_updates)

        if format_requests:
            self.spreadsheet.batch_update(
                {
                    "requests": format_requests,
                }
            )

    @staticmethod
    def _background_request(
            sheet_id: int,
            row_index: int,
            column_index: int,
            color: dict,
    ) -> dict:
        return {
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": row_index,
                    "endRowIndex": row_index + 1,
                    "startColumnIndex": column_index,
                    "endColumnIndex": column_index + 1,
                },
                "cell": {
                    "userEnteredFormat": {
                        "backgroundColor": color,
                    }
                },
                "fields": (
                    "userEnteredFormat.backgroundColor"
                ),
            }
        }


    @staticmethod
    def _column_name(column_number: int) -> str:
        """
        Convert a one-based column number into a Google Sheets
        column name.
        """
        result = ""
        number = column_number

        while number:
            number, remainder = divmod(number - 1, 26)
            result = chr(65 + remainder) + result

        return result

    @staticmethod
    def _status_colour(value: str) -> dict | None:
        normalised = str(value).strip().upper()

        green_values = {
            "INVEST",
            "SELECTED",
            "PREVIEW READY",
            "READY",
            "COMPLETE",
            "COMPLETED",
            "YES",
            "GREEN",
            "PASSED",
            "SUCCESS",
        }

        red_values = {
            "NO INVEST",
            "FAILED",
            "ERROR",
            "RED",
            "INCOMPLETE",
        }

        amber_values = {
            "NO",
            "NOT SUBMITTED",
            "NOT PREVIEWED",
            "ELIGIBLE - LIMIT REACHED",
            "PARTIAL",
            "WARNING",
        }

        if normalised in green_values:
            return {
                "red": 0.82,
                "green": 0.94,
                "blue": 0.84,
            }

        if normalised in red_values:
            return {
                "red": 0.98,
                "green": 0.82,
                "blue": 0.82,
            }

        if normalised in amber_values:
            return {
                "red": 1.0,
                "green": 0.93,
                "blue": 0.72,
            }

        if (
            "EXCLUDED" in normalised
            or "LOW IEX RELIABILITY" in normalised
        ):
            return {
                "red": 0.98,
                "green": 0.82,
                "blue": 0.82,
            }

        return None

    def format_worksheet(self, worksheet) -> None:
        """
        Apply consistent professional formatting to a worksheet.

        This does not delete, rename, or replace any data.
        """
        values = worksheet.get_all_values()

        if not values:
            return

        columns = values[0]
        row_count = max(len(values), 2)
        column_count = max(len(columns), 1)
        sheet_id = worksheet.id

        # Keep columns wide enough that words are not displayed
        # one letter per line. Long columns are capped so the
        # worksheet remains easy to scan.
        column_widths = []

        for column_index in range(column_count):
            cell_values = [
                str(row[column_index])
                for row in values
                if column_index < len(row)
            ]

            longest_word = max(
                (
                    len(word)
                    for value in cell_values
                    for word in value.split()
                ),
                default=0,
            )

            longest_cell = max(
                (
                    len(value)
                    for value in cell_values
                ),
                default=0,
            )

            width = max(
                100,
                longest_word * 8 + 28,
                min(
                    longest_cell * 7 + 28,
                    240,
                ),
            )

            column_widths.append(
                min(width, 260)
            )

        header_background = {
            "red": 0.09,
            "green": 0.20,
            "blue": 0.33,
        }

        body_background = {
            "red": 1.0,
            "green": 1.0,
            "blue": 1.0,
        }

        border_colour = {
            "red": 0.80,
            "green": 0.83,
            "blue": 0.87,
        }

        requests = [
            {
                "updateSheetProperties": {
                    "properties": {
                        "sheetId": sheet_id,
                        "gridProperties": {
                            "frozenRowCount": 1,
                        },
                    },
                    "fields": (
                        "gridProperties.frozenRowCount"
                    ),
                }
            },
            {
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": 0,
                        "endRowIndex": 1,
                        "startColumnIndex": 0,
                        "endColumnIndex": column_count,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "backgroundColor": header_background,
                            "textFormat": {
                                "foregroundColor": {
                                    "red": 1,
                                    "green": 1,
                                    "blue": 1,
                                },
                                "bold": True,
                                "fontSize": 10,
                            },
                            "horizontalAlignment": "CENTER",
                            "verticalAlignment": "MIDDLE",
                            "wrapStrategy": "WRAP",
                            "borders": {
                                "bottom": {
                                    "style": "SOLID_MEDIUM",
                                    "color": border_colour,
                                }
                            },
                        }
                    },
                    "fields": "userEnteredFormat",
                }
            },
            {
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": 1,
                        "endRowIndex": row_count,
                        "startColumnIndex": 0,
                        "endColumnIndex": column_count,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "backgroundColor": body_background,
                            "verticalAlignment": "MIDDLE",
                            "wrapStrategy": "CLIP",
                            "textFormat": {
                                "fontSize": 10,
                                "foregroundColor": {
                                    "red": 0.0,
                                    "green": 0.0,
                                    "blue": 0.0,
                                },
                            },
                            "borders": {
                                "bottom": {
                                    "style": "SOLID",
                                    "color": border_colour,
                                }
                            },
                        }
                    },
                    "fields": "userEnteredFormat",
                }
            },
                    *[
            {
                "updateDimensionProperties": {
                    "range": {
                        "sheetId": sheet_id,
                        "dimension": "COLUMNS",
                        "startIndex": column_index,
                        "endIndex": column_index + 1,
                    },
                    "properties": {
                        "pixelSize": pixel_width,
                    },
                    "fields": "pixelSize",
                }
            }
            for column_index, pixel_width
            in enumerate(column_widths)
        ],

            {
                "updateDimensionProperties": {
                    "range": {
                        "sheetId": sheet_id,
                        "dimension": "ROWS",
                        "startIndex": 0,
                        "endIndex": 1,
                    },
                    "properties": {
                        "pixelSize": 38,
                    },
                    "fields": "pixelSize",
                }
            },
        ]

        currency_four_decimals = {
            "Open",
            "High",
            "Low",
            "Close",
            "Average Price",
            "Average Range",
            "Prev Day Range (ATR)",
            "ATR x 0.25",
            "Candle Range",
            "Limit Buy",
            "Limit Sell",
            "Stop Loss",
            "Trading Stop Loss",
            "Running High",
            "Running Low",
            "VWAP",
        }

        currency_two_decimals = {
            "Estimated Cost",
            "Estimated Fee",
            "Buy Price",
            "Sell Price",
            "Profit/Loss",
            "Total P&L",
        }

        integer_columns = {
            "Valid Bars",
            "Average Volume",
            "Volume",
            "Trade Count",
            "Quantity",
            "Scanner Rows",
            "Selected Symbols",
            "Strategy Rows",
            "Invest Signals",
            "Order Previews",
            "Orders Submitted",
        }

        percentage_columns = {
            "Average Range %",
            "Reliability",
            "Completeness",
            "Return %",
        }

        date_columns = {
            "Date",
        }

        time_columns = {
            "Last Update Time",
            "Timestamp UTC",
            "Timestamp ET",
            "Completed At",
            "Last Updated",
        }

        left_aligned_columns = {
            "Decision",
            "Proximity to High/Low",
        }

        for index, column in enumerate(columns):
            column_range = {
                "sheetId": sheet_id,
                "startRowIndex": 1,
                "endRowIndex": row_count,
                "startColumnIndex": index,
                "endColumnIndex": index + 1,
            }

            if column in currency_four_decimals:
                number_format = {
                    "type": "CURRENCY",
                    "pattern": "$#,##0.0000",
                }
            elif column in currency_two_decimals:
                number_format = {
                    "type": "CURRENCY",
                    "pattern": "$#,##0.00",
                }
            elif column in integer_columns:
                number_format = {
                    "type": "NUMBER",
                    "pattern": "#,##0",
                }
            elif column in percentage_columns:
                number_format = {
                    "type": "NUMBER",
                    "pattern": '0.00"%"',
                }
            elif column in date_columns:
                number_format = {
                    "type": "DATE",
                    "pattern": "yyyy-mm-dd",
                }
            elif column in time_columns:
                number_format = {
                    "type": "DATE_TIME",
                    "pattern": "yyyy-mm-dd hh:mm:ss",
                }
            else:
                number_format = None

            if number_format is not None:
                requests.append(
                    {
                        "repeatCell": {
                            "range": column_range,
                            "cell": {
                                "userEnteredFormat": {
                                    "numberFormat": number_format,
                                }
                            },
                            "fields": (
                                "userEnteredFormat.numberFormat"
                            ),
                        }
                    }
                )

            alignment = (
                "LEFT"
                if column in left_aligned_columns
                else "CENTER"
            )

            requests.append(
                {
                    "repeatCell": {
                        "range": column_range,
                        "cell": {
                            "userEnteredFormat": {
                                "horizontalAlignment": alignment,
                            }
                        },
                        "fields": (
                            "userEnteredFormat."
                            "horizontalAlignment"
                        ),
                    }
                }
            )

        # Give every worksheet a complete table grid so each
        # populated cell reads as part of one professional table.
        requests.append(
            {
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": 0,
                        "endRowIndex": row_count,
                        "startColumnIndex": 0,
                        "endColumnIndex": column_count,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "borders": {
                                "top": {
                                    "style": "SOLID",
                                    "color": border_colour,
                                },
                                "bottom": {
                                    "style": "SOLID",
                                    "color": border_colour,
                                },
                                "left": {
                                    "style": "SOLID",
                                    "color": border_colour,
                                },
                                "right": {
                                    "style": "SOLID",
                                    "color": border_colour,
                                },
                            }
                        }
                    },
                    "fields": "userEnteredFormat.borders",
                }
            }
        )

        if worksheet.title == "Daily Trade P&L":
            pnl_column_widths = [
                110,  # Date
                90,   # Symbol
                85,   # Quantity
                105,  # Buy Price
                105,  # Sell Price
                115,  # Profit/Loss
                95,   # Return %
                120,  # Total P&L
            ]

            for column_index, pixel_width in enumerate(
                pnl_column_widths
            ):
                requests.append(
                    {
                        "updateDimensionProperties": {
                            "range": {
                                "sheetId": sheet_id,
                                "dimension": "COLUMNS",
                                "startIndex": column_index,
                                "endIndex": column_index + 1,
                            },
                            "properties": {
                                "pixelSize": pixel_width,
                            },
                            "fields": "pixelSize",
                        }
                    }
                )

            # Give every table cell a complete border so the
            # ledger reads as one coherent professional table.
            requests.append(
                {
                    "repeatCell": {
                        "range": {
                            "sheetId": sheet_id,
                            "startRowIndex": 0,
                            "endRowIndex": row_count,
                            "startColumnIndex": 0,
                            "endColumnIndex": 8,
                        },
                        "cell": {
                            "userEnteredFormat": {
                                "borders": {
                                    "top": {
                                        "style": "SOLID",
                                        "color": border_colour,
                                    },
                                    "bottom": {
                                        "style": "SOLID",
                                        "color": border_colour,
                                    },
                                    "left": {
                                        "style": "SOLID",
                                        "color": border_colour,
                                    },
                                    "right": {
                                        "style": "SOLID",
                                        "color": border_colour,
                                    },
                                }
                            }
                        },
                        "fields": "userEnteredFormat.borders",
                    }
                }
            )

            # Symbol column: bold for quick scanning.
            requests.append(
                {
                    "repeatCell": {
                        "range": {
                            "sheetId": sheet_id,
                            "startRowIndex": 1,
                            "endRowIndex": row_count,
                            "startColumnIndex": 1,
                            "endColumnIndex": 2,
                        },
                        "cell": {
                            "userEnteredFormat": {
                                "textFormat": {
                                    "bold": True,
                                }
                            }
                        },
                        "fields": (
                            "userEnteredFormat.textFormat.bold"
                        ),
                    }
                }
            )

            # Total P&L column gets stronger visual emphasis.
            requests.append(
                {
                    "repeatCell": {
                        "range": {
                            "sheetId": sheet_id,
                            "startRowIndex": 1,
                            "endRowIndex": row_count,
                            "startColumnIndex": 7,
                            "endColumnIndex": 8,
                        },
                        "cell": {
                            "userEnteredFormat": {
                                "textFormat": {
                                    "bold": True,
                                }
                            }
                        },
                        "fields": (
                            "userEnteredFormat.textFormat.bold"
                        ),
                    }
                }
            )

            positive_background = {
                "red": 0.86,
                "green": 0.95,
                "blue": 0.88,
            }

            negative_background = {
                "red": 0.98,
                "green": 0.86,
                "blue": 0.86,
            }

            # Profit/Loss is column F; Total P&L is column H.
            for row_index, row in enumerate(
                values[1:],
                start=1,
            ):
                for pnl_column_index in (5, 7):
                    if pnl_column_index >= len(row):
                        continue

                    raw_value = str(
                        row[pnl_column_index]
                    ).replace(
                        "$",
                        "",
                    ).replace(
                        ",",
                        "",
                    ).strip()

                    try:
                        pnl_value = float(raw_value)
                    except ValueError:
                        continue

                    if pnl_value > 0:
                        background = positive_background
                    elif pnl_value < 0:
                        background = negative_background
                    else:
                        continue

                    requests.append(
                        {
                            "repeatCell": {
                                "range": {
                                    "sheetId": sheet_id,
                                    "startRowIndex": row_index,
                                    "endRowIndex": row_index + 1,
                                    "startColumnIndex": pnl_column_index,
                                    "endColumnIndex": pnl_column_index + 1,
                                },
                                "cell": {
                                    "userEnteredFormat": {
                                        "backgroundColor": background,
                                        "textFormat": {
                                            "bold": True,
                                            "foregroundColor": {
                                                "red": 0.0,
                                                "green": 0.0,
                                                "blue": 0.0,
                                            },
                                        },
                                    }
                                },
                                "fields": (
                                    "userEnteredFormat."
                                    "backgroundColor,"
                                    "userEnteredFormat."
                                    "textFormat.bold,"
                                    "userEnteredFormat."
                                    "textFormat.foregroundColor"
                                ),
                            }
                        }
                    )

        for row_index, row in enumerate(values[1:], start=1):
            for column_index, value in enumerate(row):
                colour = self._status_colour(value)

                if colour is None:
                    continue

                requests.append(
                    {
                        "repeatCell": {
                            "range": {
                                "sheetId": sheet_id,
                                "startRowIndex": row_index,
                                "endRowIndex": row_index + 1,
                                "startColumnIndex": column_index,
                                "endColumnIndex": column_index + 1,
                            },
                            "cell": {
                                "userEnteredFormat": {
                                    "backgroundColor": colour,
                                    "textFormat": {
                                        "bold": True,
                                    },
                                    "horizontalAlignment": "CENTER",
                                }
                            },
                            "fields": (
                                "userEnteredFormat."
                                "backgroundColor,"
                                "userEnteredFormat."
                                "textFormat.bold,"
                                "userEnteredFormat."
                                "horizontalAlignment"
                            ),
                        }
                    }
                )

        self.spreadsheet.batch_update(
            {
                "requests": requests,
            }
        )

    def format_all_sheets(self) -> None:
        """
        Apply professional formatting to every worksheet in the
        workbook.
        """
        formatted = 0

        for worksheet in self.spreadsheet.worksheets():
            try:
                self.format_worksheet(worksheet)
                formatted += 1
            except Exception as error:
                print(
                    f"Formatting skipped for {worksheet.title}: "
                    f"{error}"
                )

        print(
            f"{formatted} worksheet(s) professionally formatted."
        )

    @staticmethod
    def _sheet_rows_for_date(
        worksheet,
        date_str: str,
    ) -> tuple[list[str], list[list[str]]]:
        values = worksheet.get_all_values()

        if not values:
            return [], []

        columns = values[0]
        rows = [
            row
            for row in values[1:]
            if row and row[0] == date_str
        ]

        return columns, rows

    def write_daily_summary(
        self,
        date_str: str,
    ) -> None:
        """
        Build one permanent summary row for a trading date.
        """
        scanner_rows = []
        strategy_rows = []
        order_rows = []

        try:
            _, scanner_rows = self._sheet_rows_for_date(
                self.spreadsheet.worksheet(
                    "Scanner Dashboard"
                ),
                date_str,
            )
        except gspread.exceptions.WorksheetNotFound:
            pass

        try:
            strategy_columns, strategy_rows = (
                self._sheet_rows_for_date(
                    self.spreadsheet.worksheet("Invest"),
                    date_str,
                )
            )
        except gspread.exceptions.WorksheetNotFound:
            strategy_columns = []

        try:
            order_columns, order_rows = (
                self._sheet_rows_for_date(
                    self.spreadsheet.worksheet("Orders"),
                    date_str,
                )
            )
        except gspread.exceptions.WorksheetNotFound:
            order_columns = []

        selected_count = 0
        for row in scanner_rows:
            if len(row) > 9 and row[9].strip().upper() == "YES":
                selected_count += 1

        signal_index = (
            strategy_columns.index("Signal")
            if "Signal" in strategy_columns
            else -1
        )

        invest_count = sum(
            1
            for row in strategy_rows
            if (
                signal_index >= 0
                and len(row) > signal_index
                and row[signal_index].strip().upper() == "INVEST"
            )
        )

        preview_index = (
            order_columns.index("Webull Preview")
            if "Webull Preview" in order_columns
            else -1
        )

        submitted_index = (
            order_columns.index("Submitted")
            if "Submitted" in order_columns
            else -1
        )

        preview_count = sum(
            1
            for row in order_rows
            if (
                preview_index >= 0
                and len(row) > preview_index
                and row[preview_index].strip().upper()
                == "PREVIEW READY"
            )
        )

        submitted_count = sum(
            1
            for row in order_rows
            if (
                submitted_index >= 0
                and len(row) > submitted_index
                and row[submitted_index].strip().upper()
                in {"YES", "TRUE", "SUBMITTED"}
            )
        )

        from datetime import datetime
        from zoneinfo import ZoneInfo

        completed_at = datetime.now(
            ZoneInfo("America/New_York")
        ).strftime("%Y-%m-%d %H:%M:%S")

        columns = [
            "Date",
            "Scanner Rows",
            "Selected Symbols",
            "Strategy Rows",
            "Invest Signals",
            "Order Previews",
            "Orders Submitted",
            "Last Updated",
            "Status",
        ]

        row = [
            date_str,
            len(scanner_rows),
            selected_count,
            len(strategy_rows),
            invest_count,
            preview_count,
            submitted_count,
            completed_at,
            "COMPLETE",
        ]

        worksheet = self.get_or_create_worksheet(
            title="Daily Summary",
            rows=250,
            cols=len(columns),
        )

        self._replace_date_rows(
            worksheet=worksheet,
            columns=columns,
            date_str=date_str,
            replacement_rows=[row],
            last_column="I",
            sheet_name="Daily Summary",
        )

    def write_paper_performance(
        self,
        *,
        report,
    ) -> None:
        """
        Store one LOCAL PAPER performance summary row.

        This worksheet reports simulated Webull paper outcomes
        only. It does not represent broker-submitted orders.
        """
        columns = [
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

        row = [
            report.date,
            report.orders_approved,
            report.trades_entered,
            report.open_trades,
            report.closed_trades,
            report.no_entry,
            report.target_exits,
            report.stop_exits,
            report.time_exits,
            report.profitable_trades,
            report.losing_trades,
            report.breakeven_trades,
            (
                ""
                if report.win_rate_pct is None
                else report.win_rate_pct
            ),
            report.realized_pnl,
            (
                ""
                if report.average_pnl_per_trade is None
                else report.average_pnl_per_trade
            ),
            (
                ""
                if report.average_return_pct is None
                else report.average_return_pct
            ),
            (
                ""
                if report.average_winner is None
                else report.average_winner
            ),
            (
                ""
                if report.average_loser is None
                else report.average_loser
            ),
            (
                ""
                if report.expectancy_per_trade is None
                else report.expectancy_per_trade
            ),
            (
                ""
                if report.average_mfe_pct is None
                else report.average_mfe_pct
            ),
            (
                ""
                if report.average_mae_pct is None
                else report.average_mae_pct
            ),
            report.best_trade_symbol or "",
            (
                ""
                if report.best_trade_pnl is None
                else report.best_trade_pnl
            ),
            report.worst_trade_symbol or "",
            (
                ""
                if report.worst_trade_pnl is None
                else report.worst_trade_pnl
            ),
        ]

        worksheet = self.get_or_create_worksheet(
            title="Paper Performance",
            rows=500,
            cols=len(columns),
        )

        self._replace_date_rows(
            worksheet=worksheet,
            columns=columns,
            date_str=report.date,
            replacement_rows=[row],
            last_column="Y",
            sheet_name="Paper Performance",
        )

    def write_paper_analytics(
        self,
        *,
        date_str: str,
        report,
    ) -> None:
        """
        Store cumulative LOCAL PAPER analytics by dimension.

        This worksheet contains simulated paper-trading analysis
        only. It does not represent broker-submitted activity.
        """
        columns = [
            "Date",
            "Dimension",
            "Group",
            "Approved Orders",
            "Entered Trades",
            "Closed Trades",
            "No Entry",
            "Wins",
            "Losses",
            "Breakeven",
            "Target Exits",
            "Stop Exits",
            "Time Exits",
            "Win Rate %",
            "Realized P&L",
            "Average P&L / Trade",
            "Average Return %",
            "Expectancy / Trade",
            "Average MFE %",
            "Average MAE %",
            "Sample Label",
            "Simulation Only",
            "Broker Submitted",
        ]

        dimensions = [
            ("SYMBOL", report.by_symbol),
            ("ENTRY TIME", report.by_entry_time),
            ("REWARD/RISK", report.by_reward_risk),
            ("IMPULSE ATR", report.by_impulse_atr),
            (
                "PULLBACK VOLUME",
                report.by_pullback_volume,
            ),
            (
                "CONFIRMATION TIME",
                report.by_confirmation_time,
            ),
        ]

        rows = []

        for dimension, groups in dimensions:
            for group in groups:
                rows.append([
                    date_str,
                    dimension,
                    group.key,
                    group.approved_orders,
                    group.entered_trades,
                    group.closed_trades,
                    group.no_entry,
                    group.wins,
                    group.losses,
                    group.breakeven,
                    group.target_exits,
                    group.stop_exits,
                    group.time_exits,
                    (
                        ""
                        if group.win_rate_pct is None
                        else group.win_rate_pct
                    ),
                    group.realized_pnl,
                    (
                        ""
                        if group.average_pnl_per_trade
                        is None
                        else group.average_pnl_per_trade
                    ),
                    (
                        ""
                        if group.average_return_pct
                        is None
                        else group.average_return_pct
                    ),
                    (
                        ""
                        if group.expectancy_per_trade
                        is None
                        else group.expectancy_per_trade
                    ),
                    (
                        ""
                        if group.average_mfe_pct is None
                        else group.average_mfe_pct
                    ),
                    (
                        ""
                        if group.average_mae_pct is None
                        else group.average_mae_pct
                    ),
                    group.sample_label,
                    "YES",
                    "NO",
                ])

        worksheet = self.get_or_create_worksheet(
            title="Paper Analytics",
            rows=1000,
            cols=len(columns),
        )

        self._replace_date_rows(
            worksheet=worksheet,
            columns=columns,
            date_str=date_str,
            replacement_rows=rows,
            last_column="W",
            sheet_name="Paper Analytics",
        )

    def write_paper_portfolio(
        self,
        *,
        date_str: str,
        portfolio,
        risk_status=None,
    ) -> None:
        """
        Store one LOCAL PAPER portfolio snapshot.

        This worksheet represents simulated account state only.
        It does not represent Webull broker balances, positions,
        buying power, or submitted orders.
        """
        columns = [
            "Date",
            "Starting Cash",
            "Cash",
            "Buying Power",
            "Open Cost Basis",
            "Market Value",
            "Realized P&L",
            "Unrealized P&L",
            "Total P&L",
            "Equity",
            "Open Positions",
            "Closed Positions",
            "Pending Orders",
            "No Entry",
            "Overdrawn",
            "Trading Allowed",
            "Risk Reason",
            "Available for New Orders",
            "Pending Reserved Cash",
            "Daily Realized P&L",
            "Daily Loss Limit",
            "Remaining Daily Loss",
            "Simulation Only",
            "Broker Submitted",
        ]

        row = [
            date_str,
            portfolio.starting_cash,
            portfolio.cash,
            portfolio.buying_power,
            portfolio.open_cost_basis,
            portfolio.market_value,
            portfolio.realized_pnl,
            portfolio.unrealized_pnl,
            portfolio.total_pnl,
            portfolio.equity,
            portfolio.open_position_count,
            portfolio.closed_position_count,
            portfolio.pending_order_count,
            portfolio.no_entry_count,
            (
                "YES"
                if portfolio.overdrawn
                else "NO"
            ),
            (
                "UNKNOWN"
                if risk_status is None
                else (
                    "YES"
                    if risk_status.trading_allowed
                    else "NO"
                )
            ),
            (
                "RISK STATUS UNAVAILABLE"
                if risk_status is None
                else risk_status.reason
            ),
            (
                ""
                if risk_status is None
                else risk_status.available_for_new_orders
            ),
            (
                ""
                if risk_status is None
                else risk_status.pending_reserved_cash
            ),
            (
                ""
                if risk_status is None
                else risk_status.daily_realized_pnl
            ),
            (
                ""
                if risk_status is None
                else risk_status.max_daily_loss
            ),
            (
                ""
                if risk_status is None
                else risk_status.remaining_daily_loss
            ),
            "YES",
            "NO",
        ]

        worksheet = self.get_or_create_worksheet(
            title="Paper Portfolio",
            rows=500,
            cols=len(columns),
        )

        self._replace_date_rows(
            worksheet=worksheet,
            columns=columns,
            date_str=date_str,
            replacement_rows=[row],
            last_column="X",
            sheet_name="Paper Portfolio",
        )


    def write_production_run(
        self,
        date_str: str,
    ) -> None:
        """
        Store one end-of-day production audit record.
        """
        import os
        from datetime import datetime
        from zoneinfo import ZoneInfo

        completed_at = datetime.now(
            ZoneInfo("America/New_York")
        ).strftime("%Y-%m-%d %H:%M:%S")

        columns = [
            "Date",
            "Completed At",
            "Run Mode",
            "Data Feed",
            "Strategy Status",
            "Sheets Status",
            "Webull Status",
            "Submitted",
            "Overall Status",
        ]

        row = [
            date_str,
            completed_at,
            os.getenv("TRADING_RUN_MODE", "MANUAL"),
            os.getenv("ALPACA_DATA_FEED", "iex").upper(),
            "COMPLETE",
            "COMPLETE",
            (
                "PREVIEW ONLY"
                if os.getenv(
                    "WEBULL_PREVIEW_ENABLED",
                    "false",
                ).lower() == "true"
                else "DISABLED"
            ),
            "NO",
            "COMPLETE",
        ]

        worksheet = self.get_or_create_worksheet(
            title="Production Runs",
            rows=250,
            cols=len(columns),
        )

        self._replace_date_rows(
            worksheet=worksheet,
            columns=columns,
            date_str=date_str,
            replacement_rows=[row],
            last_column="I",
            sheet_name="Production Runs",
        )


    def refresh_today_sheet(
        self,
        date_str: str,
    ) -> None:
        """
        Build a clean user-facing view for one trading date.

        Historical data remains stored in the archive worksheets.
        """
        sections: list[list] = []

        sections.extend(
            [
                ["TRADING DESK — TODAY"],
                ["Trading Date", date_str],
                ["Execution Mode", "WEBULL PREVIEW ONLY"],
                ["Orders Submitted Automatically", "NO"],
                [],
            ]
        )

        try:
            summary_sheet = self.spreadsheet.worksheet(
                "Daily Summary"
            )
            summary_columns, summary_rows = (
                self._sheet_rows_for_date(
                    summary_sheet,
                    date_str,
                )
            )
        except gspread.exceptions.WorksheetNotFound:
            summary_columns = []
            summary_rows = []

        sections.append(["DAILY SUMMARY"])

        if summary_rows:
            summary = summary_rows[-1]

            for index, column in enumerate(summary_columns):
                value = (
                    summary[index]
                    if index < len(summary)
                    else ""
                )
                sections.append([column, value])
        else:
            sections.append(
                ["Status", "No daily summary available"]
            )

        sections.append([])
        sections.append(
            [
                "TODAY'S ORDERS",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
            ]
        )

        order_columns = [
            "Date",
            "Symbol",
            "Limit Buy",
            "Limit Sell",
            "Trading Stop Loss",
            "Webull Preview",
            "Quantity",
            "Estimated Position Value",
            "Maximum Position Value",
            "Sizing Constraint",
            "Estimated Cost",
            "Estimated Fee",
            "Submitted",
        ]

        try:
            orders_sheet = self.spreadsheet.worksheet("Orders")
            existing_columns, order_rows = (
                self._sheet_rows_for_date(
                    orders_sheet,
                    date_str,
                )
            )

            if existing_columns:
                order_columns = existing_columns
        except gspread.exceptions.WorksheetNotFound:
            order_rows = []

        sections.append(order_columns)

        if order_rows:
            sections.extend(order_rows)
        else:
            sections.append(
                [
                    date_str,
                    "No INVEST orders",
                    "",
                    "",
                    "",
                    "NOT PREVIEWED",
                    "",
                    "",
                    "",
                    "NO",
                ]
            )

        sections.append([])
        sections.append(
            [
                "TODAY'S STRATEGY RESULTS",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
            ]
        )

        try:
            invest_sheet = self.spreadsheet.worksheet("Invest")
            invest_columns, invest_rows = (
                self._sheet_rows_for_date(
                    invest_sheet,
                    date_str,
                )
            )
        except gspread.exceptions.WorksheetNotFound:
            invest_columns = []
            invest_rows = []

        if invest_columns:
            sections.append(invest_columns)
            sections.extend(invest_rows)
        else:
            sections.append(
                ["Status", "No strategy results available"]
            )

        maximum_columns = max(
            len(row)
            for row in sections
            if row
        )

        normalised_rows = [
            self._normalise_row(
                row=row,
                column_count=maximum_columns,
            )
            for row in sections
        ]

        worksheet = self.get_or_create_worksheet(
            title="Today",
            rows=max(150, len(normalised_rows) + 20),
            cols=maximum_columns,
        )

        last_column = self._column_name(maximum_columns)

        worksheet.clear()
        worksheet.resize(
            rows=max(150, len(normalised_rows) + 20),
            cols=maximum_columns,
        )
        worksheet.update(
            range_name=(
                f"A1:{last_column}{len(normalised_rows)}"
            ),
            values=normalised_rows,
            value_input_option="USER_ENTERED",
        )

        self.format_worksheet(worksheet)

        print(
            f"Today sheet refreshed for {date_str}."
        )


    @staticmethod
    def _history_sort_key(row: list) -> str:
        """
        Return the Date value used to sort historical rows.

        Dates are stored as YYYY-MM-DD, so descending text order is
        also descending chronological order.
        """
        if not row:
            return ""

        return str(row[0]).strip()

    def sort_history_sheets(self) -> None:
        """
        Sort every historical worksheet newest-date first.

        Only worksheets whose first header is Date are changed.
        User-facing worksheets such as Today are left unchanged.
        """
        excluded_titles = {
            "Today",
            "Dashboard",
        }

        sorted_count = 0

        for worksheet in self.spreadsheet.worksheets():
            if worksheet.title in excluded_titles:
                continue

            values = worksheet.get_all_values()

            if not values:
                continue

            columns = values[0]

            if not columns or columns[0].strip() != "Date":
                continue

            column_count = len(columns)
            dated_rows = []
            undated_rows = []

            for row in values[1:]:
                normalised = self._normalise_row(
                    row=row,
                    column_count=column_count,
                )

                if self._history_sort_key(normalised):
                    dated_rows.append(normalised)
                else:
                    undated_rows.append(normalised)

            dated_rows.sort(
                key=self._history_sort_key,
                reverse=True,
            )

            ordered_rows = [
                *dated_rows,
                *undated_rows,
            ]

            self._rewrite_table(
                worksheet=worksheet,
                columns=columns,
                rows=ordered_rows,
                last_column=self._column_name(column_count),
            )

            sorted_count += 1

        print(
            f"{sorted_count} historical worksheet(s) sorted "
            "newest first."
        )

    def finalise_daily_workbook(
        self,
        date_str: str,
    ) -> None:
        """
        Complete the permanent daily archive and professionally
        format every worksheet.
        """
        self.write_daily_summary(date_str)
        self.write_production_run(date_str)
        self.sort_history_sheets()
        self.refresh_today_sheet(date_str)
        self.format_all_sheets()

        print(
            f"Google Sheets daily archive finalised for "
            f"{date_str}."
        )


    @staticmethod
    def _normalise_bar_timestamp(
        timestamp: str,
    ) -> tuple[str, str]:
        """
        Return UTC and New York timestamp labels for one Alpaca bar.
        """
        from datetime import datetime
        from zoneinfo import ZoneInfo

        raw = str(timestamp).strip()

        if not raw:
            return "", ""

        parsed = datetime.fromisoformat(
            raw.replace("Z", "+00:00")
        )

        if parsed.tzinfo is None:
            parsed = parsed.replace(
                tzinfo=ZoneInfo("UTC")
            )

        utc_value = parsed.astimezone(
            ZoneInfo("UTC")
        )
        eastern_value = parsed.astimezone(
            ZoneInfo("America/New_York")
        )

        return (
            utc_value.strftime("%Y-%m-%d %H:%M:%S"),
            eastern_value.strftime("%Y-%m-%d %H:%M:%S"),
        )

    def write_minute_bars_history(
        self,
        date_str: str,
        stocks: dict | None = None,
        data_feed: str = "iex",
        source: str = "LIVE",
        bars_by_symbol: dict | None = None,
    ) -> None:
        """
        Store every genuine reconciled one-minute bar permanently.

        Rows for the supplied date are rebuilt from the current
        in-memory bars. All other historical dates are preserved.
        """
        columns = [
            "Date",
            "Symbol",
            "Timestamp ET",
            "Open",
            "High",
            "Low",
            "Close",
            "Volume",
            "Trade Count",
            "VWAP",
            "Data Feed",
            "Source",
        ]

        worksheet = self.get_or_create_worksheet(
            title="Minute Bars History",
            rows=2000,
            cols=len(columns),
        )

        unique_rows: dict[
            tuple[str, str],
            list,
        ] = {}

        if bars_by_symbol is None:
            if stocks is None:
                raise ValueError(
                    "stocks or bars_by_symbol is required."
                )

            source_bars = {
                stock.symbol: stock.minute_bars
                for stock in stocks.values()
            }
        else:
            source_bars = bars_by_symbol

        for symbol, bars in source_bars.items():
            for bar in bars:
                raw_timestamp = str(
                    bar.get("t", "")
                ).strip()

                if not raw_timestamp:
                    continue

                timestamp_utc, timestamp_et = (
                    self._normalise_bar_timestamp(
                        raw_timestamp
                    )
                )

                key = (
                    symbol,
                    timestamp_utc,
                )

                unique_rows[key] = [
                    date_str,
                    symbol,
                    timestamp_et,
                    bar.get("o", ""),
                    bar.get("h", ""),
                    bar.get("l", ""),
                    bar.get("c", ""),
                    bar.get("v", ""),
                    bar.get("n", ""),
                    bar.get("vw", ""),
                    data_feed.strip().upper(),
                    source.strip().upper(),
                ]

        history_rows = [
            unique_rows[key]
            for key in sorted(
                unique_rows,
                key=lambda item: (
                    item[0],
                    item[1],
                ),
            )
        ]

        self._replace_date_rows(
            worksheet=worksheet,
            columns=columns,
            date_str=date_str,
            replacement_rows=history_rows,
            last_column="L",
            sheet_name="Minute Bars History",
        )

        print(
            f"{len(history_rows)} genuine minute bar(s) "
            "reconciled in the Minute Bars History sheet."
        )

    @staticmethod
    def _optional_round(
            value,
            digits: int = 4,
    ):
        """
        Round numeric strategy values while preserving missing data.
        """
        if isinstance(value, (int, float)):
            return round(float(value), digits)

        return ""

    @staticmethod
    def _opening_value(
            opening_bar,
            key: str,
    ):
        """
        Safely return one opening-candle value.
        """
        if not isinstance(opening_bar, dict):
            return ""

        value = opening_bar.get(key)

        if isinstance(value, (int, float)):
            return value

        return ""

    def write_strategy_results(
            self,
            date_str: str,
            stocks: dict,
            sheet_name: str = "Invest",
    ) -> None:
        """
        Reconcile strategy-neutral active results in the Invest sheet.

        The standalone Manipulation strategy uses this schema.
        """
        invest_columns = [
            "Date",
            "Symbol",
            "Strategy",
            "Strategy Status",
            "Signal",
            "Entry",
            "Target",
            "Stop Loss",
            "Trading Stop Loss",
            "Reward / Risk",
            "Confirmation Time",
            "Retracement Price",
            "Impulse ATR Multiple",
            "Pullback Volume Ratio",
            "Rejection Reason",
            "Strategy Detail",
            "Prev Day Range (ATR)",
            "Opening Open",
            "Opening High",
            "Opening Low",
            "Opening Close",
            "Candle Range",
            "ATR Threshold",
            "Manipulation Candle",
            "Red Candle",
            "Proximity to High/Low",
        ]

        worksheet = self.get_or_create_worksheet(
            title=sheet_name,
            rows=100,
            cols=len(invest_columns),
        )

        strategy_rows = []

        for stock in stocks.values():
            opening_bar = stock.opening_bar

            strategy_rows.append(
                [
                    date_str,
                    stock.symbol,
                    stock.strategy_name,
                    stock.strategy_status,
                    stock.signal,
                    self._optional_round(
                        stock.limit_buy
                    ),
                    self._optional_round(
                        stock.limit_sell
                    ),
                    self._optional_round(
                        stock.stop_loss
                    ),
                    self._optional_round(
                        stock.trading_stop_loss
                    ),
                    self._optional_round(
                        stock.reward_risk,
                        digits=2,
                    ),
                    stock.confirmation_time,
                    self._optional_round(
                        stock.retracement_price
                    ),
                    self._optional_round(
                        stock.impulse_atr_multiple,
                        digits=3,
                    ),
                    self._optional_round(
                        stock.pullback_volume_ratio,
                        digits=3,
                    ),
                    stock.strategy_rejection_reason,
                    stock.strategy_detail,
                    self._optional_round(stock.atr),
                    self._opening_value(
                        opening_bar,
                        "o",
                    ),
                    self._opening_value(
                        opening_bar,
                        "h",
                    ),
                    self._opening_value(
                        opening_bar,
                        "l",
                    ),
                    self._opening_value(
                        opening_bar,
                        "c",
                    ),
                    self._optional_round(
                        stock.candle_range
                    ),
                    self._optional_round(
                        stock.atr_threshold
                    ),
                    (
                        "YES"
                        if stock.is_manipulation
                        else "NO"
                    ),
                    (
                        "YES"
                        if stock.is_red
                        else "NO"
                    ),
                    stock.proximity,
                ]
            )

        self._replace_date_rows(
            worksheet=worksheet,
            columns=invest_columns,
            date_str=date_str,
            replacement_rows=strategy_rows,
            last_column="Z",
            sheet_name=sheet_name,
        )

        print(
            f"{len(strategy_rows)} strategy row(s) reconciled "
            f"in the {sheet_name} sheet."
        )

    def write_manipulation_selling_pressure_research(
            self,
            date_str: str,
            shadows: dict,
            sheet_name: str = (
                "Manipulation Selling Pressure Research"
            ),
    ) -> None:
        """
        Reconcile forward selling-pressure shadow variants.

        Research only:
        - does not modify the live Manipulation strategy;
        - does not create a Webull preview;
        - does not submit a broker order.
        """
        columns = [
            "Date",
            "Symbol",
            "Close Location",
            "Relative Volume",
            "Normal Entry",
            "Adaptive Entry",
            "Target",
            "Variant A Stop (1.00x)",
            "Variant B Stop (1.25x)",
            "Variant A Outcome",
            "Variant B Outcome",
        ]

        worksheet = self.get_or_create_worksheet(
            title=sheet_name,
            rows=250,
            cols=len(columns),
        )

        rows = []

        for symbol in sorted(shadows):
            shadow = shadows[symbol]

            if shadow is None:
                continue

            rows.append([
                date_str,
                shadow.symbol,
                self._optional_round(
                    shadow.close_location,
                    digits=4,
                ),
                self._optional_round(
                    shadow.relative_volume,
                    digits=3,
                ),
                self._optional_round(
                    shadow.normal_entry,
                ),
                self._optional_round(
                    shadow.adaptive_entry,
                ),
                self._optional_round(
                    shadow.target,
                ),
                self._optional_round(
                    shadow.variant_a_stop,
                ),
                self._optional_round(
                    shadow.variant_b_stop,
                ),
                shadow.variant_a_outcome,
                shadow.variant_b_outcome,
            ])

        self._replace_date_rows(
            worksheet=worksheet,
            columns=columns,
            date_str=date_str,
            replacement_rows=rows,
            last_column="K",
            sheet_name=sheet_name,
        )

        print(
            f"{len(rows)} selling-pressure research row(s) "
            f"reconciled in the {sheet_name} sheet."
        )

    def write_manipulation_selling_pressure_research(
            self,
            date_str: str,
            shadows: dict,
            sheet_name: str = (
                "Manipulation Selling Pressure Research"
            ),
    ) -> None:
        """
        Reconcile forward selling-pressure shadow variants.

        Research only:
        - does not modify the live Manipulation strategy;
        - does not create a Webull preview;
        - does not submit a broker order.
        """
        columns = [
            "Date",
            "Symbol",
            "Close Location",
            "Relative Volume",
            "Normal Entry",
            "Adaptive Entry",
            "Target",
            "Variant A Stop (1.00x)",
            "Variant B Stop (1.25x)",
            "Variant A Outcome",
            "Variant B Outcome",
        ]

        worksheet = self.get_or_create_worksheet(
            title=sheet_name,
            rows=250,
            cols=len(columns),
        )

        rows = []

        for symbol in sorted(shadows):
            shadow = shadows[symbol]

            if shadow is None:
                continue

            rows.append([
                date_str,
                shadow.symbol,
                self._optional_round(
                    shadow.close_location,
                    digits=4,
                ),
                self._optional_round(
                    shadow.relative_volume,
                    digits=3,
                ),
                self._optional_round(
                    shadow.normal_entry,
                ),
                self._optional_round(
                    shadow.adaptive_entry,
                ),
                self._optional_round(
                    shadow.target,
                ),
                self._optional_round(
                    shadow.variant_a_stop,
                ),
                self._optional_round(
                    shadow.variant_b_stop,
                ),
                shadow.variant_a_outcome,
                shadow.variant_b_outcome,
            ])

        self._replace_date_rows(
            worksheet=worksheet,
            columns=columns,
            date_str=date_str,
            replacement_rows=rows,
            last_column="K",
            sheet_name=sheet_name,
        )

        print(
            f"{len(rows)} selling-pressure research row(s) "
            f"reconciled in the {sheet_name} sheet."
        )

    def write_quick_flip_results(
            self,
            date_str: str,
            results: dict,
            sheet_name: str = "Quick Flip Signals",
    ) -> None:
        """
        Reconcile Quick Flip strategy results for one date.

        Quick Flip is long-only and intentionally has no
        automatic stop-loss field.
        """
        columns = [
            "Date",
            "Symbol",
            "Status",
            "Signal",
            "Pattern",
            "Entry",
            "TP1",
            "TP2",
            "Opening Box High",
            "Opening Box Low",
            "Opening Box Size",
            "ATR14",
            "Liquidity Threshold",
            "Reversal Time",
            "Confirmation Time",
            "Detail",
            "Automatic Stop Loss",
            "Broker Submitted",
        ]

        worksheet = self.get_or_create_worksheet(
            title=sheet_name,
            rows=250,
            cols=len(columns),
        )

        rows = []

        for symbol in sorted(results):
            result = results[symbol]

            if result is None:
                rows.append([
                    date_str,
                    symbol,
                    "NO RESULT",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "NO",
                    "NO",
                ])
                continue

            signal = getattr(
                result,
                "signal",
                None,
            )

            rows.append([
                date_str,
                symbol,
                getattr(
                    result,
                    "status",
                    "",
                ),
                (
                    ""
                    if signal is None
                    else signal.signal
                ),
                (
                    ""
                    if signal is None
                    else signal.pattern
                ),
                (
                    ""
                    if signal is None
                    else self._optional_round(
                        signal.entry_price
                    )
                ),
                (
                    ""
                    if signal is None
                    else self._optional_round(
                        signal.take_profit_1
                    )
                ),
                (
                    ""
                    if signal is None
                    else self._optional_round(
                        signal.take_profit_2
                    )
                ),
                (
                    ""
                    if signal is None
                    else self._optional_round(
                        signal.opening_range_high
                    )
                ),
                (
                    ""
                    if signal is None
                    else self._optional_round(
                        signal.opening_range_low
                    )
                ),
                (
                    ""
                    if signal is None
                    else self._optional_round(
                        signal.opening_range_size
                    )
                ),
                (
                    ""
                    if signal is None
                    else self._optional_round(
                        signal.atr_14
                    )
                ),
                (
                    ""
                    if signal is None
                    else self._optional_round(
                        signal.liquidity_threshold
                    )
                ),
                (
                    ""
                    if signal is None
                    else str(
                        signal.reversal_time
                        or ""
                    )
                ),
                (
                    ""
                    if signal is None
                    else str(
                        signal.confirmation_time
                        or ""
                    )
                ),
                (
                    ""
                    if signal is None
                    else signal.detail
                ),
                "NO",
                "NO",
            ])

        self._replace_date_rows(
            worksheet=worksheet,
            columns=columns,
            date_str=date_str,
            replacement_rows=rows,
            last_column="R",
            sheet_name=sheet_name,
        )

        print(
            f"{len(rows)} Quick Flip result row(s) "
            f"reconciled in the {sheet_name} sheet."
        )

    def write_quick_flip_previews(
            self,
            date_str: str,
            previews: list[dict],
            sheet_name: str = "Quick Flip Previews",
    ) -> None:
        """
        Store Quick Flip Webull previews.

        These rows are preview-only. No automatic stop is
        represented and no broker submission is implied.
        """
        columns = [
            "Date",
            "Symbol",
            "Status",
            "Quantity",
            "Entry",
            "TP1",
            "TP2",
            "Estimated Position Value",
            "Maximum Position Value",
            "Sizing Constraint",
            "Safety Allowed",
            "Safety Reason",
            "Manual Approval Required",
            "Manual Approval Granted",
            "Automatic Stop Loss",
            "Estimated Cost",
            "Estimated Fee",
            "Submitted",
        ]

        worksheet = self.get_or_create_worksheet(
            title=sheet_name,
            rows=250,
            cols=len(columns),
        )

        rows = []

        for preview in previews:
            rows.append([
                date_str,
                preview.get(
                    "symbol",
                    "",
                ),
                preview.get(
                    "status",
                    "",
                ),
                preview.get(
                    "quantity",
                    "",
                ),
                preview.get(
                    "limitBuy",
                    "",
                ),
                preview.get(
                    "takeProfit1",
                    "",
                ),
                preview.get(
                    "takeProfit2",
                    "",
                ),
                preview.get(
                    "estimatedPositionValue",
                    "",
                ),
                preview.get(
                    "maxPositionValue",
                    "",
                ),
                preview.get(
                    "sizingConstraint",
                    "",
                ),
                (
                    "YES"
                    if preview.get(
                        "safetyAllowed"
                    )
                    else "NO"
                ),
                preview.get(
                    "safetyReason",
                    "",
                ),
                (
                    "YES"
                    if preview.get(
                        "manualApprovalRequired"
                    )
                    else "NO"
                ),
                (
                    "YES"
                    if preview.get(
                        "manualApprovalGranted"
                    )
                    else "NO"
                ),
                "NO",
                preview.get(
                    "estimatedCost",
                    "",
                ),
                preview.get(
                    "estimatedTransactionFee",
                    "",
                ),
                "NO",
            ])

        self._replace_date_rows(
            worksheet=worksheet,
            columns=columns,
            date_str=date_str,
            replacement_rows=rows,
            last_column="R",
            sheet_name=sheet_name,
        )

        print(
            f"{len(rows)} Quick Flip preview row(s) "
            f"reconciled in the {sheet_name} sheet."
        )

    def write_webull_trade_pnl(
            self,
            date_str: str,
            trades: list,
            remaining: dict[str, float],
            sheet_name: str = "Daily Trade P&L",
    ) -> None:
        """
        Store a compact realized Webull trade ledger.

        The final column is cumulative realized P&L across all
        rows currently stored on the sheet.

        Data comes only from read-only Webull order history.
        This method cannot submit, replace, or cancel orders.
        """
        columns = [
            "Date",
            "Symbol",
            "Quantity",
            "Buy Price",
            "Sell Price",
            "Profit/Loss",
            "Return %",
            "Total P&L",
        ]

        legacy_columns = [
            "Date",
            "Symbol",
            "Buy Time ET",
            "Sell Time ET",
            "Quantity Closed",
            "Buy Price",
            "Sell Price",
            "Gross Cost",
            "Gross Proceeds",
            "Realized P&L",
            "Return %",
            "Remaining Open Quantity",
            "Status",
            "Source",
        ]

        worksheet = self.get_or_create_worksheet(
            title=sheet_name,
            rows=500,
            cols=len(columns),
        )

        existing_values = (
            worksheet.get_all_values()
            if hasattr(
                worksheet,
                "get_all_values",
            )
            else []
        )

        # Recover from a partially migrated sheet where A:H already
        # contains the compact layout but stale legacy values remain
        # in I:N.
        if (
            existing_values
            and existing_values[0][:len(columns)] == columns
            and len(existing_values[0]) > len(columns)
        ):
            worksheet.batch_clear([
                f"I1:N{max(len(existing_values), 1)}"
            ])

            existing_values = (
                worksheet.get_all_values()
            )

        # Migrate the existing 14-column P&L sheet in place.
        if (
            existing_values
            and existing_values[0] == legacy_columns
        ):
            migrated_rows = []

            for row in existing_values[1:]:
                normalised = self._normalise_row(
                    row=row,
                    column_count=len(legacy_columns),
                )

                if not normalised[0]:
                    continue

                migrated_rows.append([
                    normalised[0],
                    normalised[1],
                    normalised[4],
                    normalised[5],
                    normalised[6],
                    normalised[9],
                    normalised[10],
                    "",
                ])

            running_total = 0.0

            for row in migrated_rows:
                try:
                    running_total += float(row[5])
                except (TypeError, ValueError):
                    pass

                row[7] = round(
                    running_total,
                    2,
                )

            self._rewrite_table(
                worksheet=worksheet,
                columns=columns,
                rows=migrated_rows,
                last_column="H",
            )

            # The worksheet may previously have used columns I:N.
            # Clear them so stale legacy headers/data cannot survive
            # the compact migration.
            worksheet.batch_clear([
                f"I1:N{max(len(existing_values), 1)}"
            ])

            existing_values = (
                worksheet.get_all_values()
            )

        elif (
            existing_values
            and existing_values[0] != columns
        ):
            self._validate_header(
                existing_values=existing_values,
                expected_columns=columns,
                sheet_name=sheet_name,
            )

        # Determine cumulative P&L before this date.
        preserved_pnl = 0.0

        for row in existing_values[1:]:
            normalised = self._normalise_row(
                row=row,
                column_count=len(columns),
            )

            if normalised[0] == date_str:
                continue

            try:
                preserved_pnl += float(
                    normalised[5]
                )
            except (TypeError, ValueError):
                pass

        rows = []
        running_total = preserved_pnl

        for trade in trades:
            running_total += float(
                trade.realized_pnl
            )

            rows.append([
                date_str,
                trade.symbol,
                trade.quantity,
                trade.buy_price,
                trade.sell_price,
                trade.realized_pnl,
                trade.return_pct,
                round(
                    running_total,
                    2,
                ),
            ])

        self._replace_date_rows(
            worksheet=worksheet,
            columns=columns,
            date_str=date_str,
            replacement_rows=rows,
            last_column="H",
            sheet_name=sheet_name,
        )

        # Recalculate every cumulative total after reconciliation.
        # This also keeps totals correct if an older date is rerun.
        if hasattr(
            worksheet,
            "get_all_values",
        ):
            refreshed = worksheet.get_all_values()

            if refreshed:
                reconciled_rows = []

                for row in refreshed[1:]:
                    normalised = self._normalise_row(
                        row=row,
                        column_count=len(columns),
                    )

                    if normalised[0]:
                        reconciled_rows.append(
                            normalised
                        )

                reconciled_rows.sort(
                    key=lambda row: row[0]
                )

                running_total = 0.0

                for row in reconciled_rows:
                    try:
                        running_total += float(
                            row[5]
                        )
                    except (TypeError, ValueError):
                        pass

                    row[7] = round(
                        running_total,
                        2,
                    )

                self._rewrite_table(
                    worksheet=worksheet,
                    columns=columns,
                    rows=reconciled_rows,
                    last_column="H",
                )

        self.format_worksheet(worksheet)

        print(
            f"{len(rows)} realized Webull trade row(s) "
            f"reconciled in the {sheet_name} sheet."
        )

    def write_webull_pnl_summary(
            self,
            summary,
            sheet_name: str = "Daily P&L Summary",
    ) -> None:
        """
        Store one realized Webull P&L summary for a trading date.

        Values are calculated only from matched filled BUY/SELL
        quantities returned by read-only Webull history.
        """
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

        worksheet = self.get_or_create_worksheet(
            title=sheet_name,
            rows=500,
            cols=len(columns),
        )

        row = [
            summary.date,
            summary.closed_trades,
            summary.winning_trades,
            summary.losing_trades,
            summary.breakeven_trades,
            (
                ""
                if summary.win_rate_pct is None
                else summary.win_rate_pct
            ),
            summary.gross_profit,
            summary.gross_loss,
            summary.realized_pnl,
            "WEBULL ORDER HISTORY",
        ]

        self._replace_date_rows(
            worksheet=worksheet,
            columns=columns,
            date_str=summary.date,
            replacement_rows=[row],
            last_column="J",
            sheet_name=sheet_name,
        )

        self.format_worksheet(worksheet)

        print(
            "Webull daily P&L summary reconciled in "
            f"the {sheet_name} sheet."
        )

    def write_trade_previews_today(
            self,
            date_str: str,
            previews: list[dict],
            sheet_name: str = "Trade Previews",
    ) -> None:
        """
        Replace the today-only preview dashboard.

        This sheet intentionally shows only concise preview data.
        Historical detail remains preserved in the strategy-specific
        worksheets.
        """
        columns = [
            "Time",
            "Strategy",
            "Stock",
            "Entry",
            "Exit",
            "Quantity",
            "Status",
        ]

        worksheet = self.get_or_create_worksheet(
            title=sheet_name,
            rows=250,
            cols=len(columns),
        )

        rows = []

        for preview in previews:
            if preview.get("status") != "PREVIEW READY":
                continue

            strategy = str(
                preview.get("strategy", "")
            ).strip()

            symbol = str(
                preview.get("symbol", "")
            ).strip().upper()

            entry = preview.get(
                "entry",
                "",
            )

            exit_value = preview.get(
                "exit",
                "",
            )

            quantity = preview.get(
                "quantity",
                "",
            )

            preview_time = str(
                preview.get(
                    "time",
                    "",
                )
            ).strip()

            rows.append([
                preview_time,
                strategy,
                symbol,
                entry,
                exit_value,
                quantity,
                "PREVIEW READY",
            ])

        worksheet.clear()

        table = [
            columns,
            *rows,
        ]

        last_column = "G"

        worksheet.resize(
            rows=max(250, len(table) + 20),
            cols=len(columns),
        )

        worksheet.update(
            range_name=(
                f"A1:{last_column}{len(table)}"
            ),
            values=table,
            value_input_option="USER_ENTERED",
        )

        self.format_worksheet(
            worksheet
        )

        print(
            f"{len(rows)} current-day preview row(s) "
            f"written to the {sheet_name} sheet "
            f"for {date_str}."
        )

    def write_orders(
            self,
            date_str: str,
            stocks: dict,
            sheet_name: str = "Orders",
    ) -> None:
        order_columns = [
            "Date",
            "Symbol",
            "Limit Buy",
            "Limit Sell",
            "Trading Stop Loss",
            "Webull Preview",
            "Quantity",
            "Estimated Position Value",
            "Maximum Position Value",
            "Sizing Constraint",
            "Estimated Cost",
            "Estimated Fee",
            "Submitted",
        ]

        worksheet = self.get_or_create_worksheet(
            title=sheet_name,
            rows=100,
            cols=len(order_columns),
        )

        order_rows = []

        for stock in stocks.values():
            if stock.signal != "INVEST":
                continue

            order_rows.append(
                [
                    date_str,
                    stock.symbol,
                    round(stock.limit_buy, 4),
                    round(stock.limit_sell, 4),
                    round(stock.trading_stop_loss, 4),
                    (
                        stock.webull_preview.get("status")
                        if stock.webull_preview
                        else "NOT PREVIEWED"
                    ),
                    (
                        stock.webull_preview.get("quantity", "")
                        if stock.webull_preview
                        else ""
                    ),
                    (
                        stock.webull_preview.get(
                            "estimatedPositionValue",
                            "",
                        )
                        if stock.webull_preview
                        else ""
                    ),
                    (
                        stock.webull_preview.get(
                            "maxPositionValue",
                            "",
                        )
                        if stock.webull_preview
                        else ""
                    ),
                    (
                        stock.webull_preview.get(
                            "sizingConstraint",
                            "",
                        )
                        if stock.webull_preview
                        else ""
                    ),
                    (
                        stock.webull_preview.get(
                            "estimatedCost",
                            "",
                        )
                        if stock.webull_preview
                        else ""
                    ),
                    (
                        stock.webull_preview.get(
                            "estimatedTransactionFee",
                            "",
                        )
                        if stock.webull_preview
                        else ""
                    ),
                    "NO",
                ]
            )

        self._replace_date_rows(
            worksheet=worksheet,
            columns=order_columns,
            date_str=date_str,
            replacement_rows=order_rows,
            last_column="M",
            sheet_name=sheet_name,
        )

        if order_rows:
            print(
                f"{len(order_rows)} order(s) reconciled "
                f"in the {sheet_name} sheet."
            )
        else:
            print(
                "No INVEST orders generated. "
                "Existing orders for this date were removed."
            )

    def write_scanner_dashboard(
            self,
            date_str: str,
            statistics,
            selected_symbols,
            scanner,
    ) -> None:
        dashboard_columns = [
            "Date",
            "Symbol",
            "Valid Bars",
            "Average Volume",
            "Average Price",
            "Average Range",
            "Average Range %",
            "Ranking Score",
            "Eligible",
            "Selected",
            "Decision",
        ]

        worksheet = self.get_or_create_worksheet(
            title="Scanner Dashboard",
            rows=100,
            cols=len(dashboard_columns),
        )

        selected_set = set(selected_symbols)
        dashboard_rows = []

        ranked_statistics = sorted(
            statistics,
            key=lambda stats: (
                -stats.ranking_score,
                stats.symbol,
            ),
        )

        for stats in ranked_statistics:
            failures = scanner.eligibility_failures(
                stats
            )
            eligible = not failures
            selected = stats.symbol in selected_set

            if selected:
                decision = "SELECTED"
            elif eligible:
                decision = (
                    "ELIGIBLE - LIMIT REACHED"
                )
            else:
                decision = "; ".join(failures)

            dashboard_rows.append(
                [
                    date_str,
                    stats.symbol,
                    stats.valid_bars,
                    round(stats.avg_volume, 2),
                    round(stats.avg_price, 4),
                    round(stats.avg_range, 4),
                    round(stats.avg_range_pct, 4),
                    round(stats.ranking_score, 4),
                    "YES" if eligible else "NO",
                    "YES" if selected else "NO",
                    decision,
                ]
            )

        self._replace_date_rows(
            worksheet=worksheet,
            columns=dashboard_columns,
            date_str=date_str,
            replacement_rows=dashboard_rows,
            last_column="K",
            sheet_name="Scanner Dashboard",
        )

        print(
            f"{len(dashboard_rows)} scanner row(s) "
            "reconciled in the Scanner Dashboard sheet."
        )
