import pytest

from trading_bot.migrate_legacy_sheets import (
    INVEST_CURRENT_COLUMNS,
    INVEST_LEGACY_COLUMNS,
    ORDERS_CURRENT_COLUMNS,
    ORDERS_LEGACY_COLUMNS,
    migrate_invest_values,
    migrate_orders_values,
)


def _as_dict(header, row):
    return dict(zip(header, row))


def test_migrates_legacy_invest_values():
    legacy_row = [
        "2026-08-13",
        "BBAI",
        "3.10",
        "3.40",
        "3.00",
        "3.25",
        "0.80",
        "0.20",
        "0.40",
        "YES",
        "YES",
        "INVEST",
        "3.30",
        "3.50",
        "3.05",
        "3.15",
        "HIGH",
    ]

    migrated = migrate_invest_values(
        [
            INVEST_LEGACY_COLUMNS,
            legacy_row,
        ]
    )

    assert migrated[0] == INVEST_CURRENT_COLUMNS

    row = _as_dict(
        INVEST_CURRENT_COLUMNS,
        migrated[1],
    )

    assert row["Date"] == "2026-08-13"
    assert row["Symbol"] == "BBAI"
    assert row["Signal"] == "INVEST"
    assert row["Entry"] == "3.30"
    assert row["Target"] == "3.50"
    assert row["Stop Loss"] == "3.05"
    assert row["Trading Stop Loss"] == "3.15"
    assert row["Prev Day Range (ATR)"] == "0.80"
    assert row["Opening Open"] == "3.10"
    assert row["Opening High"] == "3.40"
    assert row["Opening Low"] == "3.00"
    assert row["Opening Close"] == "3.25"
    assert row["Candle Range"] == "0.40"
    assert row["ATR Threshold"] == "0.20"
    assert row["Manipulation Candle"] == "YES"
    assert row["Red Candle"] == "YES"
    assert row["Proximity to High/Low"] == "HIGH"

    assert row["Strategy"] == ""
    assert row["Strategy Status"] == ""
    assert row["Reward / Risk"] == ""


def test_migrates_legacy_orders_values():
    legacy_row = [
        "2026-08-13",
        "BBAI",
        "3.30",
        "3.50",
        "3.15",
        "PREVIEW READY",
        "1",
        "3.30",
        "0.00",
        "NO",
    ]

    migrated = migrate_orders_values(
        [
            ORDERS_LEGACY_COLUMNS,
            legacy_row,
        ]
    )

    assert migrated[0] == ORDERS_CURRENT_COLUMNS

    row = _as_dict(
        ORDERS_CURRENT_COLUMNS,
        migrated[1],
    )

    assert row["Date"] == "2026-08-13"
    assert row["Symbol"] == "BBAI"
    assert row["Limit Buy"] == "3.30"
    assert row["Limit Sell"] == "3.50"
    assert row["Trading Stop Loss"] == "3.15"
    assert row["Webull Preview"] == "PREVIEW READY"
    assert row["Quantity"] == "1"
    assert row["Estimated Cost"] == "3.30"
    assert row["Estimated Fee"] == "0.00"
    assert row["Submitted"] == "NO"

    assert row["Estimated Position Value"] == ""
    assert row["Maximum Position Value"] == ""
    assert row["Sizing Constraint"] == ""


def test_current_invest_schema_is_idempotent():
    values = [
        INVEST_CURRENT_COLUMNS,
        [""] * len(INVEST_CURRENT_COLUMNS),
    ]

    assert migrate_invest_values(values) == values


def test_current_orders_schema_is_idempotent():
    values = [
        ORDERS_CURRENT_COLUMNS,
        [""] * len(ORDERS_CURRENT_COLUMNS),
    ]

    assert migrate_orders_values(values) == values


def test_unknown_invest_schema_is_rejected():
    with pytest.raises(
        RuntimeError,
        match="Unrecognised Invest header",
    ):
        migrate_invest_values(
            [["Date", "Something Unexpected"]]
        )


def test_unknown_orders_schema_is_rejected():
    with pytest.raises(
        RuntimeError,
        match="Unrecognised Orders header",
    ):
        migrate_orders_values(
            [["Date", "Something Unexpected"]]
        )
