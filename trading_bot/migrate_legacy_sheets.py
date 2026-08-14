from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .sheets_client import SheetsClient


INVEST_LEGACY_COLUMNS = [
    "Date",
    "Symbol",
    "Open",
    "High",
    "Low",
    "Close",
    "Prev Day Range (ATR)",
    "ATR x 0.25",
    "Candle Range",
    "Manipulation Candle",
    "Red Candle",
    "Signal",
    "Limit Buy",
    "Limit Sell",
    "Stop Loss",
    "Trading Stop Loss",
    "Proximity to High/Low",
]

INVEST_CURRENT_COLUMNS = [
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

ORDERS_LEGACY_COLUMNS = [
    "Date",
    "Symbol",
    "Limit Buy",
    "Limit Sell",
    "Trading Stop Loss",
    "Webull Preview",
    "Quantity",
    "Estimated Cost",
    "Estimated Fee",
    "Submitted",
]

ORDERS_CURRENT_COLUMNS = [
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


def _copy_values(values: list[list[str]]) -> list[list[str]]:
    return [list(row) for row in values]


def _row_dict(
    header: list[str],
    row: list[str],
) -> dict[str, str]:
    padded = list(row[:len(header)])

    if len(padded) < len(header):
        padded.extend([""] * (len(header) - len(padded)))

    return dict(zip(header, padded))


def migrate_invest_values(
    values: list[list[str]],
) -> list[list[str]]:
    if not values or not values[0]:
        return [list(INVEST_CURRENT_COLUMNS)]

    header = list(values[0])

    if header == INVEST_CURRENT_COLUMNS:
        return _copy_values(values)

    if header != INVEST_LEGACY_COLUMNS:
        raise RuntimeError(
            "Unrecognised Invest header. "
            "Migration refused; no data was changed."
        )

    migrated_rows = []

    for row in values[1:]:
        old = _row_dict(header, row)

        migrated_rows.append(
            [
                old["Date"],
                old["Symbol"],
                "",
                "",
                old["Signal"],
                old["Limit Buy"],
                old["Limit Sell"],
                old["Stop Loss"],
                old["Trading Stop Loss"],
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                old["Prev Day Range (ATR)"],
                old["Open"],
                old["High"],
                old["Low"],
                old["Close"],
                old["Candle Range"],
                old["ATR x 0.25"],
                old["Manipulation Candle"],
                old["Red Candle"],
                old["Proximity to High/Low"],
            ]
        )

    return [
        list(INVEST_CURRENT_COLUMNS),
        *migrated_rows,
    ]


def migrate_orders_values(
    values: list[list[str]],
) -> list[list[str]]:
    if not values or not values[0]:
        return [list(ORDERS_CURRENT_COLUMNS)]

    header = list(values[0])

    if header == ORDERS_CURRENT_COLUMNS:
        return _copy_values(values)

    if header != ORDERS_LEGACY_COLUMNS:
        raise RuntimeError(
            "Unrecognised Orders header. "
            "Migration refused; no data was changed."
        )

    migrated_rows = []

    for row in values[1:]:
        old = _row_dict(header, row)

        migrated_rows.append(
            [
                old["Date"],
                old["Symbol"],
                old["Limit Buy"],
                old["Limit Sell"],
                old["Trading Stop Loss"],
                old["Webull Preview"],
                old["Quantity"],
                "",
                "",
                "",
                old["Estimated Cost"],
                old["Estimated Fee"],
                old["Submitted"],
            ]
        )

    return [
        list(ORDERS_CURRENT_COLUMNS),
        *migrated_rows,
    ]


def _schema_state(
    values: list[list[str]],
    legacy_columns: list[str],
    current_columns: list[str],
) -> str:
    if not values or not values[0]:
        return "EMPTY"

    header = list(values[0])

    if header == current_columns:
        return "CURRENT"

    if header == legacy_columns:
        return "LEGACY"

    return "UNKNOWN"


def _column_name(number: int) -> str:
    result = ""

    while number:
        number, remainder = divmod(number - 1, 26)
        result = chr(65 + remainder) + result

    return result


def _write_values(
    worksheet,
    values: list[list[str]],
) -> None:
    maximum_columns = max(
        len(row)
        for row in values
    )

    worksheet.resize(
        rows=max(
            worksheet.row_count,
            len(values) + 5,
        ),
        cols=max(
            worksheet.col_count,
            maximum_columns,
        ),
    )

    worksheet.update(
        values=values,
        range_name=(
            f"A1:{_column_name(maximum_columns)}"
            f"{len(values)}"
        ),
        value_input_option="USER_ENTERED",
    )


def _create_cloud_backup(
    client: SheetsClient,
    sheet_name: str,
    values: list[list[str]],
    stamp: str,
) -> str:
    backup_name = f"{sheet_name} Backup {stamp}"

    maximum_columns = max(
        [len(row) for row in values],
        default=1,
    )

    backup = client.spreadsheet.add_worksheet(
        title=backup_name,
        rows=max(len(values) + 5, 10),
        cols=max(maximum_columns, 1),
    )

    if values:
        backup.update(
            values=values,
            range_name=(
                f"A1:{_column_name(maximum_columns)}"
                f"{len(values)}"
            ),
            value_input_option="USER_ENTERED",
        )

    return backup_name


def _create_local_backup(
    originals: dict[str, list[list[str]]],
    stamp: str,
) -> Path:
    directory = Path(
        "runtime/sheet_migration_backups"
    )
    directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    path = directory / f"{stamp}.json"

    payload = {
        "created_at": datetime.now(
            ZoneInfo("America/New_York")
        ).isoformat(),
        "sheets": originals,
    }

    path.write_text(
        json.dumps(
            payload,
            indent=2,
        ),
        encoding="utf-8",
    )

    return path


def migrate_google_sheets(
    client: SheetsClient,
    apply: bool = False,
) -> None:
    worksheets = {
        "Invest": client.spreadsheet.worksheet(
            "Invest"
        ),
        "Orders": client.spreadsheet.worksheet(
            "Orders"
        ),
    }

    originals = {
        name: worksheet.get_all_values()
        for name, worksheet in worksheets.items()
    }

    states = {
        "Invest": _schema_state(
            originals["Invest"],
            INVEST_LEGACY_COLUMNS,
            INVEST_CURRENT_COLUMNS,
        ),
        "Orders": _schema_state(
            originals["Orders"],
            ORDERS_LEGACY_COLUMNS,
            ORDERS_CURRENT_COLUMNS,
        ),
    }

    print(
        "Invest schema:",
        states["Invest"],
    )
    print(
        "Orders schema:",
        states["Orders"],
    )

    unknown = [
        name
        for name, state in states.items()
        if state == "UNKNOWN"
    ]

    if unknown:
        raise RuntimeError(
            "Migration refused because these sheets "
            "have an unknown schema: "
            + ", ".join(unknown)
        )

    if all(
        state == "CURRENT"
        for state in states.values()
    ):
        print(
            "Both sheets already use the current "
            "schema. Nothing to migrate."
        )
        return

    migrated = {
        "Invest": migrate_invest_values(
            originals["Invest"]
        ),
        "Orders": migrate_orders_values(
            originals["Orders"]
        ),
    }

    if not apply:
        print()
        print("DRY RUN ONLY.")
        print(
            "No Google Sheet values were changed."
        )
        print(
            "Run again with --apply after reviewing "
            "this result."
        )
        return

    stamp = datetime.now(
        ZoneInfo("America/New_York")
    ).strftime("%Y%m%d-%H%M%S")

    local_backup = _create_local_backup(
        originals=originals,
        stamp=stamp,
    )

    print(
        f"Local backup created: {local_backup}"
    )

    backup_names = []

    for name in ("Invest", "Orders"):
        backup_names.append(
            _create_cloud_backup(
                client=client,
                sheet_name=name,
                values=originals[name],
                stamp=stamp,
            )
        )

    print(
        "Google Sheets backups created: "
        + ", ".join(backup_names)
    )

    changed = []

    try:
        for name in ("Invest", "Orders"):
            if states[name] == "CURRENT":
                continue

            _write_values(
                worksheets[name],
                migrated[name],
            )
            changed.append(name)

        invest_check = (
            worksheets["Invest"]
            .get_all_values()
        )
        orders_check = (
            worksheets["Orders"]
            .get_all_values()
        )

        if (
            not invest_check
            or invest_check[0]
            != INVEST_CURRENT_COLUMNS
        ):
            raise RuntimeError(
                "Invest verification failed."
            )

        if (
            not orders_check
            or orders_check[0]
            != ORDERS_CURRENT_COLUMNS
        ):
            raise RuntimeError(
                "Orders verification failed."
            )

    except Exception:
        print(
            "Migration failed. Restoring sheets "
            "that were already changed..."
        )

        for name in changed:
            _write_values(
                worksheets[name],
                originals[name],
            )

        raise

    print()
    print("Migration completed successfully.")
    print(
        f"Invest rows preserved: "
        f"{max(len(originals['Invest']) - 1, 0)}"
    )
    print(
        f"Orders rows preserved: "
        f"{max(len(originals['Orders']) - 1, 0)}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Migrate legacy Invest and Orders "
            "Google Sheet schemas."
        )
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help=(
            "Actually perform the migration. "
            "Without this flag the command is read-only."
        ),
    )

    args = parser.parse_args()

    client = SheetsClient()

    migrate_google_sheets(
        client=client,
        apply=args.apply,
    )


if __name__ == "__main__":
    main()
