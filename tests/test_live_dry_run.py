from unittest.mock import Mock

from trading_bot.models import Stock
from trading_bot.tracker import MinuteTracker


def test_tracker_can_initialise_without_sheets():
    tracker = MinuteTracker(
        alpaca=Mock(),
        sheets=None,
        stocks={
            "OPEN": Stock(symbol="OPEN"),
        },
        symbols_csv="OPEN",
        write_sheets=False,
    )

    tracker.prepare_sheet("2026-07-28")

    assert tracker.worksheet is None
    assert tracker.symbol_rows == {
        "OPEN": 2,
    }


def test_tracker_requires_sheets_when_writes_enabled():
    try:
        MinuteTracker(
            alpaca=Mock(),
            sheets=None,
            stocks={
                "OPEN": Stock(symbol="OPEN"),
            },
            symbols_csv="OPEN",
            write_sheets=True,
        )
    except ValueError as error:
        assert "SheetsClient" in str(error)
    else:
        raise AssertionError(
            "Tracker accepted write mode without SheetsClient."
        )
