import csv
from datetime import (
    date,
    datetime,
    timedelta,
)
from pathlib import Path
from zoneinfo import ZoneInfo

from trading_bot.scanner_master_dataset import (
    ScannerResearchPoint,
    build_atr_history,
    build_master_rows,
    load_webull_scanner_index,
    write_master_csv,
)


EASTERN = ZoneInfo(
    "America/New_York"
)

UTC = ZoneInfo("UTC")


def opening_bar():
    return {
        "t": "2026-03-02T14:30:00Z",
        "o": 10.50,
        "h": 11.50,
        "l": 10.00,
        "c": 10.20,
        "v": 100000,
    }


def complete_minutes():
    start = datetime(
        2026,
        3,
        2,
        9,
        30,
        tzinfo=EASTERN,
    )

    result = []

    for offset in range(390):
        timestamp = (
            start
            + timedelta(
                minutes=offset
            )
        ).astimezone(UTC)

        result.append({
            "t": (
                timestamp
                .isoformat()
                .replace(
                    "+00:00",
                    "Z",
                )
            ),
            "o": 10.20,
            "h": 10.20,
            "l": 10.20,
            "c": 10.20,
            "v": 100,
        })

    return result


def daily_bars():
    start = date(
        2026,
        2,
        1,
    )

    result = []

    for offset in range(20):
        day = (
            start
            + timedelta(
                days=offset
            )
        )

        result.append({
            "t": (
                f"{day.isoformat()}"
                "T21:00:00Z"
            ),
            "o": 10.0,
            "h": 11.0,
            "l": 9.0,
            "c": 10.0,
            "v": 1000000,
        })

    return result


def test_load_scanner_index_keeps_only_webull(tmp_path):
    path = Path(
        tmp_path
    ) / "scanner.csv"

    with path.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "date",
                "source",
                "model",
                "rank",
                "selected",
                "symbol",
                "score",
            ],
        )

        writer.writeheader()

        writer.writerow({
            "date": "2026-03-02",
            "source": "WEBULL",
            "model": "V1_LOG_VOLUME",
            "rank": "1",
            "selected": "YES",
            "symbol": "TEST",
            "score": "4.5",
        })

        writer.writerow({
            "date": "2026-03-02",
            "source": "ALPACA",
            "model": "V1_LOG_VOLUME",
            "rank": "2",
            "selected": "YES",
            "symbol": "OTHER",
            "score": "3.0",
        })

    result = (
        load_webull_scanner_index(
            path
        )
    )

    assert (
        "V1_LOG_VOLUME"
        in result[
            (
                "2026-03-02",
                "TEST",
            )
        ]
    )

    assert (
        (
            "2026-03-02",
            "OTHER",
        )
        not in result
    )


def test_build_atr_history_is_available_for_test_date():
    result = build_atr_history(
        daily_history={
            "TEST": daily_bars(),
        },
        trading_dates=[
            date(
                2026,
                3,
                2,
            ),
        ],
        symbols=[
            "TEST",
        ],
    )

    assert (
        "2026-03-02"
        in result["TEST"]
    )

    assert (
        result["TEST"][
            "2026-03-02"
        ]
        > 0
    )


def test_master_row_joins_scanner_and_realized_data():
    scanner_index = {
        (
            "2026-03-02",
            "TEST",
        ): {
            "V1_LOG_VOLUME": (
                ScannerResearchPoint(
                    model=(
                        "V1_LOG_VOLUME"
                    ),
                    rank=1,
                    selected=True,
                    score=4.5,
                )
            ),
        },
    }

    rows = build_master_rows(
        trading_dates=[
            date(
                2026,
                3,
                2,
            ),
        ],
        symbols=[
            "TEST",
        ],
        scanner_index=(
            scanner_index
        ),
        opening_history={
            "TEST": [
                opening_bar()
            ],
        },
        atr_history={
            "TEST": {
                "2026-03-02": 1.0,
            },
        },
        minute_loader=(
            lambda symbol, date_str:
            complete_minutes()
        ),
    )

    assert len(rows) == 1

    row = rows[0]

    assert (
        row["evaluation_status"]
        == "OK"
    )

    assert row["v1_rank"] == 1
    assert row["v1_selected"] == "YES"

    assert row["v2_rank"] == ""
    assert row["v2_selected"] == ""

    assert (
        row["manipulation_signal"]
        == "INVEST"
    )

    assert (
        row["quick_flip_signal"]
        == "NO INVEST"
    )


    assert (
        row["quick_flip_reversal_time"]
        == ""
    )

    assert (
        row["quick_flip_confirmation_time"]
        == ""
    )

    assert (
        row["missing_minutes"]
        == 0
    )


def test_missing_cache_is_recorded_and_csv_writes(tmp_path):
    rows = build_master_rows(
        trading_dates=[
            date(
                2026,
                3,
                2,
            ),
        ],
        symbols=[
            "TEST",
        ],
        scanner_index={},
        opening_history={
            "TEST": [
                opening_bar()
            ],
        },
        atr_history={
            "TEST": {
                "2026-03-02": 1.0,
            },
        },
        minute_loader=(
            lambda symbol, date_str:
            None
        ),
    )

    assert (
        rows[0][
            "evaluation_status"
        ]
        == "MISSING_MINUTE_CACHE"
    )

    output = (
        Path(tmp_path)
        / "master.csv"
    )

    write_master_csv(
        rows=rows,
        output_path=output,
    )

    assert output.exists()

    with output.open(
        encoding="utf-8"
    ) as handle:
        loaded = list(
            csv.DictReader(
                handle
            )
        )

    assert len(loaded) == 1

    assert (
        loaded[0][
            "evaluation_status"
        ]
        == "MISSING_MINUTE_CACHE"
    )
