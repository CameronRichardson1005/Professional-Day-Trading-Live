from __future__ import annotations

import csv
from dataclasses import asdict
from datetime import date
from pathlib import Path

from .webull_ten_second_bars import (
    TenSecondBar,
)


TEN_SECOND_BAR_COLUMNS = [
    "symbol",
    "timestamp",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "trades",
    "trading_session",
]


class TenSecondBarRecorder:
    """
    Append-only research recorder for completed
    Webull 10-second OHLCV bars.

    Files are partitioned by trading date:

        data/webull_10s/YYYY-MM-DD.csv

    This recorder is market-data only.
    """

    def __init__(
        self,
        root: str | Path = "data/webull_10s",
    ) -> None:
        self.root = Path(root)

    def path_for_date(
        self,
        trading_date: str | date,
    ) -> Path:
        if isinstance(
            trading_date,
            date,
        ):
            date_str = (
                trading_date.isoformat()
            )
        else:
            date_str = str(
                trading_date
            )

        return (
            self.root
            / f"{date_str}.csv"
        )

    def path_for_bar(
        self,
        bar: TenSecondBar,
    ) -> Path:
        return self.path_for_date(
            bar.timestamp.date()
        )

    @staticmethod
    def row_from_bar(
        bar: TenSecondBar,
    ) -> dict:
        return {
            "symbol": bar.symbol,
            "timestamp": (
                bar.timestamp.isoformat()
            ),
            "open": bar.open,
            "high": bar.high,
            "low": bar.low,
            "close": bar.close,
            "volume": bar.volume,
            "trades": bar.trades,
            "trading_session": (
                bar.trading_session
            ),
        }

    def append_bar(
        self,
        bar: TenSecondBar,
    ) -> Path:
        path = self.path_for_bar(
            bar
        )

        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        write_header = (
            not path.exists()
            or path.stat().st_size == 0
        )

        with path.open(
            "a",
            newline="",
            encoding="utf-8",
        ) as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=(
                    TEN_SECOND_BAR_COLUMNS
                ),
            )

            if write_header:
                writer.writeheader()

            writer.writerow(
                self.row_from_bar(
                    bar
                )
            )

        return path
