from types import SimpleNamespace
from unittest.mock import Mock

import trading_bot.sheets_client as sheets_module
from trading_bot.sheets_client import SheetsClient


def make_writer():
    client = object.__new__(SheetsClient)

    worksheet = Mock()
    captured = {}

    client.get_or_create_worksheet = Mock(
        return_value=worksheet
    )

    def capture_replace(**kwargs):
        captured.update(kwargs)

    client._replace_date_rows = capture_replace

    return client, captured


def test_quick_flip_results_have_tp_levels_but_no_stop():
    client, captured = make_writer()

    signal = SimpleNamespace(
        signal="INVEST",
        pattern="HAMMER",
        entry_price=9.25,
        take_profit_1=10.00,
        take_profit_2=11.00,
        opening_range_high=11.00,
        opening_range_low=10.00,
        opening_range_size=1.00,
        atr_14=0.75,
        liquidity_threshold=0.9375,
        reversal_time="2026-08-11T13:50:00Z",
        confirmation_time="2026-08-11T13:55:00Z",
        detail="Hammer confirmed",
    )

    result = SimpleNamespace(
        status="CONFIRMED",
        signal=signal,
    )

    client.write_quick_flip_results(
        date_str="2026-08-11",
        results={
            "OPEN": result,
        },
    )

    columns = captured["columns"]
    rows = captured["replacement_rows"]

    assert "Entry" in columns
    assert "TP1" in columns
    assert "TP2" in columns

    assert "Stop Loss" not in columns
    assert "Trading Stop Loss" not in columns

    assert len(rows) == 1

    row = dict(zip(columns, rows[0]))

    assert row["Symbol"] == "OPEN"
    assert row["Signal"] == "INVEST"
    assert row["Pattern"] == "HAMMER"
    assert row["Entry"] == 9.25
    assert row["TP1"] == 10.0
    assert row["TP2"] == 11.0

    assert row["Automatic Stop Loss"] == "NO"
    assert row["Broker Submitted"] == "NO"


def test_quick_flip_previews_are_preview_only():
    client, captured = make_writer()

    client.write_quick_flip_previews(
        date_str="2026-08-11",
        previews=[
            {
                "symbol": "OPEN",
                "status": "PREVIEW READY",
                "quantity": 10,
                "limitBuy": 9.25,
                "takeProfit1": 10.00,
                "takeProfit2": 11.00,
                "estimatedPositionValue": 92.50,
                "maxPositionValue": 500.00,
                "sizingConstraint": "POSITION_VALUE",
                "safetyAllowed": True,
                "safetyReason": "PREVIEW_ELIGIBLE",
                "manualApprovalRequired": True,
                "manualApprovalGranted": False,
                "estimatedCost": 92.50,
                "estimatedTransactionFee": 0.0,
                "submitted": False,
            }
        ],
    )

    columns = captured["columns"]
    rows = captured["replacement_rows"]

    assert "TP1" in columns
    assert "TP2" in columns

    assert "Stop Loss" not in columns
    assert "Trading Stop Loss" not in columns

    row = dict(zip(columns, rows[0]))

    assert row["Status"] == "PREVIEW READY"
    assert row["Quantity"] == 10
    assert row["Entry"] == 9.25
    assert row["TP1"] == 10.0
    assert row["TP2"] == 11.0

    assert row["Manual Approval Required"] == "YES"
    assert row["Manual Approval Granted"] == "NO"
    assert row["Automatic Stop Loss"] == "NO"
    assert row["Submitted"] == "NO"


def test_sheets_client_can_target_separate_workbook(
    monkeypatch,
):
    credentials = object()

    monkeypatch.setattr(
        sheets_module.Credentials,
        "from_service_account_file",
        Mock(return_value=credentials),
    )

    spreadsheet = Mock()

    google_client = Mock()
    google_client.open_by_key.return_value = (
        spreadsheet
    )

    monkeypatch.setattr(
        sheets_module.gspread,
        "authorize",
        Mock(return_value=google_client),
    )

    client = SheetsClient(
        spreadsheet_id="NEW-WORKBOOK-ID",
    )

    google_client.open_by_key.assert_called_once_with(
        "NEW-WORKBOOK-ID"
    )

    assert (
        client.spreadsheet_id
        == "NEW-WORKBOOK-ID"
    )

    assert client.spreadsheet is spreadsheet


def test_blank_google_worksheet_can_accept_new_header():
    SheetsClient._validate_header(
        existing_values=[[]],
        expected_columns=[
            "Date",
            "Symbol",
        ],
        sheet_name="Scanner Dashboard",
    )


def test_existing_wrong_header_is_still_rejected():
    import pytest

    with pytest.raises(
        RuntimeError,
        match="unexpected columns",
    ):
        SheetsClient._validate_header(
            existing_values=[
                ["Wrong", "Header"],
            ],
            expected_columns=[
                "Date",
                "Symbol",
            ],
            sheet_name="Scanner Dashboard",
        )
