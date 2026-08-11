import time
from datetime import datetime, timedelta
from typing import Any

from .alpaca_client import AlpacaClient
from .models import Stock
from .sheets_client import SheetsClient


class MinuteTracker:
    TRACKING_COLUMNS = [
        "Date",
        "Symbol",
        "Running High",
        "Running Low",
        "Last Update Time",
        "Candle Color",
    ]

    def __init__(
        self,
        alpaca: AlpacaClient,
        sheets: SheetsClient | None,
        stocks: dict[str, Stock],
        symbols_csv: str,
        write_sheets: bool = True,
    ) -> None:
        self.alpaca = alpaca
        self.sheets = sheets
        self.stocks = stocks
        self.symbols_csv = symbols_csv
        self.write_sheets = write_sheets

        if self.write_sheets:
            if self.sheets is None:
                raise ValueError(
                    "SheetsClient is required when write_sheets=True."
                )

            self.worksheet = (
                self.sheets.get_or_create_worksheet(
                    title="1 minute intervals",
                    rows=100,
                    cols=6,
                )
            )
        else:
            self.worksheet = None

        self.symbol_rows: dict[str, int] = {}

    def prepare_sheet(self, date_str: str) -> None:
        """
        Guarantee exactly one tracking row per date and symbol.
        Existing duplicate keys are consolidated using their latest row.
        """
        if not self.write_sheets:
            self.symbol_rows = {
                symbol: index
                for index, symbol in enumerate(
                    self.stocks,
                    start=2,
                )
            }
            return

        if self.worksheet is None:
            raise RuntimeError(
                "Tracking worksheet was not initialised."
            )

        existing_values = self.worksheet.get_all_values()

        if (
                existing_values
                and existing_values[0] != self.TRACKING_COLUMNS
        ):
            raise RuntimeError(
                "1 minute intervals has unexpected columns. "
                "The sheet was not modified."
            )

        unique_rows: dict[tuple[str, str], list] = {}

        for row in existing_values[1:]:
            if len(row) < 2 or not row[0] or not row[1]:
                continue

            normalised = list(row[:6])

            if len(normalised) < 6:
                normalised.extend(
                    [""] * (6 - len(normalised))
                )

            key = (normalised[0], normalised[1])
            unique_rows[key] = normalised

        for symbol in self.stocks:
            key = (date_str, symbol)

            if key not in unique_rows:
                unique_rows[key] = [
                    date_str,
                    symbol,
                    "",
                    "",
                    "",
                    "",
                ]

        tracking_rows = list(unique_rows.values())

        self.sheets._rewrite_table(
            worksheet=self.worksheet,
            columns=self.TRACKING_COLUMNS,
            rows=tracking_rows,
            last_column="F",
        )

        self.symbol_rows = {}

        for row_number, row in enumerate(
                tracking_rows,
                start=2,
        ):
            if row[0] == date_str and row[1] in self.stocks:
                self.symbol_rows[row[1]] = row_number

    @staticmethod
    def process_bar(
        stock: Stock,
        bar: dict[str, Any],
    ) -> tuple[bool, bool, str]:
        """
        Update one stock's in-memory state using one 1-minute bar.

        Returns:
            new_high, new_low, candle_color
        """
        minute_open = float(bar["o"])
        minute_close = float(bar["c"])
        minute_high = float(bar["h"])
        minute_low = float(bar["l"])

        candle_color = (
            "GREEN"
            if minute_close > minute_open
            else "RED"
        )

        if candle_color == "GREEN":
            stock.green_minutes += 1
        else:
            stock.red_minutes += 1

        new_high = False
        new_low = False

        if (
            stock.running_high is None
            or minute_high > stock.running_high
        ):
            stock.running_high = minute_high
            stock.new_highs += 1
            new_high = True

        if (
            stock.running_low is None
            or minute_low < stock.running_low
        ):
            stock.running_low = minute_low
            stock.new_lows += 1
            new_low = True

        return new_high, new_low, candle_color

    @staticmethod
    def _bar_timestamp(bar: dict[str, Any]) -> str:
        """
        Return the Alpaca timestamp used to deduplicate bars.
        """
        return str(bar.get("t", ""))

    @staticmethod
    def _reset_tracking_state(stock: Stock) -> None:
        """
        Reset minute-derived fields before a chronological rebuild.
        """
        stock.running_high = None
        stock.running_low = None
        stock.minute_bars = []
        stock.green_minutes = 0
        stock.red_minutes = 0
        stock.new_highs = 0
        stock.new_lows = 0

    def merge_stream_bars(
        self,
        streamed_bars: dict[str, list[dict[str, Any]]],
    ) -> dict[str, int]:
        """
        Merge WebSocket bars and updated bars into the REST results.

        Bars are deduplicated by timestamp and rebuilt chronologically.
        A later WebSocket updated bar replaces an earlier version.
        """
        processed_counts: dict[str, int] = {}
        sheet_updates: list[dict[str, Any]] = []

        for symbol, stock in self.stocks.items():
            unique_bars: dict[str, dict[str, Any]] = {}

            for bar in stock.minute_bars:
                timestamp = self._bar_timestamp(bar)
                if timestamp:
                    unique_bars[timestamp] = bar

            for bar in streamed_bars.get(symbol, []):
                timestamp = self._bar_timestamp(bar)
                if timestamp:
                    unique_bars[timestamp] = bar

            ordered_bars = [
                unique_bars[timestamp]
                for timestamp in sorted(unique_bars)
            ]

            self._reset_tracking_state(stock)

            last_candle_color = ""

            for bar in ordered_bars:
                stock.minute_bars.append(bar)
                _, _, last_candle_color = self.process_bar(
                    stock=stock,
                    bar=bar,
                )

            processed_counts[symbol] = len(ordered_bars)

            if (
                ordered_bars
                and symbol in self.symbol_rows
                and stock.running_high is not None
                and stock.running_low is not None
            ):
                sheet_updates.append(
                    {
                        "symbol": symbol,
                        "row": self.symbol_rows[symbol],
                        "running_high": round(
                            stock.running_high,
                            4,
                        ),
                        "running_low": round(
                            stock.running_low,
                            4,
                        ),
                        "time_label": "09:45",
                        "candle_color": last_candle_color,
                        "new_high": False,
                        "new_low": False,
                    }
                )

        if (
            sheet_updates
            and self.write_sheets
            and self.sheets is not None
            and self.worksheet is not None
        ):
            self.sheets.update_tracking_minute(
                worksheet=self.worksheet,
                updates=sheet_updates,
            )

        return processed_counts

    def reconcile_window(
        self,
        window_start: datetime,
        window_end: datetime,
        delay_seconds: int = 3,
    ) -> dict[str, int]:
        """
        Re-fetch the complete opening window and rebuild each stock
        chronologically from genuine IEX/SIP bars.

        Existing valid bars are retained. Missing timestamps are filled
        only when Alpaca supplies a real bar.
        """
        if delay_seconds > 0:
            time.sleep(delay_seconds)

        start_iso = window_start.strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        end_iso = (
            window_end + timedelta(seconds=59)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")

        try:
            fetched = self.alpaca.get_historical_1min_bars(
                symbols_csv=self.symbols_csv,
                start_iso=start_iso,
                end_iso=end_iso,
            )
        except Exception as error:
            print(
                f"Opening-window reconciliation failed: {error}",
                flush=True,
            )
            return {
                symbol: len(stock.minute_bars)
                for symbol, stock in self.stocks.items()
            }

        expected_bars = (
            int(
                (window_end - window_start).total_seconds()
                // 60
            )
            + 1
        )

        processed_counts: dict[str, int] = {}
        sheet_updates: list[dict[str, Any]] = []

        for symbol, stock in self.stocks.items():
            unique_bars: dict[str, dict[str, Any]] = {}

            for bar in stock.minute_bars:
                timestamp = self._bar_timestamp(bar)
                if timestamp:
                    unique_bars[timestamp] = bar

            for bar in fetched.get(symbol, []):
                timestamp = self._bar_timestamp(bar)
                if timestamp:
                    unique_bars[timestamp] = bar

            ordered_bars = [
                unique_bars[timestamp]
                for timestamp in sorted(unique_bars)
            ]

            self._reset_tracking_state(stock)

            last_candle_color = ""

            for bar in ordered_bars:
                stock.minute_bars.append(bar)
                _, _, last_candle_color = self.process_bar(
                    stock=stock,
                    bar=bar,
                )

            processed = len(ordered_bars)
            processed_counts[symbol] = processed

            if processed < expected_bars:
                print(
                    f"{symbol}: reconciliation finished with "
                    f"{processed}/{expected_bars} real bars.",
                    flush=True,
                )
            else:
                print(
                    f"{symbol}: reconciliation completed with "
                    f"{processed}/{expected_bars} bars.",
                    flush=True,
                )

            if (
                processed > 0
                and symbol in self.symbol_rows
                and stock.running_high is not None
                and stock.running_low is not None
            ):
                sheet_updates.append(
                    {
                        "symbol": symbol,
                        "row": self.symbol_rows[symbol],
                        "running_high": round(
                            stock.running_high,
                            4,
                        ),
                        "running_low": round(
                            stock.running_low,
                            4,
                        ),
                        "time_label": "09:45",
                        "candle_color": last_candle_color,
                        "new_high": False,
                        "new_low": False,
                    }
                )

        if (
            sheet_updates
            and self.write_sheets
            and self.sheets is not None
            and self.worksheet is not None
        ):
            self.sheets.update_tracking_minute(
                worksheet=self.worksheet,
                updates=sheet_updates,
            )

        if (
            self.write_sheets
            and self.sheets is not None
            and hasattr(
                self.sheets,
                "write_minute_bars_history",
            )
        ):
            try:
                date_values = {
                    str(bar.get("t", ""))[:10]
                    for stock in self.stocks.values()
                    for bar in stock.minute_bars
                    if bar.get("t")
                }

                if len(date_values) == 1:
                    archive_date = next(
                        iter(date_values)
                    )
                else:
                    archive_date = (
                        window_start.strftime(
                            "%Y-%m-%d"
                        )
                    )

                from .config import MARKET_DATA_FEED

                self.sheets.write_minute_bars_history(
                    date_str=archive_date,
                    stocks=self.stocks,
                    data_feed=MARKET_DATA_FEED,
                    source="LIVE",
                )
            except Exception as error:
                print(
                    "Minute Bars History update failed. "
                    "Live processing will continue."
                )
                print(
                    f"Minute history error: {error}"
                )

        return processed_counts

    def track_window(
        self,
        date_str: str,
        window_start: datetime,
        window_end: datetime,
    ) -> None:
        """
        Fetch and process one completed bar per minute in real time.
        """
        self.prepare_sheet(date_str)

        current_minute = window_start

        while current_minute <= window_end:
            self.wait_for_bar_completion(current_minute)

            minute_start_iso = current_minute.strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )

            minute_end_iso = (
                current_minute + timedelta(seconds=59)
            ).strftime("%Y-%m-%dT%H:%M:%SZ")

            time_label = current_minute.strftime("%H:%M")

            try:
                bars = self.alpaca.get_1min_bars(
                    symbols_csv=self.symbols_csv,
                    start_iso=minute_start_iso,
                    end_iso=minute_end_iso,
                )

            except Exception as error:
                print(
                    f"Could not fetch bars for {time_label}: {error}",
                    flush=True,
                )

                bars = {
                    symbol: None
                    for symbol in self.stocks
                }

            tracking_updates: list[dict[str, Any]] = []

            for symbol, stock in self.stocks.items():
                bar = bars.get(symbol)

                if bar is None:
                    print(
                        f"{symbol}: no bar for {time_label}",
                        flush=True,
                    )
                    continue

                timestamp = self._bar_timestamp(bar)

                if (
                    timestamp
                    and all(
                        self._bar_timestamp(existing) != timestamp
                        for existing in stock.minute_bars
                    )
                ):
                    stock.minute_bars.append(bar)

                new_high, new_low, candle_color = self.process_bar(
                    stock=stock,
                    bar=bar,
                )

                row_number = self.symbol_rows[symbol]

                tracking_updates.append(
                    {
                        "symbol": symbol,
                        "row": row_number,
                        "running_high": round(
                            stock.running_high,
                            4,
                        ),
                        "running_low": round(
                            stock.running_low,
                            4,
                        ),
                        "time_label": time_label,
                        "candle_color": candle_color,
                        "new_high": new_high,
                        "new_low": new_low,
                    }
                )

            if (
                tracking_updates
                and self.write_sheets
                and self.sheets is not None
                and self.worksheet is not None
            ):
                self.sheets.update_tracking_minute(
                    worksheet=self.worksheet,
                    updates=tracking_updates,
                )

            print(
                f"1-minute update logged for {time_label}",
                flush=True,
            )

            current_minute += timedelta(minutes=1)

        print(
            "Reconciling the complete opening window...",
            flush=True,
        )

        self.reconcile_window(
            window_start=window_start,
            window_end=window_end,
        )

        print(
            "Finished real-time 1-minute tracking window.",
            flush=True,
        )

    @staticmethod
    def wait_for_bar_completion(
        bar_start: datetime,
        delay_seconds: int = 2,
    ) -> None:
        """
        Wait until the requested minute has fully completed.

        The small delay gives Alpaca time to publish the completed bar.
        """
        bar_available_time = (
            bar_start
            + timedelta(minutes=1)
            + timedelta(seconds=delay_seconds)
        )

        sleep_seconds = (
            bar_available_time - datetime.utcnow()
        ).total_seconds()

        if sleep_seconds > 0:
            time.sleep(sleep_seconds)

    def test_historical_minute(
            self,
            date_str: str,
            time_str: str,
    ) -> None:
        test_minute = datetime.strptime(
            f"{date_str}T{time_str}:00",
            "%Y-%m-%dT%H:%M:%S",
        )

        minute_start_iso = test_minute.strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )

        minute_end_iso = (
                test_minute + timedelta(seconds=59)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")

        self.prepare_sheet(date_str)

        bars = self.alpaca.get_1min_bars(
            symbols_csv=self.symbols_csv,
            start_iso=minute_start_iso,
            end_iso=minute_end_iso,
        )

        updates = []

        for symbol, stock in self.stocks.items():
            bar = bars.get(symbol)

            if bar is None:
                print(f"{symbol}: no historical test bar")
                continue

            new_high, new_low, candle_color = self.process_bar(
                stock=stock,
                bar=bar,
            )

            updates.append(
                {
                    "symbol": symbol,
                    "row": self.symbol_rows[symbol],
                    "running_high": round(stock.running_high, 4),
                    "running_low": round(stock.running_low, 4),
                    "time_label": time_str,
                    "candle_color": candle_color,
                    "new_high": new_high,
                    "new_low": new_low,
                }
            )

        if updates:
            self.sheets.update_tracking_minute(
                worksheet=self.worksheet,
                updates=updates,
            )

        print(f"Historical tracker test completed for {date_str} {time_str}")