from types import SimpleNamespace

from trading_bot.sheets_client import SheetsClient


def _number_formats(requests, columns):
    result = {}

    for request in requests:
        repeat_cell = request.get("repeatCell")

        if not repeat_cell:
            continue

        user_format = repeat_cell.get(
            "cell",
            {},
        ).get(
            "userEnteredFormat",
            {},
        )

        number_format = user_format.get(
            "numberFormat"
        )

        if number_format is None:
            continue

        column_index = repeat_cell[
            "range"
        ].get(
            "startColumnIndex"
        )

        end_column_index = repeat_cell[
            "range"
        ].get(
            "endColumnIndex"
        )

        if (
            column_index is None
            or end_column_index
            != column_index + 1
            or column_index >= len(columns)
        ):
            continue

        result[columns[column_index]] = (
            number_format
        )

    return result


def test_current_strategy_and_order_columns_are_formatted():
    columns = [
        "Entry",
        "Target",
        "Retracement Price",
        "Opening Open",
        "Opening High",
        "Opening Low",
        "Opening Close",
        "ATR Threshold",
        "Reward / Risk",
        "Impulse ATR Multiple",
        "Pullback Volume Ratio",
        "Estimated Position Value",
        "Maximum Position Value",
    ]

    worksheet = SimpleNamespace(
        title="Formatting Test",
        id=123,
        get_all_values=lambda: [
            columns,
            [""] * len(columns),
        ],
    )

    captured = {}

    spreadsheet = SimpleNamespace(
        batch_update=lambda payload: (
            captured.update(payload)
        )
    )

    client = object.__new__(SheetsClient)
    client.spreadsheet = spreadsheet

    client.format_worksheet(worksheet)

    formats = _number_formats(
        captured["requests"],
        columns,
    )

    currency_four = {
        "type": "CURRENCY",
        "pattern": "$#,##0.0000",
    }

    for column in (
        "Entry",
        "Target",
        "Retracement Price",
        "Opening Open",
        "Opening High",
        "Opening Low",
        "Opening Close",
        "ATR Threshold",
    ):
        assert formats[column] == currency_four

    currency_two = {
        "type": "CURRENCY",
        "pattern": "$#,##0.00",
    }

    assert (
        formats["Estimated Position Value"]
        == currency_two
    )
    assert (
        formats["Maximum Position Value"]
        == currency_two
    )

    assert formats["Reward / Risk"] == {
        "type": "NUMBER",
        "pattern": "0.00",
    }

    assert formats["Impulse ATR Multiple"] == {
        "type": "NUMBER",
        "pattern": "0.000",
    }

    assert formats["Pullback Volume Ratio"] == {
        "type": "NUMBER",
        "pattern": "0.000",
    }
