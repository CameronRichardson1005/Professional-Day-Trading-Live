import time

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

        # Cache worksheet handles so repeated writes during the
        # same live session do not repeatedly fetch worksheet
        # metadata from Google Sheets.
        self._worksheet_cache = {}

        # Cache only tables that this SheetsClient has just written.
        # This lets immediate formatting reuse the exact written
        # values instead of reading the whole worksheet again.
        self._worksheet_values_cache = {}

    @staticmethod
    def _is_sheets_transient_error(
            error: Exception,
    ) -> bool:
        """
        Return True only for transient Google Sheets API 429/503 errors.

        Authentication, permission, schema, worksheet, and other
        API failures must not be silently retried here.
        """
        if not isinstance(
            error,
            gspread.exceptions.APIError,
        ):
            return False

        response = getattr(
            error,
            "response",
            None,
        )

        status_code = getattr(
            response,
            "status_code",
            None,
        )

        if status_code in {429, 503}:
            return True

        error_code = getattr(
            error,
            "code",
            None,
        )

        if error_code in {429, 503}:
            return True

        message = str(error).lower()

        return (
            "[429]" in message
            and "quota" in message
        )

    def _sheets_read_with_quota_retry(
            self,
            func,
            *args,
            label: str = "Google Sheets read",
            max_attempts: int = 3,
            **kwargs,
    ):
        """
        Retry temporary Google Sheets 429 quota and 503 service errors.

        Attempts:
        1. immediate
        2. after 15 seconds
        3. after 30 seconds

        Any non-transient error is raised immediately.
        """
        retry_delays = (
            15,
            30,
        )

        for attempt in range(
            1,
            max_attempts + 1,
        ):
            try:
                return func(
                    *args,
                    **kwargs,
                )

            except Exception as error:
                if not self._is_sheets_transient_error(
                    error
                ):
                    raise

                if attempt >= max_attempts:
                    raise

                delay_index = min(
                    attempt - 1,
                    len(retry_delays) - 1,
                )

                wait_seconds = (
                    retry_delays[
                        delay_index
                    ]
                )

                print(
                    f"{label} hit Google Sheets "
                    f"transient 429/503 error "
                    f"(attempt "
                    f"{attempt}/{max_attempts}). "
                    f"Retrying in "
                    f"{wait_seconds} seconds."
                )

                time.sleep(
                    wait_seconds
                )

        raise RuntimeError(
            f"{label} retry loop exited unexpectedly."
        )

    def _sheets_write_with_transient_retry(
            self,
            func,
            *args,
            label: str = "Google Sheets write",
            max_attempts: int = 3,
            **kwargs,
    ):
        """
        Retry deterministic Google Sheets writes only for
        transient HTTP 429 quota and 503 service errors.

        Callers must use this helper only for writes that are safe
        to repeat without creating duplicate data.
        """
        retry_delays = (
            15,
            30,
        )

        for attempt in range(
            1,
            max_attempts + 1,
        ):
            try:
                return func(
                    *args,
                    **kwargs,
                )

            except Exception as error:
                if not self._is_sheets_transient_error(
                    error
                ):
                    raise

                if attempt >= max_attempts:
                    raise

                delay_index = min(
                    attempt - 1,
                    len(retry_delays) - 1,
                )

                wait_seconds = (
                    retry_delays[
                        delay_index
                    ]
                )

                print(
                    f"{label} hit Google Sheets "
                    f"transient 429/503 error "
                    f"(attempt "
                    f"{attempt}/{max_attempts}). "
                    f"Retrying in "
                    f"{wait_seconds} seconds."
                )

                time.sleep(
                    wait_seconds
                )

        raise RuntimeError(
            f"{label} retry loop exited unexpectedly."
        )

    def get_or_create_worksheet(
        self,
        title: str,
        rows: int = 100,
        cols: int = 20,
    ):
        cache = getattr(
            self,
            "_worksheet_cache",
            None,
        )

        if cache is None:
            cache = {}
            self._worksheet_cache = cache

        if title in cache:
            return cache[title]

        try:
            worksheet = (
                self._sheets_read_with_quota_retry(
                    self.spreadsheet.worksheet,
                    title,
                    label=(
                        "Google Sheets worksheet "
                        f"lookup: {title}"
                    ),
                )
            )

        except gspread.exceptions.WorksheetNotFound:
            worksheet = self.spreadsheet.add_worksheet(
                title=title,
                rows=rows,
                cols=cols,
            )

        cache[title] = worksheet

        return worksheet
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
        existing_row_count: int | None = None,
    ) -> None:
        # Callers that already read the worksheet pass the existing
        # row count so this method does not immediately read the same
        # worksheet a second time.
        if existing_row_count is None:
            existing_row_count = len(
                self._sheets_read_with_quota_retry(
                    worksheet.get_all_values,
                    label=(
                        "Google Sheets table read: "
                        f"{getattr(worksheet, 'title', 'worksheet')}"
                    ),
                )
            )

        table = [columns, *rows]

        self._sheets_write_with_transient_retry(
            worksheet.update,
            values=table,
            range_name=(
                f"A1:{last_column}{len(table)}"
            ),
            value_input_option="USER_ENTERED",
            label=(
                "Google Sheets table write: "
                f"{getattr(worksheet, 'title', 'worksheet')}"
            ),
        )

        if existing_row_count > len(table):
            self._sheets_write_with_transient_retry(
                worksheet.batch_clear,
                [
                    (
                        f"A{len(table) + 1}:"
                        f"{last_column}{existing_row_count}"
                    )
                ],
                label=(
                    "Google Sheets table clear: "
                    f"{getattr(worksheet, 'title', 'worksheet')}"
                ),
            )

        cache = getattr(
            self,
            "_worksheet_values_cache",
            None,
        )

        if cache is None:
            cache = {}
            self._worksheet_values_cache = cache

        cache[
            str(
                getattr(
                    worksheet,
                    "title",
                    "",
                )
            )
        ] = [
            list(row)
            for row in table
        ]

    def _replace_date_rows(
        self,
        worksheet,
        columns: list[str],
        date_str: str,
        replacement_rows: list[list],
        last_column: str,
        sheet_name: str,
    ) -> None:
        existing_values = (
            self._sheets_read_with_quota_retry(
                worksheet.get_all_values,
                label=(
                    "Google Sheets reconciliation read: "
                    f"{sheet_name}"
                ),
            )
        )

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
            existing_row_count=len(
                existing_values
            ),
        )
    def test_connection(self) -> list[str]:
        worksheets = self._sheets_read_with_quota_retry(
            self.spreadsheet.worksheets,
            label="Google Sheets worksheet list",
        )

        return [
            worksheet.title
            for worksheet in worksheets
        ]


    @staticmethod


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

    @staticmethod
    def _append_daily_trade_pnl_formatting_requests(
            *,
            requests: list[dict],
            sheet_id: int,
            row_count: int,
            values: list,
            border_colour: dict,
    ) -> None:
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

    @staticmethod
    def _append_column_formatting_requests(
            *,
            requests: list[dict],
            columns: list,
            sheet_id: int,
            row_count: int,
            currency_four_decimals: set,
            currency_two_decimals: set,
            number_two_decimals: set,
            number_three_decimals: set,
            integer_columns: set,
            percentage_columns: set,
            date_columns: set,
            time_columns: set,
            left_aligned_columns: set,
    ) -> None:
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
            elif column in number_two_decimals:
                number_format = {
                    "type": "NUMBER",
                    "pattern": "0.00",
                }
            elif column in number_three_decimals:
                number_format = {
                    "type": "NUMBER",
                    "pattern": "0.000",
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

    @staticmethod
    def _format_new_york_clock_time(
            value,
    ) -> str:
        """
        Format an aware strategy timestamp as a concise
        America/New_York clock time for Google Sheets display.

        Strategy calculations retain their original datetime
        objects; this changes presentation only.
        """
        if value in {
            None,
            "",
        }:
            return ""

        from datetime import datetime
        from zoneinfo import ZoneInfo

        if isinstance(
            value,
            datetime,
        ):
            timestamp = value
        else:
            try:
                timestamp = datetime.fromisoformat(
                    str(value)
                )
            except ValueError:
                return str(value)

        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(
                tzinfo=ZoneInfo("UTC")
            )

        eastern = timestamp.astimezone(
            ZoneInfo(
                "America/New_York"
            )
        )

        return eastern.strftime(
            "%I:%M %p"
        ).lstrip("0")

    @staticmethod
    def _append_trade_previews_display_requests(
            *,
            requests: list[dict],
            columns: list,
            values: list,
            sheet_id: int,
            row_count: int,
    ) -> None:
        """
        Apply the concise daily Trade Previews display rules.

        These requests affect presentation only. They do not change
        strategy decisions, allocations, reservations, or broker
        behavior.
        """
        column_indexes = {
            str(column): index
            for index, column
            in enumerate(columns)
        }

        def append_number_format(
                column_name: str,
                format_type: str,
                pattern: str,
        ) -> None:
            column_index = (
                column_indexes.get(
                    column_name
                )
            )

            if column_index is None:
                return

            requests.append({
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": 1,
                        "endRowIndex": row_count,
                        "startColumnIndex": (
                            column_index
                        ),
                        "endColumnIndex": (
                            column_index + 1
                        ),
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "numberFormat": {
                                "type": format_type,
                                "pattern": pattern,
                            },
                        },
                    },
                    "fields": (
                        "userEnteredFormat."
                        "numberFormat"
                    ),
                },
            })

        append_number_format(
            "Time",
            "TIME",
            "h:mm AM/PM",
        )

        append_number_format(
            "Entry",
            "CURRENCY",
            "$0.0000",
        )

        # Numeric Manipulation targets receive currency formatting.
        # Quick Flip's combined "TP1 / TP2" text remains unchanged.
        append_number_format(
            "Exit",
            "CURRENCY",
            "$0.0000",
        )

        # Trade Previews stores this as a fractional spreadsheet
        # percentage after USER_ENTERED parsing, so use PERCENT
        # rather than the generic literal-percent formatter.
        append_number_format(
            "Allocation %",
            "PERCENT",
            "0.00%",
        )

        append_number_format(
            "Recommended Allocation $",
            "CURRENCY",
            "$0.00",
        )

        status_index = (
            column_indexes.get(
                "Status"
            )
        )

        if status_index is None:
            return

        ready_background = {
            "red": 0.82,
            "green": 0.94,
            "blue": 0.82,
        }

        blocked_background = {
            "red": 1.00,
            "green": 0.88,
            "blue": 0.78,
        }

        failed_background = {
            "red": 0.96,
            "green": 0.78,
            "blue": 0.78,
        }

        for row_index, row in enumerate(
            values[1:],
            start=1,
        ):
            if status_index >= len(row):
                continue

            status = str(
                row[status_index]
            ).strip().upper()

            if status == "PREVIEW READY":
                background = ready_background
            elif status in {
                "BLOCKED BY MANIPULATION",
                "BLOCKED BY EARLIER QUICK FLIP",
            }:
                background = blocked_background
            elif status == "PREVIEW FAILED":
                background = failed_background
            else:
                continue

            requests.append({
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": row_index,
                        "endRowIndex": (
                            row_index + 1
                        ),
                        "startColumnIndex": (
                            status_index
                        ),
                        "endColumnIndex": (
                            status_index + 1
                        ),
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "backgroundColor": (
                                background
                            ),
                            "textFormat": {
                                "bold": True,
                            },
                            "horizontalAlignment": (
                                "CENTER"
                            ),
                        },
                    },
                    "fields": (
                        "userEnteredFormat."
                        "backgroundColor,"
                        "userEnteredFormat."
                        "textFormat.bold,"
                        "userEnteredFormat."
                        "horizontalAlignment"
                    ),
                },
            })

    @staticmethod
    def _trading_sheet_layout_policy(
            sheet_title: str,
    ) -> dict | None:
        """
        Return the daily-use presentation policy for the clean
        Manipulation + Quick Flip workbook.

        Hidden columns retain their underlying values for audit and
        debugging; this policy changes presentation only.
        """
        layouts = {
            "Trade Previews": {
                "widths": {
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
                },
                "hidden_columns": [],
            },
            "Scanner Dashboard": {
                "widths": {
                    0: 105,
                    1: 85,
                    3: 135,
                    4: 110,
                    7: 115,
                    9: 90,
                    10: 260,
                },
                "hidden_columns": [
                    (2, 3),
                    (5, 7),
                    (8, 9),
                ],
            },
            "Manipulation Signals": {
                "widths": {
                    0: 105,
                    1: 85,
                    4: 90,
                    5: 95,
                    6: 95,
                    8: 125,
                    9: 105,
                    14: 220,
                },
                "hidden_columns": [
                    (2, 4),
                    (7, 8),
                    (10, 14),
                    (15, 26),
                ],
            },
            "Quick Flip Signals": {
                "widths": {
                    0: 105,
                    1: 85,
                    2: 120,
                    3: 90,
                    4: 150,
                    5: 95,
                    6: 95,
                    7: 95,
                    14: 120,
                },
                "hidden_columns": [
                    (8, 14),
                    (15, 18),
                ],
            },
            "Daily Trade P&L": {
                "widths": {
                    0: 105,
                    1: 85,
                    2: 90,
                    3: 105,
                    4: 105,
                    5: 110,
                    6: 105,
                    7: 135,
                },
                "hidden_columns": [],
            },
            "Daily P&L Summary": {
                "widths": {
                    0: 105,
                    1: 105,
                    2: 110,
                    3: 110,
                    4: 125,
                    5: 105,
                    6: 115,
                    7: 115,
                    8: 120,
                    9: 170,
                },
                "hidden_columns": [],
            },
        }

        return layouts.get(sheet_title)

    def format_worksheet(
            self,
            worksheet,
            *,
            use_cached_values: bool = True,
    ) -> None:
        """
        Apply consistent professional formatting to a worksheet.

        When this SheetsClient just rewrote the worksheet, reuse
        those exact values instead of issuing another Google Sheets
        read request.
        """
        cache = getattr(
            self,
            "_worksheet_values_cache",
            {},
        )

        cache_key = str(
            getattr(
                worksheet,
                "title",
                "",
            )
        )

        values = (
            cache.get(cache_key)
            if use_cached_values
            else None
        )

        if values is None:
            values = (
                self._sheets_read_with_quota_retry(
                    worksheet.get_all_values,
                    label=(
                        "Google Sheets formatting read: "
                        f"{getattr(worksheet, 'title', 'worksheet')}"
                    ),
                )
            )

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

        layout_policy = (
            self._trading_sheet_layout_policy(
                worksheet.title
            )
        )

        if layout_policy is not None:
            for column_index, pixel_width in (
                layout_policy["widths"].items()
            ):
                if column_index < len(column_widths):
                    column_widths[
                        column_index
                    ] = pixel_width

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
            "ATR Threshold",
            "Candle Range",
            "Entry",
            "Target",
            "TP1",
            "TP2",
            "Retracement Price",
            "Opening Open",
            "Opening High",
            "Opening Low",
            "Opening Close",
            "Limit Buy",
            "Limit Sell",
            "Stop Loss",
            "Trading Stop Loss",
            "Running High",
            "Running Low",
            "VWAP",
        }

        currency_two_decimals = {
            "Estimated Position Value",
            "Maximum Position Value",
            "Estimated Cost",
            "Estimated Fee",
            "Buy Price",
            "Sell Price",
            "Profit/Loss",
            "Total P&L",
            "Gross Profit",
            "Gross Loss",
            "Realized P&L",
        }

        number_two_decimals = {
            "Reward / Risk",
        }

        number_three_decimals = {
            "Impulse ATR Multiple",
            "Pullback Volume Ratio",
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
            "Win Rate %",
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

        self._append_column_formatting_requests(
            requests=requests,
            columns=columns,
            sheet_id=sheet_id,
            row_count=row_count,
            currency_four_decimals=currency_four_decimals,
            currency_two_decimals=currency_two_decimals,
            number_two_decimals=number_two_decimals,
            number_three_decimals=number_three_decimals,
            integer_columns=integer_columns,
            percentage_columns=percentage_columns,
            date_columns=date_columns,
            time_columns=time_columns,
            left_aligned_columns=left_aligned_columns,
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
            self._append_daily_trade_pnl_formatting_requests(
                requests=requests,
                sheet_id=sheet_id,
                row_count=row_count,
                values=values,
                border_colour=border_colour,
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

        if worksheet.title == "Trade Previews":
            self._append_trade_previews_display_requests(
                requests=requests,
                columns=columns,
                values=values,
                sheet_id=sheet_id,
                row_count=row_count,
            )

        if layout_policy is not None:
            # First restore every managed column to visible, then
            # hide only the diagnostic ranges in the policy.
            requests.append({
                "updateDimensionProperties": {
                    "range": {
                        "sheetId": sheet_id,
                        "dimension": "COLUMNS",
                        "startIndex": 0,
                        "endIndex": column_count,
                    },
                    "properties": {
                        "hiddenByUser": False,
                    },
                    "fields": "hiddenByUser",
                }
            })

            for start_index, end_index in (
                layout_policy[
                    "hidden_columns"
                ]
            ):
                if start_index >= column_count:
                    continue

                requests.append({
                    "updateDimensionProperties": {
                        "range": {
                            "sheetId": sheet_id,
                            "dimension": "COLUMNS",
                            "startIndex": (
                                start_index
                            ),
                            "endIndex": min(
                                end_index,
                                column_count,
                            ),
                        },
                        "properties": {
                            "hiddenByUser": True,
                        },
                        "fields": "hiddenByUser",
                    }
                })

        self._sheets_write_with_transient_retry(
            self.spreadsheet.batch_update,
            {
                "requests": requests,
            },
            label="Google Sheets worksheet formatting",
        )

    def _apply_trading_workbook_structure(
            self,
            worksheets=None,
    ) -> bool:
        """
        Keep the clean trading workbook ordered around the daily
        decision workflow while retaining research/support tabs.

        This is deliberately applied by format_all_sheets rather
        than every worksheet write so normal production does not
        create unnecessary Google Sheets API traffic.
        """
        visible_order = [
            "Trade Previews",
            "Scanner Dashboard",
            "Manipulation Signals",
            "Quick Flip Signals",
            "Daily Trade P&L",
            "Daily P&L Summary",
        ]

        hidden_order = [
            "Quick Flip Previews",
            (
                "Manipulation Selling Pressure "
                "Research"
            ),
            "Committed Allocation History",
        ]

        desired_order = (
            visible_order
            + hidden_order
        )

        if worksheets is None:
            worksheets = (
                self._sheets_read_with_quota_retry(
                    self.spreadsheet.worksheets,
                    label="Google Sheets worksheet list",
                )
            )

        worksheets = list(worksheets)

        by_title = {
            worksheet.title: worksheet
            for worksheet in worksheets
        }

        if not all(
            title in by_title
            for title in desired_order
        ):
            return False

        extras = [
            worksheet
            for worksheet in worksheets
            if worksheet.title
            not in desired_order
        ]

        target = [
            by_title[title]
            for title in desired_order
        ] + extras

        current_titles = [
            worksheet.title
            for worksheet in worksheets
        ]

        target_titles = [
            worksheet.title
            for worksheet in target
        ]

        if current_titles != target_titles:
            self._sheets_write_with_transient_retry(
                self.spreadsheet.reorder_worksheets,
                target,
                label="Google Sheets worksheet reorder",
            )

        visibility_requests = []

        for title in visible_order:
            visibility_requests.append({
                "updateSheetProperties": {
                    "properties": {
                        "sheetId": (
                            by_title[title].id
                        ),
                        "hidden": False,
                    },
                    "fields": "hidden",
                }
            })

        for title in hidden_order:
            visibility_requests.append({
                "updateSheetProperties": {
                    "properties": {
                        "sheetId": (
                            by_title[title].id
                        ),
                        "hidden": True,
                    },
                    "fields": "hidden",
                }
            })

        self._sheets_write_with_transient_retry(
            self.spreadsheet.batch_update,
            {
                "requests": visibility_requests,
            },
            label="Google Sheets worksheet visibility",
        )

        return True

    def format_all_sheets(self) -> None:
        """
        Apply professional formatting to every worksheet and, when
        this is the clean trading workbook, restore its daily-use
        tab order and visibility policy.
        """
        formatted = 0

        worksheets = (
            self._sheets_read_with_quota_retry(
                self.spreadsheet.worksheets,
                label="Google Sheets worksheet list",
            )
        )

        for worksheet in worksheets:
            try:
                self.format_worksheet(
                    worksheet,
                    use_cached_values=False,
                )
                formatted += 1
            except Exception as error:
                print(
                    f"Formatting skipped for {worksheet.title}: "
                    f"{error}"
                )

        try:
            self._apply_trading_workbook_structure(
                worksheets=worksheets,
            )
        except Exception as error:
            print(
                "Trading workbook organization skipped: "
                f"{error}"
            )

        print(
            f"{formatted} worksheet(s) professionally formatted."
        )

    def _sheet_rows_for_date(
        self,
        worksheet,
        date_str: str,
    ) -> tuple[list[str], list[list[str]]]:
        values = (
            self._sheets_read_with_quota_retry(
                worksheet.get_all_values,
                label=(
                    "Google Sheets date lookup: "
                    f"{getattr(worksheet, 'title', 'worksheet')}"
                ),
            )
        )

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
                self._sheets_read_with_quota_retry(
                    self.spreadsheet.worksheet,
                    "Scanner Dashboard",
                    label="Google Sheets worksheet lookup: Scanner Dashboard",
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

        self.format_worksheet(worksheet)

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
                    else self._format_new_york_clock_time(
                        signal.confirmation_time
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

    def _migrate_legacy_webull_trade_pnl(
            self,
            *,
            worksheet,
            existing_values: list,
            columns: list,
            legacy_columns: list,
    ) -> list:
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

        return worksheet.get_all_values()

    def _reconcile_webull_trade_pnl_totals(
            self,
            *,
            worksheet,
            columns: list,
    ) -> None:
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
            existing_values = (
                self._migrate_legacy_webull_trade_pnl(
                    worksheet=worksheet,
                    existing_values=existing_values,
                    columns=columns,
                    legacy_columns=legacy_columns,
                )
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
        self._reconcile_webull_trade_pnl_totals(
            worksheet=worksheet,
            columns=columns,
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
        Replace the current-session capital-allocation dashboard.
        """
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

        worksheet = self.get_or_create_worksheet(
            title=sheet_name,
            rows=250,
            cols=len(columns),
        )

        display_statuses = {
            "PREVIEW READY",
            "BLOCKED BY MANIPULATION",
            "BLOCKED BY EARLIER QUICK FLIP",
            "PREVIEW FAILED",
        }

        def rank_sort_key(preview):
            value = preview.get(
                "rank",
                "",
            )

            try:
                rank = int(value)
            except (
                TypeError,
                ValueError,
            ):
                rank = 999999

            return (
                rank,
                str(
                    preview.get(
                        "strategy",
                        "",
                    )
                ),
                str(
                    preview.get(
                        "symbol",
                        "",
                    )
                ),
            )

        rows = []

        for preview in sorted(
            previews,
            key=rank_sort_key,
        ):
            status = str(
                preview.get(
                    "status",
                    "",
                )
            ).strip().upper()

            if status not in display_statuses:
                continue

            rank = preview.get(
                "rank",
                "",
            )

            strategy = str(
                preview.get(
                    "strategy",
                    "",
                )
            ).strip()

            symbol = str(
                preview.get(
                    "symbol",
                    "",
                )
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

            allocation_weight = preview.get(
                "allocation_weight",
                "",
            )

            if allocation_weight in {
                "",
                None,
            }:
                allocation_percent = ""
            else:
                allocation_percent = (
                    f"{float(allocation_weight) * 100:.2f}%"
                )

            recommended = preview.get(
                "recommended_allocation",
                "",
            )

            if recommended in {
                "",
                None,
            }:
                recommended_text = ""
            else:
                recommended_text = (
                    f"${float(recommended):.2f}"
                )

            rows.append([
                date_str,
                preview_time,
                rank,
                strategy,
                symbol,
                entry,
                exit_value,
                quantity,
                allocation_percent,
                recommended_text,
                status,
            ])

        self._sheets_write_with_transient_retry(
            worksheet.clear,
            label=f"Google Sheets clear: {sheet_name}",
        )

        table = [
            columns,
            *rows,
        ]

        last_column = "K"

        self._sheets_write_with_transient_retry(
            worksheet.resize,
            rows=max(
                250,
                len(table) + 20,
            ),
            cols=len(columns),
            label=f"Google Sheets resize: {sheet_name}",
        )

        self._sheets_write_with_transient_retry(
            worksheet.update,
            range_name=(
                f"A1:{last_column}{len(table)}"
            ),
            values=table,
            value_input_option="USER_ENTERED",
            label=f"Google Sheets write: {sheet_name}",
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

        self.format_worksheet(worksheet)

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
