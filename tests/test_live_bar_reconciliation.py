from unittest.mock import Mock

from trading_bot.models import Stock
from trading_bot.tracker import MinuteTracker


def make_bar(
    timestamp: str,
    open_price: float,
    high: float,
    low: float,
    close: float,
    volume: int = 100,
) -> dict:
    return {
        "t": timestamp,
        "o": open_price,
        "h": high,
        "l": low,
        "c": close,
        "v": volume,
    }


def make_tracker() -> MinuteTracker:
    alpaca = Mock()
    sheets = Mock()
    sheets.get_or_create_worksheet.return_value = Mock()

    stocks = {
        "OPEN": Stock(symbol="OPEN"),
    }

    tracker = MinuteTracker(
        alpaca=alpaca,
        sheets=sheets,
        stocks=stocks,
        symbols_csv="OPEN",
    )

    tracker.symbol_rows = {"OPEN": 2}
    return tracker


def test_merge_stream_bars_deduplicates_timestamps():
    tracker = make_tracker()
    stock = tracker.stocks["OPEN"]

    original = make_bar(
        "2026-07-28T13:30:00Z",
        4.10,
        4.20,
        4.05,
        4.15,
    )

    stock.minute_bars.append(original)
    tracker.process_bar(stock, original)

    streamed = {
        "OPEN": [
            make_bar(
                "2026-07-28T13:30:00Z",
                4.10,
                4.20,
                4.05,
                4.15,
            )
        ]
    }

    counts = tracker.merge_stream_bars(streamed)

    assert counts["OPEN"] == 1
    assert len(stock.minute_bars) == 1
    assert stock.green_minutes == 1
    assert stock.red_minutes == 0


def test_updated_stream_bar_replaces_rest_bar():
    tracker = make_tracker()
    stock = tracker.stocks["OPEN"]

    rest_bar = make_bar(
        "2026-07-28T13:30:00Z",
        4.10,
        4.20,
        4.05,
        4.15,
        100,
    )

    stock.minute_bars.append(rest_bar)
    tracker.process_bar(stock, rest_bar)

    updated_bar = make_bar(
        "2026-07-28T13:30:00Z",
        4.10,
        4.30,
        4.05,
        4.25,
        150,
    )

    counts = tracker.merge_stream_bars(
        {"OPEN": [updated_bar]}
    )

    assert counts["OPEN"] == 1
    assert stock.minute_bars[0]["h"] == 4.30
    assert stock.minute_bars[0]["c"] == 4.25
    assert stock.minute_bars[0]["v"] == 150
    assert stock.running_high == 4.30


def test_stream_merge_rebuilds_bars_chronologically():
    tracker = make_tracker()
    stock = tracker.stocks["OPEN"]

    streamed = {
        "OPEN": [
            make_bar(
                "2026-07-28T13:32:00Z",
                4.20,
                4.25,
                4.15,
                4.18,
            ),
            make_bar(
                "2026-07-28T13:30:00Z",
                4.10,
                4.15,
                4.05,
                4.12,
            ),
            make_bar(
                "2026-07-28T13:31:00Z",
                4.12,
                4.22,
                4.10,
                4.20,
            ),
        ]
    }

    counts = tracker.merge_stream_bars(streamed)

    assert counts["OPEN"] == 3
    assert [
        bar["t"]
        for bar in stock.minute_bars
    ] == [
        "2026-07-28T13:30:00Z",
        "2026-07-28T13:31:00Z",
        "2026-07-28T13:32:00Z",
    ]

    assert stock.green_minutes == 2
    assert stock.red_minutes == 1
    assert stock.running_high == 4.25
    assert stock.running_low == 4.05


def test_merge_does_not_fabricate_missing_minutes():
    tracker = make_tracker()
    stock = tracker.stocks["OPEN"]

    streamed = {
        "OPEN": [
            make_bar(
                "2026-07-28T13:30:00Z",
                4.10,
                4.20,
                4.05,
                4.15,
            ),
            make_bar(
                "2026-07-28T13:32:00Z",
                4.15,
                4.25,
                4.10,
                4.20,
            ),
        ]
    }

    counts = tracker.merge_stream_bars(streamed)

    assert counts["OPEN"] == 2
    assert len(stock.minute_bars) == 2
    assert all(
        bar["t"] != "2026-07-28T13:31:00Z"
        for bar in stock.minute_bars
    )


def test_reconciliation_merges_late_rest_bar():
    tracker = make_tracker()
    stock = tracker.stocks["OPEN"]

    first_bar = make_bar(
        "2026-07-28T13:30:00Z",
        4.10,
        4.20,
        4.05,
        4.15,
    )

    stock.minute_bars.append(first_bar)
    tracker.process_bar(stock, first_bar)

    tracker.alpaca.get_historical_1min_bars.return_value = {
        "OPEN": [
            first_bar,
            make_bar(
                "2026-07-28T13:31:00Z",
                4.15,
                4.25,
                4.10,
                4.20,
            ),
        ]
    }

    from datetime import datetime

    counts = tracker.reconcile_window(
        window_start=datetime(
            2026,
            7,
            28,
            13,
            30,
        ),
        window_end=datetime(
            2026,
            7,
            28,
            13,
            44,
        ),
        delay_seconds=0,
    )

    assert counts["OPEN"] == 2
    assert len(stock.minute_bars) == 2
    assert stock.green_minutes == 2
