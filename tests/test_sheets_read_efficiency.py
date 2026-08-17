from trading_bot.sheets_client import SheetsClient


class FakeWorksheet:
    def __init__(self):
        self.title = "Efficiency Test"
        self.id = 123
        self.values = [
            ["Date", "Value"],
            ["2026-08-16", "keep"],
            ["2026-08-17", "old"],
        ]
        self.read_count = 0
        self.update_count = 0

    def get_all_values(self):
        self.read_count += 1
        return [
            list(row)
            for row in self.values
        ]

    def update(
        self,
        *,
        values,
        range_name,
        value_input_option,
    ):
        self.update_count += 1
        self.values = [
            list(row)
            for row in values
        ]

    def batch_clear(self, ranges):
        return None


class FakeSpreadsheet:
    def __init__(self, worksheet):
        self.target = worksheet
        self.lookup_count = 0
        self.batch_updates = []

    def worksheet(self, title):
        self.lookup_count += 1
        return self.target

    def batch_update(self, payload):
        self.batch_updates.append(payload)


def test_get_or_create_worksheet_uses_session_cache():
    worksheet = FakeWorksheet()
    spreadsheet = FakeSpreadsheet(
        worksheet
    )

    client = object.__new__(SheetsClient)
    client.spreadsheet = spreadsheet

    first = client.get_or_create_worksheet(
        "Efficiency Test"
    )
    second = client.get_or_create_worksheet(
        "Efficiency Test"
    )

    assert first is worksheet
    assert second is worksheet
    assert spreadsheet.lookup_count == 1


def test_replace_and_format_use_one_sheet_read():
    worksheet = FakeWorksheet()
    spreadsheet = FakeSpreadsheet(
        worksheet
    )

    client = object.__new__(SheetsClient)
    client.spreadsheet = spreadsheet

    client._replace_date_rows(
        worksheet=worksheet,
        columns=[
            "Date",
            "Value",
        ],
        date_str="2026-08-17",
        replacement_rows=[
            [
                "2026-08-17",
                "new",
            ],
        ],
        last_column="B",
        sheet_name="Efficiency Test",
    )

    # _replace_date_rows needs one real read.
    # _rewrite_table must not perform a second read.
    assert worksheet.read_count == 1

    assert worksheet.values == [
        ["Date", "Value"],
        ["2026-08-16", "keep"],
        ["2026-08-17", "new"],
    ]

    client.format_worksheet(
        worksheet
    )

    # Formatting reuses the table we just wrote.
    assert worksheet.read_count == 1
    assert spreadsheet.batch_updates


def _api_error(status_code):
    import json
    from requests import Response
    import gspread

    response = Response()
    response.status_code = status_code
    response._content = json.dumps({
        "error": {
            "code": status_code,
            "message": (
                "Quota exceeded"
                if status_code == 429
                else "Different API error"
            ),
            "status": (
                "RESOURCE_EXHAUSTED"
                if status_code == 429
                else "UNKNOWN"
            ),
        }
    }).encode("utf-8")

    return gspread.exceptions.APIError(
        response
    )


def test_sheets_read_retries_only_429(monkeypatch):
    client = object.__new__(SheetsClient)

    attempts = []
    sleeps = []

    monkeypatch.setattr(
        "trading_bot.sheets_client.time.sleep",
        lambda seconds: sleeps.append(seconds),
    )

    def flaky_read():
        attempts.append("attempt")

        if len(attempts) < 3:
            raise _api_error(429)

        return [["ok"]]

    result = client._sheets_read_with_quota_retry(
        flaky_read,
        label="test read",
    )

    assert result == [["ok"]]
    assert len(attempts) == 3
    assert sleeps == [15, 30]


def test_sheets_read_does_not_retry_non_429(
        monkeypatch,
):
    import pytest

    client = object.__new__(SheetsClient)

    attempts = []
    sleeps = []

    monkeypatch.setattr(
        "trading_bot.sheets_client.time.sleep",
        lambda seconds: sleeps.append(seconds),
    )

    def failing_read():
        attempts.append("attempt")
        raise _api_error(403)

    with pytest.raises(
        Exception
    ):
        client._sheets_read_with_quota_retry(
            failing_read,
            label="test read",
        )

    assert len(attempts) == 1
    assert sleeps == []


def test_sheets_read_raises_after_final_429(
        monkeypatch,
):
    import pytest

    client = object.__new__(SheetsClient)

    attempts = []
    sleeps = []

    monkeypatch.setattr(
        "trading_bot.sheets_client.time.sleep",
        lambda seconds: sleeps.append(seconds),
    )

    def failing_read():
        attempts.append("attempt")
        raise _api_error(429)

    with pytest.raises(
        Exception
    ):
        client._sheets_read_with_quota_retry(
            failing_read,
            label="test read",
        )

    assert len(attempts) == 3
    assert sleeps == [15, 30]
