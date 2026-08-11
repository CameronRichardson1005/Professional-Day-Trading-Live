import csv
import os
import time as time_module
import subprocess

from contextlib import redirect_stdout
from dataclasses import asdict
from datetime import UTC, datetime, time, timedelta
from io import StringIO
from pathlib import Path
from threading import Event, Thread
from zoneinfo import ZoneInfo

from .webull_preview_service import WebullPreviewService
from .webull_preview_store import (
    WebullPreviewStore,
    WebullPreviewStoreError,
)
from .webull_account_snapshot import (
    WebullAccountSnapshotClient,
)
from .webull_approval import (
    WebullApprovalError,
    WebullApprovalQueue,
    WebullApprovalTicket,
)
from .webull_approval_store import (
    WebullApprovalStore,
    WebullApprovalStoreError,
)
from .alpaca_client import AlpacaClient
from .fibonacci_research import FibonacciResearchReport
from .fibonacci_paper import (
    FibonacciPaperLedger,
    build_fibonacci_paper_record,
)
from .fibonacci_retracement import (
    FIBONACCI_LEVELS,
    FibonacciRetracementReport,
    analyse_retracement_level,
    analyse_symbol_day,
    analyse_symbol_day_multiple_impulses,
    metrics_for,
    stopped_out_then_target,
)
from .fibonacci_strategy import Fibonacci618Strategy
from .quick_flip_webull_preview_service import (
    QuickFlipWebullPreviewService,
)
from .quick_flip_monitor import (
    QuickFlipMonitor,
    reconcile_minute_bars,
)
from .quick_flip_strategy import QuickFlipCandle

from .backtest import (
    BacktestReport,
    ReplaySession,
    market_regimes_by_date,
    weekday_dates,
)
from .config import (
    ACTIVE_STRATEGY,
    CANDIDATE_TICKERS,
    FIBONACCI_MONITOR_CUTOFF,
    FIBONACCI_MONITOR_INTERVAL_SECONDS,
    FIBONACCI_MONITOR_START,
    FIBONACCI_STRATEGY_NAME,
    MANIPULATION_STRATEGY_NAME,
    MARKET_DATA_FEED,
    NEW_TRADING_SPREADSHEET_ID,
    QUICK_FLIP_MONITOR_CUTOFF,
    QUICK_FLIP_MONITOR_INTERVAL_SECONDS,
    QUICK_FLIP_MONITOR_START,
    TICKERS,
)
from .dashboard_exporter import DashboardExporter
from .models import Stock
from .webull_trade_history import (
    WebullTradeHistoryClient,
    calculate_fifo_realized_trades,
    summarize_realized_trades,
)
from .webull_safety import WebullOrderProposal
from .webull_paper_order_service import (
    WebullPaperOrderService,
    WebullPaperOrderServiceError,
)
from .webull_paper_order_store import (
    WebullPaperOrderRecord,
)
from .webull_paper_performance import (
    load_webull_paper_daily_performance,
)
from .webull_paper_analytics import (
    load_webull_paper_analytics,
)
from .fibonacci_paper_evaluation import (
    load_fibonacci_paper_evaluation,
)

from .webull_paper_portfolio import (
    latest_prices_from_completed_bars,
    load_webull_paper_portfolio,
)
from .webull_paper_risk import (
    load_webull_paper_risk_status,
)
from .replay import HistoricalReplay
from .scanner import StockScanner
from .sheets_client import SheetsClient
from .stream_client import AlpacaStockStream
from .strategy import ManipulationStrategy
from .tracker import MinuteTracker


class TradingBot:
    def __init__(self) -> None:
        self.stocks = {
            symbol: Stock(symbol=symbol)
            for symbol in TICKERS
        }

        self.symbols_csv = ",".join(self.stocks.keys())

        self.alpaca = AlpacaClient()
        # Preserved manipulation engine for historical replay,
        # comparison, and audit work.
        self.strategy = ManipulationStrategy()

        # Separate active paper/preview Fibonacci adapter.
        self.fibonacci_strategy = Fibonacci618Strategy()

        # Quick Flip remains completely independent from the
        # Stock fields used by the preserved Manipulation strategy.
        #
        # Quick Flip results are stored by symbol so running it
        # cannot overwrite Manipulation signal, entry, target,
        # or stop-loss values.
        self.quick_flip_monitor = QuickFlipMonitor()
        self.quick_flip_results = {}
        self.quick_flip_status = {}

        self.scanner = StockScanner(
            current_symbols=TICKERS,
        )
        self.scanner_statistics = None
        self.symbol_reliability = None

        # Legacy workbook used by the existing tracker and
        # historical workflow.
        self.sheets = None

        # Separate clean workbook for Manipulation + Quick Flip.
        # This never replaces self.sheets.
        self.trading_sheets = None

        self.tracker = None
        self.dashboard = DashboardExporter()

        # Static Fibonacci data is cached per session so the
        # live monitor does not repeatedly request the same
        # opening bars and ATR history from Alpaca.
        self._fibonacci_session_static_cache = {}
        self._fibonacci_intraday_bar_cache = {}
        self._fibonacci_performance_metrics = {}

        try:
            self.webull_approval_queue = (
                WebullApprovalQueue(
                    store=WebullApprovalStore(),
                )
            )
        except WebullApprovalStoreError as error:
            self.webull_approval_queue = None
            print(
                "Webull approval store unavailable. "
                "Dashboard approval records will be omitted. "
                f"Reason: {error}"
            )

    def refresh_symbols_for_date(
            self,
            date_str: str,
            data_feed: str = MARKET_DATA_FEED,
    ) -> list[str]:
        self.scanner_statistics = None
        self.symbol_reliability = None

        fallback_symbols = list(
            self.scanner.current_symbols
        )

        try:
            statistics = (
                self.alpaca.get_scanner_statistics(
                    symbols_csv=",".join(
                        CANDIDATE_TICKERS
                    ),
                    date_str=date_str,
                    feed=data_feed,
                )
            )

            reliability = None

            try:
                reliability = (
                    self.alpaca.get_opening_reliability(
                        symbols_csv=",".join(
                            dict.fromkeys(
                                TICKERS
                                + CANDIDATE_TICKERS
                            )
                        ),
                        date_str=date_str,
                        feed=data_feed,
                    )
                )
            except Exception as reliability_error:
                print(
                    "Opening reliability check failed. "
                    "Continuing without reliability filtering. "
                    f"Reason: {reliability_error}"
                )

            selected_symbols = (
                self.scanner.select_symbols(
                    statistics,
                    reliability=reliability,
                )
            )

            if reliability is not None:
                for record in reliability:
                    print(
                        f"{record.symbol}: "
                        f"{data_feed.upper()} opening reliability "
                        f"{record.completeness:.1%} across "
                        f"{record.usable_days} day(s)."
                    )

            if reliability is not None:
                selected_set = set(selected_symbols)

                for record in reliability:
                    if (
                        record.usable_days
                        < self.scanner.rules.minimum_reliability_days
                    ):
                        status = (
                            "FALLBACK - INSUFFICIENT HISTORY"
                        )
                    elif record.symbol in selected_set:
                        status = "SELECTED"
                    elif (
                        record.completeness
                        < self.scanner.rules.minimum_opening_completeness
                    ):
                        status = (
                            "EXCLUDED - LOW IEX RELIABILITY"
                        )
                    else:
                        status = (
                            "NOT SELECTED - RANKING LIMIT"
                        )

                    print(
                        f"{record.symbol}: {status}"
                    )

            if reliability is not None:
                selected_set = set(selected_symbols)
                reliability_payload = []

                for record in reliability:
                    if (
                        record.usable_days
                        < self.scanner.rules.minimum_reliability_days
                    ):
                        status = (
                            "FALLBACK_INSUFFICIENT_HISTORY"
                        )
                    elif record.symbol in selected_set:
                        status = "SELECTED"
                    elif (
                        record.completeness
                        < self.scanner.rules.minimum_opening_completeness
                    ):
                        status = (
                            "EXCLUDED_LOW_RELIABILITY"
                        )
                    else:
                        status = (
                            "NOT_SELECTED_RANKING_LIMIT"
                        )

                    reliability_payload.append(
                        {
                            "symbol": record.symbol,
                            "completeness": round(
                                record.completeness,
                                6,
                            ),
                            "usableDays": (
                                record.usable_days
                            ),
                            "totalBars": (
                                record.total_bars
                            ),
                            "expectedBars": (
                                record.expected_bars
                            ),
                            "status": status,
                        }
                    )

                self.symbol_reliability = (
                    reliability_payload
                )

            self.scanner_statistics = statistics

        except Exception as error:
            print(
                "Stock scanner failed. "
                "Using existing tickers."
            )
            print(f"Scanner error: {error}")

            selected_symbols = fallback_symbols

        existing_stocks = self.stocks

        self.stocks = {
            symbol: existing_stocks.get(
                symbol,
                Stock(symbol=symbol),
            )
            for symbol in selected_symbols
        }

        self.symbols_csv = ",".join(selected_symbols)

        # Rebuild the tracker when Sheets are next
        # initialised so it receives the new symbols.
        self.tracker = None

        print(
            "Selected symbols:",
            ", ".join(selected_symbols),
        )

        return selected_symbols

    def initialise_trading_sheets(
            self,
    ) -> None:
        """
        Initialise the separate clean Manipulation + Quick Flip
        workbook.

        This method never changes the legacy self.sheets client.
        """
        if self.trading_sheets is not None:
            return

        if not NEW_TRADING_SPREADSHEET_ID:
            raise RuntimeError(
                "NEW_TRADING_SPREADSHEET_ID is not configured."
            )

        self.trading_sheets = SheetsClient(
            spreadsheet_id=(
                NEW_TRADING_SPREADSHEET_ID
            ),
        )

    def initialise_sheets(
            self,
            write_sheets: bool = True,
    ) -> None:
        if write_sheets and self.sheets is None:
            self.sheets = SheetsClient()

        if self.tracker is None:
            self.tracker = MinuteTracker(
                alpaca=self.alpaca,
                sheets=self.sheets,
                stocks=self.stocks,
                symbols_csv=self.symbols_csv,
                write_sheets=write_sheets,
            )

    def write_new_trading_scanner(
            self,
            date_str: str,
            selected_symbols,
    ) -> None:
        """
        Write the scanner view to the separate clean
        Manipulation + Quick Flip workbook.
        """
        self.initialise_trading_sheets()

        if self.trading_sheets is None:
            raise RuntimeError(
                "New trading workbook was not initialised."
            )

        if self.scanner_statistics is None:
            return

        self.trading_sheets.write_scanner_dashboard(
            date_str=date_str,
            statistics=self.scanner_statistics,
            selected_symbols=selected_symbols,
            scanner=self.scanner,
        )

    def write_new_manipulation_results(
            self,
            date_str: str,
    ) -> None:
        """
        Copy the current preserved Manipulation strategy state
        into the separate clean trading workbook.

        The legacy workbook is not modified by this method.
        """
        self.initialise_trading_sheets()

        if self.trading_sheets is None:
            raise RuntimeError(
                "New trading workbook was not initialised."
            )

        self.trading_sheets.write_strategy_results(
            date_str=date_str,
            stocks=self.stocks,
            sheet_name="Manipulation Signals",
        )

    def write_new_quick_flip_results(
            self,
            date_str: str,
    ) -> None:
        """
        Reconcile Quick Flip signals and Webull previews into
        the separate clean trading workbook.

        Quick Flip remains long-only with no automatic stop
        and no broker submission.
        """
        self.initialise_trading_sheets()

        if self.trading_sheets is None:
            raise RuntimeError(
                "New trading workbook was not initialised."
            )

        self.trading_sheets.write_quick_flip_results(
            date_str=date_str,
            results=self.quick_flip_results,
            sheet_name="Quick Flip Signals",
        )

        self.trading_sheets.write_quick_flip_previews(
            date_str=date_str,
            previews=getattr(
                self,
                "quick_flip_webull_previews",
                [],
            ),
            sheet_name="Quick Flip Previews",
        )

        self.write_trade_previews_dashboard(
            date_str=date_str,
        )

    def write_trade_previews_dashboard(
            self,
            date_str: str,
    ) -> None:
        """
        Rebuild the concise today-only preview dashboard from
        Manipulation and Quick Flip PREVIEW READY records.
        """
        from datetime import datetime
        from zoneinfo import ZoneInfo

        self.initialise_trading_sheets()

        if self.trading_sheets is None:
            raise RuntimeError(
                "New trading workbook was not initialised."
            )

        eastern = ZoneInfo("America/New_York")

        previews = []

        for stock in getattr(
            self,
            "stocks",
            {},
        ).values():
            preview = getattr(
                stock,
                "webull_preview",
                None,
            )

            if (
                not isinstance(preview, dict)
                or preview.get("status")
                != "PREVIEW READY"
            ):
                continue

            previews.append({
                "time": datetime.now(
                    eastern
                ).strftime("%H:%M:%S"),
                "strategy": "Manipulation",
                "symbol": stock.symbol,
                "entry": preview.get(
                    "limitBuy",
                    "",
                ),
                "exit": preview.get(
                    "target",
                    "",
                ),
                "quantity": preview.get(
                    "quantity",
                    "",
                ),
                "status": "PREVIEW READY",
            })

        for preview in getattr(
            self,
            "quick_flip_webull_previews",
            [],
        ):
            if (
                not isinstance(preview, dict)
                or preview.get("status")
                != "PREVIEW READY"
            ):
                continue

            tp1 = preview.get(
                "takeProfit1",
                "",
            )
            tp2 = preview.get(
                "takeProfit2",
                "",
            )

            if tp1 != "" and tp2 != "":
                exit_value = (
                    f"{tp1} / {tp2}"
                )
            elif tp1 != "":
                exit_value = tp1
            else:
                exit_value = tp2

            previews.append({
                "time": datetime.now(
                    eastern
                ).strftime("%H:%M:%S"),
                "strategy": "Quick Flip",
                "symbol": preview.get(
                    "symbol",
                    "",
                ),
                "entry": preview.get(
                    "limitBuy",
                    "",
                ),
                "exit": exit_value,
                "quantity": preview.get(
                    "quantity",
                    "",
                ),
                "status": "PREVIEW READY",
            })

        self.trading_sheets.write_trade_previews_today(
            date_str=date_str,
            previews=previews,
            sheet_name="Trade Previews",
        )

    def write_new_minute_bars_history(
            self,
            date_str: str,
            bars_by_symbol: dict,
            source: str,
            data_feed: str = MARKET_DATA_FEED,
    ) -> None:
        """
        Archive genuine reconciled one-minute bars in the
        separate trading workbook.

        Missing minutes are never fabricated.
        """
        self.initialise_trading_sheets()

        if self.trading_sheets is None:
            raise RuntimeError(
                "New trading workbook was not initialised."
            )

        self.trading_sheets.write_minute_bars_history(
            date_str=date_str,
            bars_by_symbol=bars_by_symbol,
            data_feed=data_feed,
            source=source,
        )

    @staticmethod
    def _notify_webull_daily_pnl(
            summary,
    ) -> None:
        """
        Show a macOS notification after Webull daily P&L
        has been calculated and written successfully.

        Notification failure never interrupts the P&L workflow.
        """
        pnl = float(summary.realized_pnl)

        pnl_text = (
            f"+${pnl:.2f}"
            if pnl > 0
            else (
                f"-${abs(pnl):.2f}"
                if pnl < 0
                else "$0.00"
            )
        )

        title = "Webull Daily P&L Updated"

        message = (
            f"{summary.date} · "
            f"{summary.closed_trades} closed trades · "
            f"{summary.winning_trades} wins · "
            f"{summary.losing_trades} losses · "
            f"P&L {pnl_text}"
        )

        safe_title = (
            title
            .replace("\\", "\\\\")
            .replace('"', '\\"')
        )

        safe_message = (
            message
            .replace("\\", "\\\\")
            .replace('"', '\\"')
        )

        script = (
            'display notification '
            f'"{safe_message}" '
            f'with title "{safe_title}"'
        )

        try:
            subprocess.run(
                [
                    "osascript",
                    "-e",
                    script,
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
        except Exception as error:
            print(
                "WARNING: Webull P&L notification "
                f"failed: {error}"
            )

    def write_webull_daily_pnl(
            self,
            date_str: str,
            history_client=None,
    ):
        """
        Read Webull order history and write realized daily P&L
        to the separate trading workbook.

        READ ONLY:
        - no order submission
        - no order cancellation
        - no order replacement
        """
        self.initialise_trading_sheets()

        if self.trading_sheets is None:
            raise RuntimeError(
                "New trading workbook was not initialised."
            )

        client = (
            history_client
            if history_client is not None
            else WebullTradeHistoryClient()
        )

        fills = client.get_recent_fills()

        trades, remaining = (
            calculate_fifo_realized_trades(
                fills,
                date_str,
            )
        )

        summary = summarize_realized_trades(
            trades,
            date_str,
        )

        self.trading_sheets.write_webull_trade_pnl(
            date_str=date_str,
            trades=trades,
            remaining=remaining,
        )

        self.trading_sheets.write_webull_pnl_summary(
            summary=summary,
        )

        self._notify_webull_daily_pnl(
            summary
        )

        print()
        print("===================================")
        print(" Webull Daily Trade P&L")
        print("===================================")
        print(f"Trading date: {date_str}")
        print(
            f"Closed trades: {summary.closed_trades}"
        )
        print(
            f"Winning trades: {summary.winning_trades}"
        )
        print(
            f"Losing trades: {summary.losing_trades}"
        )
        print(
            f"Gross realized P&L: "
            f"${summary.realized_pnl:.2f}"
        )
        print(
            "Source: READ-ONLY WEBULL ORDER HISTORY"
        )
        print(
            "No broker orders were submitted."
        )

        return {
            "trades": trades,
            "remaining": remaining,
            "summary": summary,
        }

    def run(self) -> None:
        print("===================================")
        print(" Professional Day Trading Bot")
        print("===================================")
        print()

        print("Tracking")

        for stock in self.stocks.values():
            print(stock.symbol)

        print()
        print("Testing Alpaca market-data connection...")

        try:
            recent_bars = self.alpaca.test_connection(
                self.symbols_csv
            )

            successful_symbols = [
                symbol
                for symbol, bar in recent_bars.items()
                if bar is not None
            ]

            missing_symbols = [
                symbol
                for symbol, bar in recent_bars.items()
                if bar is None
            ]

            print("Alpaca connection successful.")
            print(
                "Symbols returned:",
                ", ".join(successful_symbols),
            )

            if missing_symbols:
                print(
                    "No recent bars returned for:",
                    ", ".join(missing_symbols),
                )

        except Exception as error:
            print("Alpaca connection test failed.")
            print(f"Error: {error}")
            return

        print()
        print("Testing Google Sheets connection...")

        try:
            self.initialise_sheets()

            worksheet_names = self.sheets.test_connection()

            print("Google Sheets connection successful.")
            print(
                "Worksheets:",
                ", ".join(worksheet_names),
            )

        except Exception as error:
            print("Google Sheets connection test failed.")
            print(f"Error: {error}")
            return

        print()
        print("Bot Started Successfully")

    def run_scanner_smoke(
            self,
            date_str: str | None = None,
    ) -> bool:
        if date_str is None:
            eastern = ZoneInfo(
                "America/New_York"
            )
            date_str = (
                datetime.now(eastern)
                .date()
                .isoformat()
            )

        print()
        print("===================================")
        print(" Scanner Dashboard Smoke Test")
        print("===================================")
        print(f"Scanner date: {date_str}")

        selected_symbols = (
            self.refresh_symbols_for_date(date_str)
        )

        if self.scanner_statistics is None:
            print(
                "Smoke test failed because scanner "
                "statistics were unavailable."
            )
            return False

        if self.sheets is None:
            self.sheets = SheetsClient()

        self.sheets.write_scanner_dashboard(
            date_str=date_str,
            statistics=self.scanner_statistics,
            selected_symbols=selected_symbols,
            scanner=self.scanner,
        )

        print()
        print(
            "Scanner dashboard smoke test "
            "completed successfully."
        )
        print(
            "No minute tracking, strategy, or "
            "order workflow was started."
        )

        return True

    def run_preflight(
            self,
            date_str: str | None = None,
    ) -> bool:
        if date_str is None:
            eastern = ZoneInfo(
                "America/New_York"
            )
            date_str = (
                datetime.now(eastern)
                .date()
                .isoformat()
            )

        print()
        print("===================================")
        print(" Trading Bot Preflight")
        print("===================================")
        print(f"Preflight date: {date_str}")

        selected_symbols = (
            self.refresh_symbols_for_date(date_str)
        )

        if self.scanner_statistics is None:
            print(
                "Preflight failed: scanner statistics "
                "were unavailable."
            )
            return False

        if not selected_symbols:
            print(
                "Preflight failed: no symbols were "
                "selected."
            )
            return False

        print("Scanner check passed.")
        print(
            "Checking Google Sheets and tracker "
            "initialisation..."
        )

        try:
            self.initialise_sheets()
            worksheet_names = (
                self.sheets.test_connection()
            )
        except Exception as error:
            print(
                "Preflight failed during Google Sheets "
                "or tracker initialisation."
            )
            print(f"Preflight error: {error}")
            return False

        required_worksheets = {
            "Scanner Dashboard",
            "1 minute intervals",
        }

        missing_worksheets = sorted(
            required_worksheets.difference(
                worksheet_names
            )
        )

        if missing_worksheets:
            print(
                "Preflight failed: missing worksheets: "
                + ", ".join(missing_worksheets)
            )
            return False

        if self.tracker is None:
            print(
                "Preflight failed: minute tracker was "
                "not initialised."
            )
            return False

        print("Google Sheets check passed.")
        print("Minute tracker initialisation passed.")
        print()
        print("Preflight completed successfully.")
        print(
            "No minute tracking, strategy, dashboard "
            "write, or order workflow was started."
        )

        return True

    def run_live_tracker(
            self,
            write_sheets: bool = True,
            publish_dashboard: bool = True,
    ) -> None:
        eastern = ZoneInfo("America/New_York")
        utc = ZoneInfo("UTC")

        today_eastern = datetime.now(eastern).date()

        market_open_eastern = datetime.combine(
            today_eastern,
            time(hour=9, minute=30),
            tzinfo=eastern,
        )

        market_end_eastern = datetime.combine(
            today_eastern,
            time(hour=9, minute=44),
            tzinfo=eastern,
        )

        now_eastern = datetime.now(eastern)
        earliest_start = (
            market_open_eastern
            - timedelta(minutes=10)
        )
        latest_start = (
            market_end_eastern
            + timedelta(minutes=6)
        )

        if now_eastern < earliest_start:
            print(
                "Live workflow skipped: current New York "
                "time is earlier than 09:20."
            )
            return

        if now_eastern > latest_start:
            print(
                "Live workflow skipped: the 09:30–09:45 "
                "opening window has already passed."
            )
            return

        window_start = market_open_eastern.astimezone(
            utc
        ).replace(tzinfo=None)

        window_end = market_end_eastern.astimezone(
            utc
        ).replace(tzinfo=None)

        date_str = today_eastern.strftime("%Y-%m-%d")

        selected_symbols = (
            self.refresh_symbols_for_date(date_str)
        )
        self.initialise_sheets(
            write_sheets=write_sheets,
        )

        if not write_sheets:
            print(
                "DRY-RUN MODE: Google Sheets and "
                "scanner-dashboard writes are disabled."
            )
        elif self.scanner_statistics is not None:
            try:
                self.sheets.write_scanner_dashboard(
                    date_str=date_str,
                    statistics=self.scanner_statistics,
                    selected_symbols=selected_symbols,
                    scanner=self.scanner,
                )
            except Exception as error:
                print(
                    "Scanner dashboard update failed. "
                    "Live tracking will continue."
                )
                print(f"Dashboard error: {error}")
        else:
            print(
                "Scanner dashboard skipped because "
                "scanner statistics were unavailable."
            )

        if (
            write_sheets
            and self.scanner_statistics is not None
        ):
            try:
                self.write_new_trading_scanner(
                    date_str=date_str,
                    selected_symbols=selected_symbols,
                )
                print(
                    "New trading workbook scanner "
                    "updated successfully."
                )
            except Exception as error:
                print(
                    "WARNING: New trading workbook "
                    "scanner write failed. "
                    "Live tracking will continue."
                )
                print(
                    f"New workbook error: {error}"
                )

        print()
        print("Starting real-time 1-minute tracker...")
        print(
            "Tracking window:",
            market_open_eastern.strftime("%H:%M"),
            "to",
            "09:45",
            "New York time",
        )

        stream_result: dict[str, object] = {
            "bars": {},
            "error": None,
        }

        stream_stop_time = (
            window_end
            + timedelta(minutes=1)
            + timedelta(seconds=5)
        )

        def collect_stream() -> None:
            try:
                stream = AlpacaStockStream(
                    symbols=selected_symbols,
                    feed=MARKET_DATA_FEED,
                )
                stream_result["bars"] = (
                    stream.collect_until(
                        stop_time=stream_stop_time,
                    )
                )
            except Exception as error:
                stream_result["error"] = error

        stream_thread = Thread(
            target=collect_stream,
            name="alpaca-market-data-stream",
            daemon=True,
        )

        print(
            f"Starting {MARKET_DATA_FEED.upper()} "
            "WebSocket collector..."
        )
        stream_thread.start()

        self.tracker.track_window(
            date_str=date_str,
            window_start=window_start,
            window_end=window_end,
        )

        stream_thread.join(timeout=10)

        stream_error = stream_result.get("error")
        streamed_bars = stream_result.get("bars", {})

        if stream_thread.is_alive():
            print(
                "WebSocket collector did not stop in time. "
                "Continuing with reconciled REST bars."
            )
        elif stream_error is not None:
            print(
                "WebSocket collector failed. "
                "Reconciled REST tracking was preserved."
            )
            print(f"WebSocket error: {stream_error}")
        elif isinstance(streamed_bars, dict):
            streamed_count = sum(
                len(bars)
                for bars in streamed_bars.values()
                if isinstance(bars, list)
            )

            if streamed_count > 0:
                print(
                    f"Merging {streamed_count} WebSocket bar(s)..."
                )

                self.tracker.merge_stream_bars(
                    streamed_bars=streamed_bars,
                )
            else:
                print(
                    "No WebSocket bars were available to merge."
                )

            print(
                "WebSocket bars merged successfully."
            )

        if write_sheets:
            opening_stocks = getattr(
                self,
                "stocks",
                {},
            )

            opening_bars_by_symbol = {
                symbol: list(
                    getattr(
                        stock,
                        "minute_bars",
                        [],
                    )
                )
                for symbol, stock
                in opening_stocks.items()
            }

            if opening_bars_by_symbol:
                try:
                    self.write_new_minute_bars_history(
                        date_str=date_str,
                        bars_by_symbol=(
                            opening_bars_by_symbol
                        ),
                        source="LIVE_RECONCILED_OPENING",
                        data_feed=MARKET_DATA_FEED,
                    )

                    print(
                        "Reconciled opening minute bars "
                        "written to new trading workbook."
                    )

                except Exception as error:
                    print(
                        "WARNING: New trading workbook "
                        "minute history write failed. "
                        "Live processing will continue."
                    )
                    print(
                        f"Minute history error: {error}"
                    )

        processed_bars = {
            symbol: (
                stock.green_minutes
                + stock.red_minutes
            )
            for symbol, stock in getattr(self, "stocks", {}).items()
        }

        if ACTIVE_STRATEGY == FIBONACCI_STRATEGY_NAME:
            print()
            print(
                "Opening tracking completed. "
                "Starting Fibonacci monitoring..."
            )

            self.run_fibonacci_monitor(
                date_str=date_str,
                write_sheets=write_sheets,
                publish_dashboard=publish_dashboard,
            )
            return

        print()
        print("Calculating preserved manipulation results...")

        try:
            if write_sheets:
                self.run_strategy_and_write(
                    date_str=date_str,
                )
            else:
                self.calculate_strategy(
                    date_str=date_str,
                )

            print(
                "Live strategy calculation completed."
            )
        except Exception as error:
            print(
                "Live strategy calculation failed. "
                "Dashboard will preserve data warnings."
            )
            print(f"Strategy error: {error}")

        if write_sheets:
            try:
                self.write_new_manipulation_results(
                    date_str=date_str,
                )
                print(
                    "Manipulation results written to "
                    "new trading workbook."
                )

                self.write_trade_previews_dashboard(
                    date_str=date_str,
                )

                print(
                    "Trade Previews dashboard updated."
                )
            except Exception as error:
                print(
                    "WARNING: New trading workbook "
                    "Manipulation write failed. "
                    "Legacy results remain preserved."
                )
                print(
                    f"New workbook error: {error}"
                )

        if publish_dashboard:
            self._publish_dashboard_session(
                date_str=date_str,
                source="LIVE_MANIPULATION",
                processed_bars=processed_bars,
            )
        else:
            print(
                "DRY-RUN MODE: Cloudflare dashboard "
                "upload was skipped."
            )

        print()
        print(
            "Manipulation opening strategy completed. "
            "Starting independent Quick Flip monitoring..."
        )

        try:
            self.run_quick_flip_monitor(
                date_str=date_str,
                data_feed=MARKET_DATA_FEED,
                stream_factory=AlpacaStockStream,
                preview_service_factory=(
                    QuickFlipWebullPreviewService
                ),
                write_sheets=write_sheets,
            )
        except Exception as error:
            print(
                "Quick Flip live monitoring failed. "
                "Manipulation results remain preserved."
            )
            print(
                f"Quick Flip error: {error}"
            )


    def run_quick_flip_monitor(
            self,
            date_str: str,
            now_fn=None,
            sleep_fn=None,
            data_feed: str = MARKET_DATA_FEED,
            stream_factory=None,
            preview_service_factory=None,
            write_sheets: bool = False,
    ) -> None:
        """
        Monitor Quick Flip from 09:45 through 11:00 ET.

        The opening 15-minute candle and Wilder ATR14 are
        fetched once because they remain fixed for the session.

        Intraday one-minute bars are fetched incrementally and
        accumulated locally. QuickFlipMonitor then aggregates
        only complete 5-minute candles.

        This method:
        - does not alter Manipulation Stock.signal fields;
        - does not calculate a stop loss;
        - writes only to the separate trading workbook when
          write_sheets=True;
        - may create preview-only Webull requests;
        - cannot submit a broker order.
        """
        eastern = ZoneInfo("America/New_York")
        utc = ZoneInfo("UTC")

        # Native-timeframe live mode:
        # Quick Flip uses Alpaca native 5Min REST bars.
        # Do not mix the existing 1Min WebSocket stream
        # with native 5Min strategy candles.
        stream_factory = None

        now_fn = now_fn or (
            lambda: datetime.now(eastern)
        )
        sleep_fn = sleep_fn or time_module.sleep

        trading_date = datetime.strptime(
            date_str,
            "%Y-%m-%d",
        ).date()

        monitor_start = self._session_clock(
            trading_date,
            QUICK_FLIP_MONITOR_START,
            eastern,
        )

        monitor_cutoff = self._session_clock(
            trading_date,
            QUICK_FLIP_MONITOR_CUTOFF,
            eastern,
        )

        print()
        print("===================================")
        print(" Quick Flip Live Monitor")
        print("===================================")
        print(f"Trading date: {date_str}")
        print(
            "Monitoring window:",
            QUICK_FLIP_MONITOR_START,
            "to",
            QUICK_FLIP_MONITOR_CUTOFF,
            "New York time",
        )
        print(
            "LONG ONLY · NO AUTOMATIC STOP LOSS"
        )
        print(
            "SIGNAL MONITORING ONLY · "
            "NO BROKER ORDER SUBMISSION"
        )

        now = now_fn()

        if now.tzinfo is None:
            now = now.replace(
                tzinfo=eastern,
            )
        else:
            now = now.astimezone(
                eastern
            )

        if now < monitor_start:
            wait_seconds = (
                monitor_start - now
            ).total_seconds()

            print(
                "Waiting for Quick Flip monitoring "
                f"to begin at {QUICK_FLIP_MONITOR_START} ET..."
            )

            sleep_fn(wait_seconds)

            now = now_fn()

            if now.tzinfo is None:
                now = now.replace(
                    tzinfo=eastern,
                )
            else:
                now = now.astimezone(
                    eastern
                )

        if now >= monitor_cutoff:
            print(
                "Quick Flip monitoring cutoff has "
                "already passed."
            )
            return

        print(
            "Loading Quick Flip opening ranges "
            "and ATR14 values..."
        )

        opening_bars = (
            self.alpaca.get_opening_15min_bars(
                symbols_csv=self.symbols_csv,
                date_str=date_str,
                feed=data_feed,
            )
        )

        atrs = (
            self.alpaca.get_previous_day_ranges_all(
                symbols_csv=self.symbols_csv,
                date_str=date_str,
                feed=data_feed,
            )
        )

        intraday_bars = {
            symbol: []
            for symbol in self.stocks
        }

        stream = None
        stream_stop_event = None
        stream_thread = None
        stream_error = {
            "value": None,
        }

        if stream_factory is not None:
            try:
                stream = stream_factory(
                    symbols=list(
                        self.stocks
                    ),
                    feed=data_feed,
                )

                stream_stop_event = Event()

                stream_stop_time = (
                    monitor_cutoff
                    .astimezone(utc)
                    .replace(tzinfo=None)
                )

                def collect_quick_flip_stream():
                    try:
                        stream.collect_until(
                            stop_time=(
                                stream_stop_time
                            ),
                            stop_event=(
                                stream_stop_event
                            ),
                        )
                    except Exception as error:
                        stream_error[
                            "value"
                        ] = error

                stream_thread = Thread(
                    target=(
                        collect_quick_flip_stream
                    ),
                    name=(
                        "quick-flip-alpaca-stream"
                    ),
                    daemon=True,
                )

                print(
                    "Starting Quick Flip "
                    f"{data_feed.upper()} "
                    "WebSocket collector..."
                )

                stream_thread.start()

            except Exception as error:
                print(
                    "WARNING: Quick Flip WebSocket "
                    f"could not start: {error}. "
                    "REST reconciliation will "
                    "continue."
                )

                stream = None
                stream_stop_event = None
                stream_thread = None

        def merge_stream_snapshot() -> None:
            """
            Merge the latest WebSocket representation first.

            REST reconciliation is deliberately applied after
            this function so REST remains authoritative when
            both sources contain the same completed minute.
            """
            if stream is None:
                return

            try:
                snapshot = stream.snapshot()
            except Exception as error:
                print(
                    "WARNING: Quick Flip WebSocket "
                    f"snapshot failed: {error}. "
                    "REST reconciliation will "
                    "continue."
                )
                return

            for symbol in self.stocks:
                intraday_bars[
                    symbol
                ] = reconcile_minute_bars(
                    intraday_bars[
                        symbol
                    ],
                    snapshot.get(
                        symbol,
                        [],
                    ),
                )

        fetch_start = monitor_start
        last_signature = None

        # A confirmed setup may remain INVEST across many
        # one-minute monitoring cycles. Remember exactly which
        # setups have already generated a Webull preview so the
        # same signal cannot be previewed repeatedly.
        previewed_signal_keys = set()

        self.quick_flip_webull_previews = []

        preview_service = (
            preview_service_factory()
            if preview_service_factory is not None
            else None
        )

        def quick_flip_signal_key(
                symbol,
                signal,
        ):
            return (
                symbol,
                str(signal.pattern),
                round(
                    float(signal.entry_price),
                    6,
                ),
                str(
                    getattr(
                        signal,
                        "reversal_time",
                        None,
                    )
                ),
                str(
                    getattr(
                        signal,
                        "confirmation_time",
                        None,
                    )
                ),
            )

        def notify_quick_flip_preview(
                preview,
        ) -> None:
            """
            Show a macOS desktop notification for a newly
            created Quick Flip Webull preview.

            Notification failure never interrupts trading
            strategy monitoring.
            """
            if preview.get("status") != "PREVIEW READY":
                return

            symbol = str(
                preview.get("symbol", "")
            )

            quantity = int(
                preview.get("quantity", 0)
            )

            entry = float(
                preview.get("limitBuy", 0)
            )

            tp1 = float(
                preview.get("takeProfit1", 0)
            )

            tp2 = float(
                preview.get("takeProfit2", 0)
            )

            title = (
                "Quick Flip Webull Preview Ready"
            )

            message = (
                f"{symbol} · {quantity} shares · "
                f"Entry ${entry:.4f} · "
                f"TP1 ${tp1:.4f} · "
                f"TP2 ${tp2:.4f}"
            )

            # Escape values for AppleScript strings.
            safe_title = (
                title
                .replace("\\", "\\\\")
                .replace('"', '\\"')
            )

            safe_message = (
                message
                .replace("\\", "\\\\")
                .replace('"', '\\"')
            )

            script = (
                'display notification '
                f'"{safe_message}" '
                f'with title "{safe_title}"'
            )

            try:
                subprocess.run(
                    [
                        "osascript",
                        "-e",
                        script,
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
            except Exception as error:
                print(
                    "WARNING: Quick Flip macOS "
                    "notification failed: "
                    f"{error}"
                )

        def prepare_new_quick_flip_previews():
            if preview_service is None:
                return []

            new_results = {}
            new_keys = {}

            for symbol, result in (
                self.quick_flip_results.items()
            ):
                if result is None:
                    continue

                signal = getattr(
                    result,
                    "signal",
                    None,
                )

                if (
                    signal is None
                    or signal.signal != "INVEST"
                ):
                    continue

                signal_key = (
                    quick_flip_signal_key(
                        symbol,
                        signal,
                    )
                )

                if (
                    signal_key
                    in previewed_signal_keys
                ):
                    continue

                new_results[symbol] = result
                new_keys[symbol] = signal_key

            if not new_results:
                return []

            try:
                previews = (
                    preview_service
                    .prepare_previews(
                        new_results
                    )
                )
            except Exception as error:
                print(
                    "WARNING: Quick Flip Webull "
                    "preview preparation failed: "
                    f"{error}. Monitoring will "
                    "continue."
                )
                return []

            for preview in previews:
                symbol = preview.get(
                    "symbol"
                )

                # Mark the signal as handled once the preview
                # service has returned a result, whether READY
                # or FAILED. This prevents a failing Webull/API
                # condition from hammering the endpoint every
                # minute for the same setup.
                if symbol in new_keys:
                    previewed_signal_keys.add(
                        new_keys[symbol]
                    )

                self.quick_flip_webull_previews.append(
                    preview
                )

                if (
                    preview.get("status")
                    == "PREVIEW READY"
                ):
                    print(
                        f"{symbol}: QUICK FLIP "
                        "WEBULL PREVIEW READY · "
                        f"{preview['quantity']} shares · "
                        f"entry "
                        f"${preview['limitBuy']:.4f} · "
                        f"TP1 "
                        f"${preview['takeProfit1']:.4f} · "
                        f"TP2 "
                        f"${preview['takeProfit2']:.4f} · "
                        "NO AUTOMATIC STOP · "
                        "NOT SUBMITTED"
                    )

                    notify_quick_flip_preview(
                        preview
                    )
                else:
                    print(
                        f"{symbol}: QUICK FLIP "
                        "WEBULL PREVIEW FAILED · "
                        f"{preview.get('error', 'Unknown error')}"
                    )

            return previews

        def evaluate_current_state(
                *,
                evaluation_end: datetime,
                cutoff_reached: bool,
        ) -> None:
            self.quick_flip_results = {}
            self.quick_flip_status = {}

            for symbol in self.stocks:
                opening_bar = (
                    opening_bars.get(symbol)
                )

                atr_14 = atrs.get(symbol)

                if opening_bar is None:
                    self.quick_flip_results[
                        symbol
                    ] = None

                    self.quick_flip_status[
                        symbol
                    ] = "MISSING_OPENING_BAR"

                    continue

                if atr_14 is None:
                    self.quick_flip_results[
                        symbol
                    ] = None

                    self.quick_flip_status[
                        symbol
                    ] = "MISSING_ATR14"

                    continue

                try:
                    evaluation_end_utc = (
                        evaluation_end.astimezone(utc)
                    )

                    native_candles = []

                    for bar in intraday_bars[symbol]:
                        candle = (
                            self._quick_flip_candle_from_bar(
                                bar
                            )
                        )

                        # Alpaca timestamps native 5Min bars
                        # at the start of their interval.
                        # Evaluate only after all five minutes
                        # have completed.
                        if (
                            candle.timestamp
                            + timedelta(minutes=5)
                            <= evaluation_end_utc
                        ):
                            native_candles.append(
                                candle
                            )

                    result = (
                        self.quick_flip_monitor
                        .evaluate_five_minute_candles(
                            symbol=symbol,
                            opening_bar=(
                                self
                                ._quick_flip_candle_from_bar(
                                    opening_bar
                                )
                            ),
                            atr_14=float(
                                atr_14
                            ),
                            candles=native_candles,
                            cutoff_reached=(
                                cutoff_reached
                            ),
                        )
                    )

                    self.quick_flip_results[
                        symbol
                    ] = result

                    self.quick_flip_status[
                        symbol
                    ] = result.status

                except Exception as error:
                    self.quick_flip_results[
                        symbol
                    ] = None

                    self.quick_flip_status[
                        symbol
                    ] = "EVALUATION_FAILED"

                    print(
                        f"{symbol}: Quick Flip "
                        f"evaluation failed: {error}"
                    )

        while True:
            now = now_fn()

            if now.tzinfo is None:
                now = now.replace(
                    tzinfo=eastern,
                )
            else:
                now = now.astimezone(
                    eastern
                )

            if now >= monitor_cutoff:
                break

            evaluation_end = now.replace(
                second=0,
                microsecond=0,
            )

            if evaluation_end <= monitor_start:
                sleep_fn(
                    QUICK_FLIP_MONITOR_INTERVAL_SECONDS
                )
                continue

            # Fast source first.
            merge_stream_snapshot()

            if evaluation_end > fetch_start:
                start_utc = (
                    fetch_start.astimezone(
                        utc
                    )
                )

                end_utc = (
                    evaluation_end.astimezone(
                        utc
                    )
                )

                rest_fetch_succeeded = False

                try:
                    fetched = (
                        self.alpaca
                        .get_historical_5min_bars(
                            symbols_csv=self.symbols_csv,
                            start_iso=start_utc.strftime(
                                "%Y-%m-%dT%H:%M:%SZ"
                            ),
                            end_iso=end_utc.strftime(
                                "%Y-%m-%dT%H:%M:%SZ"
                            ),
                            feed=data_feed,
                        )
                    )

                    rest_fetch_succeeded = True

                except Exception as error:
                    print(
                        "WARNING: Quick Flip market-data "
                        f"fetch failed: {error}. "
                        "WebSocket data will be used "
                        "when available and REST will "
                        "retry."
                    )

                    fetched = {}

                # Authoritative native 5Min reconciliation.
                for symbol in self.stocks:
                    intraday_bars[
                        symbol
                    ] = reconcile_minute_bars(
                        intraday_bars[
                            symbol
                        ],
                        fetched.get(
                            symbol,
                            [],
                        ),
                    )

                if rest_fetch_succeeded:
                    fetch_start = evaluation_end

            evaluate_current_state(
                evaluation_end=evaluation_end,
                cutoff_reached=False,
            )

            prepare_new_quick_flip_previews()

            signature = tuple(
                sorted(
                    (
                        symbol,
                        result.status,
                        (
                            result.signal.pattern
                            if (
                                result is not None
                                and result.signal
                                is not None
                            )
                            else None
                        ),
                        (
                            result.signal.entry_price
                            if (
                                result is not None
                                and result.signal
                                is not None
                            )
                            else None
                        ),
                    )
                    for symbol, result
                    in self.quick_flip_results.items()
                    if result is not None
                )
            )

            if signature != last_signature:
                print()
                print(
                    "Quick Flip state changed:"
                )

                for symbol in sorted(
                    self.quick_flip_status
                ):
                    status = (
                        self.quick_flip_status[
                            symbol
                        ]
                    )

                    result = (
                        self.quick_flip_results.get(
                            symbol
                        )
                    )

                    if (
                        result is not None
                        and result.signal is not None
                        and result.signal.signal
                        == "INVEST"
                    ):
                        signal = result.signal

                        print(
                            f"{symbol}: INVEST · "
                            f"{signal.pattern} · "
                            f"Entry ${signal.entry_price:.4f} · "
                            f"TP1 ${signal.take_profit_1:.4f} · "
                            f"TP2 ${signal.take_profit_2:.4f}"
                        )
                    elif status not in {
                        "WATCHING",
                    }:
                        print(
                            f"{symbol}: {status}"
                        )

                if write_sheets:
                    try:
                        self.write_new_quick_flip_results(
                            date_str=date_str,
                        )

                        print(
                            "Quick Flip state written to "
                            "new trading workbook."
                        )

                    except Exception as error:
                        print(
                            "WARNING: New trading workbook "
                            "Quick Flip write failed. "
                            "Monitoring will continue."
                        )
                        print(
                            f"New workbook error: {error}"
                        )

                last_signature = signature

            sleep_fn(
                QUICK_FLIP_MONITOR_INTERVAL_SECONDS
            )

        # --------------------------------------------
        # Stop the WebSocket collector at the cutoff.
        # --------------------------------------------
        if stream_stop_event is not None:
            stream_stop_event.set()

        if stream_thread is not None:
            stream_thread.join(
                timeout=2
            )

        if stream_error["value"] is not None:
            print(
                "WARNING: Quick Flip WebSocket "
                f"collector stopped with error: "
                f"{stream_error['value']}. "
                "Final native 5Min REST fetch will "
                "continue."
            )

        # Capture the final stream representation before
        # applying the authoritative REST reconciliation.
        merge_stream_snapshot()

        # --------------------------------------------
        # Final 11:00 evaluation.
        # --------------------------------------------
        if fetch_start < monitor_cutoff:
            try:
                final_fetch = (
                    self.alpaca
                    .get_historical_5min_bars(
                        symbols_csv=self.symbols_csv,
                        start_iso=(
                            fetch_start
                            .astimezone(utc)
                            .strftime(
                                "%Y-%m-%dT%H:%M:%SZ"
                            )
                        ),
                        end_iso=(
                            monitor_cutoff
                            .astimezone(utc)
                            .strftime(
                                "%Y-%m-%dT%H:%M:%SZ"
                            )
                        ),
                        feed=data_feed,
                    )
                )

                for symbol in self.stocks:
                    intraday_bars[
                        symbol
                    ] = reconcile_minute_bars(
                        intraday_bars[
                            symbol
                        ],
                        final_fetch.get(
                            symbol,
                            [],
                        ),
                    )

            except Exception as error:
                print(
                    "WARNING: Final Quick Flip "
                    f"market-data fetch failed: {error}"
                )

        evaluate_current_state(
            evaluation_end=monitor_cutoff,
            cutoff_reached=True,
        )

        prepare_new_quick_flip_previews()

        if write_sheets:
            try:
                self.write_new_quick_flip_results(
                    date_str=date_str,
                )

                print(
                    "Final Quick Flip state written to "
                    "new trading workbook."
                )

            except Exception as error:
                print(
                    "WARNING: Final new trading workbook "
                    "Quick Flip write failed."
                )
                print(
                    f"New workbook error: {error}"
                )

            try:
                combined_bars_by_symbol = {}

                for symbol, stock in getattr(
                    self,
                    "stocks",
                    {},
                ).items():
                    combined_bars_by_symbol[
                        symbol
                    ] = reconcile_minute_bars(
                        list(
                            getattr(
                                stock,
                                "minute_bars",
                                [],
                            )
                        ),
                        intraday_bars.get(
                            symbol,
                            [],
                        ),
                    )

                if combined_bars_by_symbol:
                    self.write_new_minute_bars_history(
                        date_str=date_str,
                        bars_by_symbol=(
                            combined_bars_by_symbol
                        ),
                        source="LIVE_RECONCILED_FULL",
                        data_feed=data_feed,
                    )

                    print(
                        "Final reconciled minute history "
                        "written to new trading workbook."
                    )

            except Exception as error:
                print(
                    "WARNING: Final new trading workbook "
                    "minute history write failed."
                )
                print(
                    f"Minute history error: {error}"
                )

        quick_flip_invest = [
            symbol
            for symbol, result
            in self.quick_flip_results.items()
            if (
                result is not None
                and result.signal is not None
                and result.signal.signal
                == "INVEST"
            )
        ]

        print()
        print(
            "Quick Flip monitoring completed."
        )

        print(
            "Quick Flip INVEST signals:",
            (
                ", ".join(
                    quick_flip_invest
                )
                if quick_flip_invest
                else "None"
            ),
        )

        print(
            "No Quick Flip stop-loss orders "
            "were created."
        )

        print(
            "No broker orders were submitted."
        )


    def run_live_recovery(
            self,
            date_str: str,
            write_sheets: bool = True,
            publish_dashboard: bool = True,
    ) -> None:
        """
        Recover a same-day Fibonacci monitoring session after the
        opening tracker window has ended.

        The normal live-mode time guards remain unchanged. Recovery
        backfills 09:30-09:44 from the configured market-data feed,
        keeps only symbols with complete opening data, and resumes
        paper/preview Fibonacci monitoring.
        """
        eastern = ZoneInfo("America/New_York")
        utc = ZoneInfo("UTC")

        try:
            trading_date = datetime.strptime(
                date_str,
                "%Y-%m-%d",
            ).date()
        except ValueError as error:
            raise ValueError(
                "Recovery date must use YYYY-MM-DD format."
            ) from error

        today_eastern = datetime.now(eastern).date()

        if trading_date != today_eastern:
            raise ValueError(
                "Live recovery is only available for today's "
                "New York trading date."
            )

        if trading_date.weekday() >= 5:
            raise ValueError(
                "Live recovery requires a weekday trading date."
            )

        def parse_monitor_time(value):
            if isinstance(value, time):
                return value

            if isinstance(value, str):
                for format_string in ("%H:%M", "%H:%M:%S"):
                    try:
                        return datetime.strptime(
                            value,
                            format_string,
                        ).time()
                    except ValueError:
                        continue

            raise ValueError(
                f"Invalid Fibonacci monitor time: {value!r}"
            )

        monitor_start = datetime.combine(
            trading_date,
            parse_monitor_time(
                FIBONACCI_MONITOR_START
            ),
            tzinfo=eastern,
        )

        monitor_cutoff = datetime.combine(
            trading_date,
            parse_monitor_time(
                FIBONACCI_MONITOR_CUTOFF
            ),
            tzinfo=eastern,
        )

        now_eastern = datetime.now(eastern)

        if now_eastern < monitor_start:
            raise RuntimeError(
                "Live recovery cannot start before the Fibonacci "
                "monitoring window."
            )

        if now_eastern >= monitor_cutoff:
            raise RuntimeError(
                "Live recovery cannot start after the Fibonacci "
                "monitoring cutoff. Use fibonacci-paper instead."
            )

        window_start = datetime.combine(
            trading_date,
            time(hour=9, minute=30),
            tzinfo=eastern,
        ).astimezone(utc)

        window_end = datetime.combine(
            trading_date,
            time(hour=9, minute=44, second=59),
            tzinfo=eastern,
        ).astimezone(utc)

        print()
        print("===================================")
        print(" Fibonacci Live Recovery")
        print("===================================")
        print(f"Trading date: {date_str}")
        print(
            f"Market-data feed: {MARKET_DATA_FEED.upper()}"
        )
        print(
            "PAPER/PREVIEW ONLY — NOT SUBMITTED"
        )
        print(
            "Backfilling the completed 09:30-09:44 "
            "opening window..."
        )

        selected_symbols = self.refresh_symbols_for_date(
            date_str=date_str,
            data_feed=MARKET_DATA_FEED,
        )

        self.initialise_sheets(
            write_sheets=write_sheets,
        )

        if write_sheets and self.scanner_statistics is not None:
            try:
                self.sheets.write_scanner_dashboard(
                    date_str=date_str,
                    statistics=self.scanner_statistics,
                    selected_symbols=selected_symbols,
                    scanner=self.scanner,
                )
            except Exception as error:
                print(
                    "Scanner dashboard update failed. "
                    "Recovery will continue."
                )
                print(f"Dashboard error: {error}")

        bars_by_symbol = (
            self.alpaca.get_historical_1min_bars(
                symbols_csv=self.symbols_csv,
                start_iso=window_start.strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                ),
                end_iso=window_end.strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                ),
                feed=MARKET_DATA_FEED,
            )
        )

        atrs = self.alpaca.get_previous_day_ranges_all(
            symbols_csv=self.symbols_csv,
            date_str=date_str,
            feed=MARKET_DATA_FEED,
        )

        replay = HistoricalReplay(
            stocks=self.stocks,
            strategy=self.strategy,
            speed=0.0,
        )

        summary = replay.run(
            date_str=date_str,
            window_start=window_start,
            bars_by_symbol=bars_by_symbol,
            atrs=atrs,
            data_feed=MARKET_DATA_FEED,
        )

        complete_symbols = [
            symbol
            for symbol, stock in self.stocks.items()
            if (
                summary.processed_bars.get(symbol, 0) == 15
                and stock.opening_bar is not None
            )
        ]

        incomplete_symbols = [
            symbol
            for symbol in self.stocks
            if symbol not in complete_symbols
        ]

        if incomplete_symbols:
            print(
                "Recovery excluded symbols with incomplete "
                "opening data: "
                + ", ".join(incomplete_symbols)
            )

        if not complete_symbols:
            raise RuntimeError(
                "Recovery could not construct one complete "
                "15-minute opening range."
            )

        self.stocks = {
            symbol: self.stocks[symbol]
            for symbol in complete_symbols
        }
        self.symbols_csv = ",".join(complete_symbols)

        print(
            "Recovered complete opening ranges: "
            + ", ".join(complete_symbols)
        )
        print()
        print("Starting Fibonacci monitoring recovery...")

        self.run_fibonacci_monitor(
            date_str=date_str,
            write_sheets=write_sheets,
            publish_dashboard=publish_dashboard,
        )

    def _dashboard_webull_approvals(
            self,
    ) -> list[dict[str, object]]:
        """
        Return redacted approval records for dashboard display.

        Approval-store failures produce an empty list and never
        interrupt the trading session.
        """
        queue = getattr(
            self,
            "webull_approval_queue",
            None,
        )

        if queue is None:
            return []

        try:
            return queue.list_public_records()
        except Exception as error:
            print(
                "Webull approval status unavailable. "
                "Publishing no approval records. "
                f"Reason: {error}"
            )
            return []

    def _dashboard_paper_portfolio(
            self,
            *,
            date_str: str,
            source: str,
    ) -> dict[str, object] | None:
        """
        Return the latest LOCAL PAPER portfolio snapshot for
        live Fibonacci dashboard sessions.

        This is reconstructed simulation state only and never
        represents broker balances or broker-submitted positions.
        """
        if source.upper() not in {
            "LIVE_FIBONACCI",
            "LIVE_FIBONACCI_FINAL",
        }:
            return None

        try:
            tracker = getattr(
                self,
                "webull_paper_lifecycle_tracker",
                None,
            )

            portfolio_store = (
                tracker.store
                if tracker is not None
                else None
            )

            portfolio = getattr(
                self,
                "_webull_paper_portfolio_snapshot",
                None,
            )

            if portfolio is None:
                portfolio = (
                    load_webull_paper_portfolio(
                        store=portfolio_store,
                    )
                )

            try:
                risk_status = (
                    load_webull_paper_risk_status(
                        date_str=date_str,
                        store=portfolio_store,
                    )
                )
            except Exception as error:
                risk_status = None
                print(
                    "LOCAL PAPER dashboard risk status "
                    "unavailable. "
                    f"Reason: {error}"
                )
        except Exception as error:
            print(
                "LOCAL PAPER dashboard portfolio "
                "unavailable. "
                f"Reason: {error}"
            )
            return None

        return {
            "startingCash": portfolio.starting_cash,
            "cash": portfolio.cash,
            "buyingPower": portfolio.buying_power,
            "openCostBasis": (
                portfolio.open_cost_basis
            ),
            "marketValue": portfolio.market_value,
            "realizedPnl": portfolio.realized_pnl,
            "unrealizedPnl": portfolio.unrealized_pnl,
            "totalPnl": portfolio.total_pnl,
            "equity": portfolio.equity,
            "openPositionCount": (
                portfolio.open_position_count
            ),
            "closedPositionCount": (
                portfolio.closed_position_count
            ),
            "pendingOrderCount": (
                portfolio.pending_order_count
            ),
            "noEntryCount": portfolio.no_entry_count,
            "overdrawn": portfolio.overdrawn,
            "openPositions": [
                {
                    "paperOrderId": (
                        position.paper_order_id
                    ),
                    "symbol": position.symbol,
                    "quantity": position.quantity,
                    "fillPrice": position.fill_price,
                    "costBasis": position.cost_basis,
                    "markPrice": position.mark_price,
                    "markStatus": position.mark_status,
                    "marketValue": (
                        position.market_value
                    ),
                    "unrealizedPnl": (
                        position.unrealized_pnl
                    ),
                    "unrealizedReturnPct": (
                        position.unrealized_return_pct
                    ),
                    "filledAt": (
                        position.filled_at
                        .isoformat()
                        .replace("+00:00", "Z")
                    ),
                    "targetPrice": (
                        position.target_price
                    ),
                    "stopPrice": position.stop_price,
                }
                for position in portfolio.open_positions
            ],
            "closedPositions": [
                {
                    "paperOrderId": (
                        position.paper_order_id
                    ),
                    "symbol": position.symbol,
                    "quantity": position.quantity,
                    "fillPrice": position.fill_price,
                    "exitPrice": position.exit_price,
                    "realizedPnl": (
                        position.realized_pnl
                    ),
                    "returnPct": position.return_pct,
                    "exitReason": position.exit_reason,
                    "filledAt": (
                        position.filled_at
                        .isoformat()
                        .replace("+00:00", "Z")
                    ),
                    "closedAt": (
                        position.closed_at
                        .isoformat()
                        .replace("+00:00", "Z")
                    ),
                }
                for position in portfolio.closed_positions
            ],
            "risk": (
                None
                if risk_status is None
                else {
                    "tradingAllowed": (
                        risk_status.trading_allowed
                    ),
                    "reason": risk_status.reason,
                    "availableForNewOrders": (
                        risk_status.available_for_new_orders
                    ),
                    "pendingReservedCash": (
                        risk_status.pending_reserved_cash
                    ),
                    "dailyRealizedPnl": (
                        risk_status.daily_realized_pnl
                    ),
                    "maxDailyLoss": (
                        risk_status.max_daily_loss
                    ),
                    "remainingDailyLoss": (
                        risk_status.remaining_daily_loss
                    ),
                    "simulationOnly": True,
                    "brokerSubmitted": False,
                }
            ),
            "simulationOnly": True,
            "brokerSubmitted": False,
        }

    def _dashboard_paper_performance(
            self,
            *,
            date_str: str,
            source: str,
    ) -> dict[str, object] | None:
        """
        Return completed LOCAL PAPER performance for the final
        Fibonacci dashboard session only.

        Ledger failures never interrupt trading or dashboard
        publishing.
        """
        if source.upper() != "LIVE_FIBONACCI_FINAL":
            return None

        try:
            report = load_webull_paper_daily_performance(
                date_str=date_str,
            )
        except Exception as error:
            print(
                "LOCAL PAPER dashboard performance "
                "unavailable. "
                f"Reason: {error}"
            )
            return None

        return {
            "date": report.date,
            "ordersApproved": report.orders_approved,
            "tradesEntered": report.trades_entered,
            "openTrades": report.open_trades,
            "closedTrades": report.closed_trades,
            "noEntry": report.no_entry,
            "targetExits": report.target_exits,
            "stopExits": report.stop_exits,
            "timeExits": report.time_exits,
            "profitableTrades": (
                report.profitable_trades
            ),
            "losingTrades": report.losing_trades,
            "breakevenTrades": (
                report.breakeven_trades
            ),
            "winRatePct": report.win_rate_pct,
            "realizedPnl": report.realized_pnl,
            "averagePnlPerTrade": (
                report.average_pnl_per_trade
            ),
            "averageReturnPct": (
                report.average_return_pct
            ),
            "averageWinner": report.average_winner,
            "averageLoser": report.average_loser,
            "expectancyPerTrade": (
                report.expectancy_per_trade
            ),
            "averageMfePct": report.average_mfe_pct,
            "averageMaePct": report.average_mae_pct,
            "bestTrade": {
                "symbol": report.best_trade_symbol,
                "pnl": report.best_trade_pnl,
            },
            "worstTrade": {
                "symbol": report.worst_trade_symbol,
                "pnl": report.worst_trade_pnl,
            },
            "simulationOnly": True,
            "brokerSubmitted": False,
        }

    def _dashboard_paper_analytics(
            self,
            *,
            source: str,
    ) -> dict[str, object] | None:
        """
        Return cumulative LOCAL PAPER analytics for the final
        live Fibonacci dashboard session only.

        Ledger failures are nonfatal and never affect strategy or
        order-processing behavior.
        """
        if source.upper() != "LIVE_FIBONACCI_FINAL":
            return None

        try:
            report = load_webull_paper_analytics()
        except Exception as error:
            print(
                "LOCAL PAPER dashboard analytics "
                "unavailable. "
                f"Reason: {error}"
            )
            return None

        def groups(values):
            return [
                {
                    "key": group.key,
                    "approvedOrders": (
                        group.approved_orders
                    ),
                    "enteredTrades": (
                        group.entered_trades
                    ),
                    "closedTrades": (
                        group.closed_trades
                    ),
                    "noEntry": group.no_entry,
                    "wins": group.wins,
                    "losses": group.losses,
                    "breakeven": group.breakeven,
                    "targetExits": (
                        group.target_exits
                    ),
                    "stopExits": group.stop_exits,
                    "timeExits": group.time_exits,
                    "winRatePct": (
                        group.win_rate_pct
                    ),
                    "realizedPnl": (
                        group.realized_pnl
                    ),
                    "averagePnlPerTrade": (
                        group.average_pnl_per_trade
                    ),
                    "averageReturnPct": (
                        group.average_return_pct
                    ),
                    "expectancyPerTrade": (
                        group.expectancy_per_trade
                    ),
                    "averageMfePct": (
                        group.average_mfe_pct
                    ),
                    "averageMaePct": (
                        group.average_mae_pct
                    ),
                    "sampleLabel": (
                        group.sample_label
                    ),
                }
                for group in values
            ]

        return {
            "totalOrders": report.total_orders,
            "enteredTrades": report.entered_trades,
            "closedTrades": report.closed_trades,
            "openTrades": report.open_trades,
            "noEntry": report.no_entry,
            "realizedPnl": report.realized_pnl,
            "winRatePct": report.win_rate_pct,
            "averageReturnPct": (
                report.average_return_pct
            ),
            "expectancyPerTrade": (
                report.expectancy_per_trade
            ),
            "bySymbol": groups(report.by_symbol),
            "byEntryTime": groups(
                report.by_entry_time
            ),
            "byRewardRisk": groups(
                report.by_reward_risk
            ),
            "byImpulseAtr": groups(
                report.by_impulse_atr
            ),
            "byPullbackVolume": groups(
                report.by_pullback_volume
            ),
            "byConfirmationTime": groups(
                report.by_confirmation_time
            ),
            "simulationOnly": True,
            "brokerSubmitted": False,
        }

    def _dashboard_paper_evaluation(
            self,
            *,
            source: str,
    ) -> dict[str, object] | None:
        """
        Return Fibonacci LOCAL PAPER evaluation for the final
        live Fibonacci dashboard session only.

        Evaluation failures are nonfatal and cannot modify strategy
        parameters or order-processing behavior.
        """
        if source.upper() != "LIVE_FIBONACCI_FINAL":
            return None

        try:
            evaluation = (
                load_fibonacci_paper_evaluation()
            )
        except Exception as error:
            print(
                "FIBONACCI PAPER dashboard evaluation "
                "unavailable. "
                f"Reason: {error}"
            )
            return None

        def finding(value):
            if value is None:
                return None

            return {
                "dimension": value.dimension,
                "key": value.key,
                "closedTrades": value.closed_trades,
                "winRatePct": value.win_rate_pct,
                "expectancyPerTrade": (
                    value.expectancy_per_trade
                ),
                "averageReturnPct": (
                    value.average_return_pct
                ),
                "realizedPnl": value.realized_pnl,
                "sampleLabel": value.sample_label,
            }

        return {
            "totalOrders": evaluation.total_orders,
            "closedTrades": evaluation.closed_trades,
            "evidenceStatus": (
                evaluation.evidence_status
            ),
            "evidenceMessage": (
                evaluation.evidence_message
            ),
            "parameterChangesAllowed": (
                evaluation.parameter_changes_allowed
            ),
            "strongestCohort": finding(
                evaluation.strongest_cohort
            ),
            "weakestCohort": finding(
                evaluation.weakest_cohort
            ),
            "simulationOnly": True,
            "brokerSubmitted": False,
        }

    def _publish_dashboard_session(
            self,
            date_str: str,
            source: str,
            processed_bars: dict[str, int],
            data_feed: str = MARKET_DATA_FEED,
    ) -> None:
        try:
            result = self.dashboard.publish(
                date_str=date_str,
                source=source,
                stocks=self.stocks,
                processed_bars=processed_bars,
                data_feed=data_feed,
                symbol_reliability=(
                    self.symbol_reliability
                ),
                run_mode=os.getenv(
                    "TRADING_RUN_MODE",
                    (
                        "REPLAY"
                        if source == "REPLAY"
                        else "MANUAL"
                    ),
                ),
                webull_approvals=(
                    self._dashboard_webull_approvals()
                ),
                paper_performance=(
                    self._dashboard_paper_performance(
                        date_str=date_str,
                        source=source,
                    )
                ),
                paper_portfolio=(
                    self._dashboard_paper_portfolio(
                        date_str=date_str,
                        source=source,
                    )
                ),
                paper_analytics=(
                    self._dashboard_paper_analytics(
                        source=source,
                    )
                ),
                paper_evaluation=(
                    self._dashboard_paper_evaluation(
                        source=source,
                    )
                ),
            )
        except Exception as error:
            print(
                "Dashboard upload failed. "
                "Trading-bot processing is unchanged."
            )
            print(f"Dashboard error: {error}")
            return

        if result is None:
            print(
                "Dashboard upload skipped: "
                "DASHBOARD_INGEST_KEY is not configured."
            )
            return

        print(
            "Dashboard session uploaded: "
            f"{result['status']}."
        )

    def run_replay(
            self,
            date_str: str,
            speed: float = 60.0,
        publish_dashboard: bool = True,
        data_feed: str = MARKET_DATA_FEED,
        slippage_bps: float = 0.0,
        commission_per_share: float = 0.0,
    ) -> ReplaySession:
        data_feed = data_feed.strip().lower()
        if data_feed not in {"iex", "sip"}:
            raise ValueError(
                "Market-data feed must be 'iex' or 'sip'."
            )
        try:
            trading_date = datetime.strptime(
                date_str,
                "%Y-%m-%d",
            ).date()
        except ValueError as error:
            raise ValueError(
                "Replay date must use YYYY-MM-DD format."
            ) from error

        if trading_date.weekday() >= 5:
            raise ValueError(
                "Replay date must be a weekday."
            )

        if speed < 0:
            raise ValueError(
                "Replay speed cannot be negative."
            )

        eastern = ZoneInfo("America/New_York")
        utc = ZoneInfo("UTC")

        window_start = datetime.combine(
            trading_date,
            time(hour=9, minute=30),
            tzinfo=eastern,
        ).astimezone(utc)

        window_end = (
            window_start
            + timedelta(minutes=15)
            - timedelta(seconds=1)
        )

        print()
        print("===================================")
        print(" Historical Trading Replay")
        print("===================================")
        print(f"Trading date: {date_str}")
        print(f"Replay speed: {speed:g}x")
        print(f"Market-data feed: {data_feed.upper()}")
        print(
            "READ-ONLY MODE: Google Sheets, Orders, "
            "and trading are disabled."
        )

        self.refresh_symbols_for_date(
            date_str,
            data_feed=data_feed,
        )

        bars_by_symbol = (
            self.alpaca.get_historical_1min_bars(
                symbols_csv=self.symbols_csv,
                start_iso=window_start.strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                ),
                end_iso=window_end.strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                ),
                feed=data_feed,
            )
        )

        atrs = self.alpaca.get_previous_day_ranges_all(
            symbols_csv=self.symbols_csv,
            date_str=date_str,
            feed=data_feed,
        )

        replay = HistoricalReplay(
            stocks=self.stocks,
            strategy=self.strategy,
            speed=speed,
        )

        summary = replay.run(
            date_str=date_str,
            window_start=window_start,
            bars_by_symbol=bars_by_symbol,
            atrs=atrs,
            data_feed=data_feed,
        )
        summary.atr_diagnostics = getattr(
            self.alpaca,
            "last_atr_diagnostics",
            {},
        )

        outcome_start = datetime.combine(
            trading_date,
            time(hour=9, minute=45),
            tzinfo=eastern,
        ).astimezone(utc)

        outcome_end = datetime.combine(
            trading_date,
            time(hour=16),
            tzinfo=eastern,
        ).astimezone(utc)

        outcome_bars = (
            self.alpaca.get_historical_1min_bars(
                symbols_csv=self.symbols_csv,
                start_iso=outcome_start.strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                ),
                end_iso=outcome_end.strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                ),
                feed=data_feed,
            )
        )

        replay.calculate_outcomes(
            bars_by_symbol=outcome_bars,
            slippage_bps=slippage_bps,
            commission_per_share=commission_per_share,
        )

        print()
        print("===== REPLAY RESULTS =====")

        for symbol, stock in self.stocks.items():
            processed = summary.processed_bars[symbol]

            print()
            print(f"Symbol: {symbol}")
            print(
                f"Bars processed: {processed}/15"
            )
            print(
                f"Green/Red minutes: "
                f"{stock.green_minutes}/"
                f"{stock.red_minutes}"
            )
            print(
                f"New highs/lows: "
                f"{stock.new_highs}/"
                f"{stock.new_lows}"
            )

            if stock.opening_bar is None:
                print("Opening candle: incomplete")
                print("Signal: NO INVEST")
                continue

            print(
                "Opening O/H/L/C: "
                f"{float(stock.opening_bar['o']):.4f} / "
                f"{float(stock.opening_bar['h']):.4f} / "
                f"{float(stock.opening_bar['l']):.4f} / "
                f"{float(stock.opening_bar['c']):.4f}"
            )

            if stock.atr is None:
                print("ATR: unavailable")
            else:
                print(f"ATR: {stock.atr:.4f}")

            print(f"Signal: {stock.signal}")

        print()
        print("Historical replay completed.")
        print(
            "No spreadsheets or orders were created."
        )

        session = ReplaySession(
            date=date_str,
            stocks={
                symbol: stock
                for symbol, stock in self.stocks.items()
            },
            summary=summary,
        )

        if publish_dashboard:
            self._publish_dashboard_session(
                date_str=date_str,
                source="REPLAY",
                processed_bars=summary.processed_bars,
                data_feed=data_feed,
            )

        return session




    def run_fibonacci_paper(
        self,
        date_str: str | None = None,
        output_path: str | Path = (
            "reports/fibonacci-paper/"
            "fibonacci_paper_ledger.csv"
        ),
        data_feed: str = MARKET_DATA_FEED,
        slippage_bps: float = 15.0,
        publish_outputs: bool = False,
        publish_dashboard_only: bool = False,
    ) -> list:
        """
        Evaluate the Fibonacci paper rule for one session.

        By default this mode writes only to its independent
        CSV ledger.

        When publish_outputs is explicitly enabled, it may also
        write only to the dedicated Fibonacci Google Sheets and
        publish the read-only Cloudflare dashboard.

        When publish_dashboard_only is enabled, it publishes a
        historical REPLAY session without writing Google Sheets.

        It never calls Webull, creates previews, or submits orders.
        """
        data_feed = data_feed.strip().lower()

        if data_feed not in {"iex", "sip"}:
            raise ValueError(
                "Market-data feed must be 'iex' or 'sip'."
            )

        if slippage_bps < 0:
            raise ValueError(
                "Slippage cannot be negative."
            )

        eastern = ZoneInfo("America/New_York")
        utc = ZoneInfo("UTC")
        now = datetime.now(eastern)

        if date_str is None:
            trading_date = now.date()
            date_str = trading_date.isoformat()
        else:
            try:
                trading_date = datetime.strptime(
                    date_str,
                    "%Y-%m-%d",
                ).date()
            except ValueError as error:
                raise ValueError(
                    "Paper date must use YYYY-MM-DD."
                ) from error

        if trading_date > now.date():
            raise ValueError(
                "Fibonacci paper mode cannot evaluate "
                "a future date."
            )

        if trading_date.weekday() >= 5:
            print()
            print(
                f"{date_str} is a weekend. "
                "No paper evaluation was performed."
            )
            return []

        session_start_eastern = datetime.combine(
            trading_date,
            time(hour=9, minute=30),
            tzinfo=eastern,
        )

        market_close_eastern = datetime.combine(
            trading_date,
            time(hour=16),
            tzinfo=eastern,
        )

        if trading_date == now.date():
            if now < session_start_eastern:
                print()
                print(
                    "The market has not opened yet. "
                    "No Fibonacci paper evaluation "
                    "was performed."
                )
                return []

            session_end_eastern = min(
                now,
                market_close_eastern,
            )
        else:
            session_end_eastern = market_close_eastern

        print()
        print("===================================")
        print(" Fibonacci Paper Mode")
        print("===================================")
        print(f"Trading date: {date_str}")
        print(f"Market-data feed: {data_feed.upper()}")
        print(
            f"Modeled slippage: "
            f"{slippage_bps:.1f} bps"
        )
        print("PAPER ONLY — NOT SUBMITTED")
        if publish_outputs:
            print(
                "Publishing enabled for Fibonacci Sheets and "
                "the read-only Cloudflare dashboard."
            )
            print(
                "Webull, previews, and production orders "
                "remain disabled."
            )
        elif publish_dashboard_only:
            print(
                "Historical dashboard publishing enabled."
            )
            print(
                "Google Sheets, Webull, previews, and "
                "production orders remain disabled."
            )
        else:
            print(
                "Google Sheets, dashboard, Webull, previews, "
                "and production orders are disabled."
            )

        with redirect_stdout(StringIO()):
            self.refresh_symbols_for_date(
                date_str,
                data_feed=data_feed,
            )

        symbols_csv = self.symbols_csv

        session_start = (
            session_start_eastern
            .astimezone(utc)
        )

        session_end = (
            session_end_eastern
            .astimezone(utc)
        )

        bars_by_symbol = (
            self.alpaca.get_historical_1min_bars(
                symbols_csv=symbols_csv,
                start_iso=session_start.strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                ),
                end_iso=session_end.strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                ),
                feed=data_feed,
            )
        )

        atrs = (
            self.alpaca.get_previous_day_ranges_all(
                symbols_csv=symbols_csv,
                date_str=date_str,
                feed=data_feed,
            )
        )

        observation_type = (
            "FORWARD_PAPER"
            if trading_date == now.date()
            else "HISTORICAL_VALIDATION"
        )

        print(
            f"Observation type: {observation_type}"
        )

        paper_records = []

        for symbol in self.stocks:
            setups = analyse_symbol_day(
                date_str=date_str,
                symbol=symbol,
                data_feed=data_feed,
                bars=bars_by_symbol.get(symbol, []),
                atr=atrs.get(symbol),
                minimum_impulse_atr=0.50,
                slippage_bps=slippage_bps,
                commission_per_share=0.0,
            )

            for setup in setups:
                record = build_fibonacci_paper_record(
                    setup,
                    modeled_slippage_bps=(
                        slippage_bps
                    ),
                    observation_type=(
                        observation_type
                    ),
                )

                if record is not None:
                    paper_records.append(record)

        ledger = FibonacciPaperLedger(output_path)
        ledger_path = ledger.upsert(paper_records)

        print()
        print(
            f"Selected symbols evaluated: "
            f"{len(self.stocks)}"
        )
        print(
            f"Qualifying paper setups: "
            f"{len(paper_records)}"
        )

        if not paper_records:
            print(
                "No setup satisfied every Fibonacci "
                "paper rule."
            )

        for record in paper_records:
            net_return = (
                f"{record.net_return_pct:.4f}%"
                if record.net_return_pct is not None
                else "Pending"
            )

            print()
            print(
                f"{record.symbol} · "
                f"{record.fibonacci_level}"
            )
            print(
                f"Impulse: "
                f"{record.impulse_atr_multiple:.3f} ATR "
                f"over "
                f"{record.impulse_duration_minutes} minutes"
            )
            print(
                f"Pullback volume ratio: "
                f"{record.pullback_volume_ratio:.3f}"
            )
            print(
                f"Entry ${record.entry_price:.4f} · "
                f"Stop ${record.stop_price:.4f} · "
                f"Target ${record.target_price:.4f}"
            )
            print(
                f"Outcome: {record.outcome} · "
                f"Return: {net_return}"
            )
            print("PAPER ONLY — NOT SUBMITTED")

        print()
        print(f"Paper ledger: {ledger_path}")

        if publish_outputs or publish_dashboard_only:
            print()
            print(
                (
                    "Preparing dedicated Fibonacci Sheets and "
                    "dashboard output..."
                    if publish_outputs
                    else "Preparing historical Fibonacci "
                    "dashboard output..."
                )
            )

            processed_bars: dict[str, int] = {}

            for symbol, stock in self.stocks.items():
                symbol_bars = sorted(
                    bars_by_symbol.get(symbol, []),
                    key=lambda bar: str(bar.get("t", "")),
                )

                opening_bars = []

                for bar in symbol_bars:
                    timestamp = datetime.fromisoformat(
                        str(bar["t"]).replace(
                            "Z",
                            "+00:00",
                        )
                    )

                    if timestamp.tzinfo is None:
                        timestamp = timestamp.replace(
                            tzinfo=utc
                        )

                    eastern_timestamp = (
                        timestamp.astimezone(eastern)
                    )

                    bar_time = eastern_timestamp.time()

                    if (
                        time(hour=9, minute=30)
                        <= bar_time
                        < time(hour=9, minute=45)
                    ):
                        opening_bars.append(bar)

                processed_bars[symbol] = len(opening_bars)

                if opening_bars:
                    stock.opening_bar = {
                        "o": float(opening_bars[0]["o"]),
                        "h": max(
                            float(bar["h"])
                            for bar in opening_bars
                        ),
                        "l": min(
                            float(bar["l"])
                            for bar in opening_bars
                        ),
                        "c": float(opening_bars[-1]["c"]),
                        "v": sum(
                            float(bar.get("v", 0) or 0)
                            for bar in opening_bars
                        ),
                    }

                    stock.candle_range = (
                        float(stock.opening_bar["h"])
                        - float(stock.opening_bar["l"])
                    )

                stock.atr = atrs.get(symbol)
                stock.atr_threshold = (
                    float(stock.atr) * 0.25
                    if stock.atr is not None
                    else None
                )

                self.fibonacci_strategy.evaluate(
                    stock=stock,
                    date_str=date_str,
                    bars=symbol_bars,
                    atr=stock.atr,
                    data_feed=data_feed,
                    slippage_bps=slippage_bps,
                )

            records_by_symbol = {}

            for record in paper_records:
                records_by_symbol.setdefault(
                    record.symbol,
                    [],
                ).append(record)

            for symbol, stock in self.stocks.items():
                if stock.signal != "INVEST":
                    stock.outcome = None
                    continue

                symbol_records = records_by_symbol.get(
                    symbol,
                    [],
                )

                if not symbol_records:
                    stock.outcome = None
                    continue

                record = sorted(
                    symbol_records,
                    key=lambda item: (
                        str(
                            getattr(
                                item,
                                "confirmation_time",
                                "",
                            )
                        )
                    ),
                )[0]

                status = str(record.outcome).upper()

                if status not in {
                    "WIN",
                    "LOSS",
                    "NO ENTRY",
                    "STILL OPEN",
                }:
                    stock.outcome = None
                    continue

                outcome = {
                    "status": status,
                    "detail": (
                        "Historical Fibonacci paper outcome. "
                        "PAPER ONLY — NOT SUBMITTED."
                    ),
                }

                confirmation_time = getattr(
                    record,
                    "confirmation_time",
                    None,
                )

                if confirmation_time:
                    outcome["entryTime"] = str(
                        confirmation_time
                    )

                entry_price = getattr(
                    record,
                    "entry_price",
                    None,
                )

                if entry_price is not None:
                    outcome["entryPrice"] = float(
                        entry_price
                    )

                exit_time = getattr(
                    record,
                    "exit_time",
                    None,
                )

                if exit_time:
                    outcome["exitTime"] = str(exit_time)

                exit_price = getattr(
                    record,
                    "exit_price",
                    None,
                )

                if exit_price is not None:
                    outcome["exitPrice"] = float(
                        exit_price
                    )

                net_return_pct = getattr(
                    record,
                    "net_return_pct",
                    None,
                )

                if net_return_pct is not None:
                    outcome["returnPct"] = float(
                        net_return_pct
                    )

                    if entry_price is not None:
                        outcome["pnlPerShare"] = round(
                            float(entry_price)
                            * float(net_return_pct)
                            / 100.0,
                            6,
                        )

                stock.outcome = outcome

            if publish_outputs:
                self.initialise_sheets(
                    write_sheets=True,
                )

                if self.sheets is None:
                    raise RuntimeError(
                        "Google Sheets was not initialised."
                    )

                self.sheets.write_strategy_results(
                    date_str=date_str,
                    stocks=self.stocks,
                    sheet_name="Fibonacci Invest",
                )

                # This directly reconciles the dedicated
                # Fibonacci order sheet. Webull preview
                # generation is deliberately not called.
                self.sheets.write_orders(
                    date_str=date_str,
                    stocks=self.stocks,
                    sheet_name="Fibonacci Orders",
                )

            dashboard_source = (
                "LIVE_FIBONACCI_FINAL"
                if publish_outputs
                else "REPLAY"
            )

            self._publish_dashboard_session(
                date_str=date_str,
                source=dashboard_source,
                processed_bars=processed_bars,
                data_feed=data_feed,
            )

            if publish_outputs:
                print(
                    "Fibonacci Sheets and dashboard published."
                )
            else:
                print(
                    "Historical Fibonacci dashboard session "
                    "published."
                )

            print("PAPER ONLY — NOT SUBMITTED")

        return paper_records

    def run_dashboard_backfill(
            self,
            start_date: str,
            end_date: str,
            data_feed: str = MARKET_DATA_FEED,
            slippage_bps: float = 15.0,
    ) -> None:
        """
        Publish historical Fibonacci sessions to Cloudflare.

        Google Sheets, Webull previews, and all broker-order
        workflows remain disabled.
        """
        try:
            start = datetime.strptime(
                start_date,
                "%Y-%m-%d",
            ).date()
            end = datetime.strptime(
                end_date,
                "%Y-%m-%d",
            ).date()
        except ValueError as error:
            raise ValueError(
                "Backfill dates must use YYYY-MM-DD."
            ) from error

        if end < start:
            raise ValueError(
                "Backfill end date cannot precede "
                "the start date."
            )

        eastern = ZoneInfo("America/New_York")
        today = datetime.now(eastern).date()

        if end >= today:
            raise ValueError(
                "Dashboard backfill is historical only. "
                "The end date must be before today."
            )

        data_feed = data_feed.strip().lower()

        if data_feed not in {"iex", "sip"}:
            raise ValueError(
                "Backfill feed must be 'iex' or 'sip'."
            )

        if slippage_bps < 0:
            raise ValueError(
                "Slippage cannot be negative."
            )

        dates = weekday_dates(start, end)

        if not dates:
            raise ValueError(
                "Backfill range contains no weekdays."
            )

        print()
        print("===================================")
        print(" Fibonacci Dashboard Backfill")
        print("===================================")
        print(
            f"Date range: {start_date} to {end_date}"
        )
        print(f"Market-data feed: {data_feed.upper()}")
        print(
            f"Modeled slippage: "
            f"{slippage_bps:.1f} bps"
        )
        print(
            "Dashboard only — Google Sheets, Webull, "
            "previews, and orders are disabled."
        )
        print("PAPER ONLY — NOT SUBMITTED")

        uploaded = 0
        failed = 0

        for trading_date in dates:
            date_str = trading_date.isoformat()

            print()
            print(f"Backfilling {date_str}...")

            try:
                self.run_fibonacci_paper(
                    date_str=date_str,
                    data_feed=data_feed,
                    slippage_bps=slippage_bps,
                    publish_outputs=False,
                    publish_dashboard_only=True,
                )

                uploaded += 1
                print(f"{date_str}: UPLOADED")

            except Exception as error:
                failed += 1
                print(
                    f"{date_str}: FAILED — {error}"
                )

        print()
        print("===================================")
        print(" Backfill Summary")
        print("===================================")
        print(f"Uploaded: {uploaded}")
        print(f"Failed: {failed}")
        print("No real orders were submitted.")

    def run_fibonacci_retracement_research(
        self,
        start_date: str,
        end_date: str,
        output_directory: str | Path = (
            "reports/fibonacci-retracement"
        ),
        data_feed: str = MARKET_DATA_FEED,
        slippage_bps: float = 0.0,
        commission_per_share: float = 0.0,
        minimum_impulse_atr: float = 1.0,
        multiple_impulses: bool = False,
    ) -> FibonacciRetracementReport:
        """
        Study genuine upward impulses followed by Fibonacci
        pullbacks and bullish confirmation.

        This workflow is strictly read-only. It cannot write
        Google Sheets, publish dashboard sessions, call Webull,
        create previews, or submit orders.
        """
        data_feed = data_feed.strip().lower()

        if data_feed not in {"iex", "sip"}:
            raise ValueError(
                "Market-data feed must be 'iex' or 'sip'."
            )

        if slippage_bps < 0:
            raise ValueError(
                "Slippage cannot be negative."
            )

        if commission_per_share < 0:
            raise ValueError(
                "Commission cannot be negative."
            )

        if minimum_impulse_atr <= 0:
            raise ValueError(
                "Minimum impulse ATR must be positive."
            )

        try:
            start = datetime.strptime(
                start_date,
                "%Y-%m-%d",
            ).date()
            end = datetime.strptime(
                end_date,
                "%Y-%m-%d",
            ).date()
        except ValueError as error:
            raise ValueError(
                "Research dates must use YYYY-MM-DD format."
            ) from error

        dates = weekday_dates(start, end)

        if not dates:
            raise ValueError(
                "Research range contains no weekdays."
            )

        report = FibonacciRetracementReport(
            start_date=start_date,
            end_date=end_date,
            data_feed=data_feed,
            slippage_bps=slippage_bps,
            commission_per_share=commission_per_share,
        )

        eastern = ZoneInfo("America/New_York")
        utc = ZoneInfo("UTC")

        print()
        print("===================================")
        print(" Fibonacci Retracement Research")
        print("===================================")
        print(
            f"Date range: {start_date} to {end_date}"
        )
        print(f"Market-data feed: {data_feed.upper()}")
        print(
            "Minimum impulse: "
            f"{minimum_impulse_atr:.2f} ATR"
        )
        print(
            "Impulse selection:",
            (
                "MULTIPLE NON-OVERLAPPING IMPULSES"
                if multiple_impulses
                else "FIRST QUALIFYING IMPULSE"
            ),
        )
        print(
            "READ-ONLY MODE: Google Sheets, dashboard, "
            "Webull, previews, and orders are disabled."
        )

        for trading_date in dates:
            date_str = trading_date.isoformat()

            try:
                with redirect_stdout(StringIO()):
                    self.refresh_symbols_for_date(
                        date_str,
                        data_feed=data_feed,
                    )

                symbols_csv = self.symbols_csv

                session_start = datetime.combine(
                    trading_date,
                    time(hour=9, minute=30),
                    tzinfo=eastern,
                ).astimezone(utc)

                session_end = datetime.combine(
                    trading_date,
                    time(hour=16),
                    tzinfo=eastern,
                ).astimezone(utc)

                bars_by_symbol = (
                    self.alpaca.get_historical_1min_bars(
                        symbols_csv=symbols_csv,
                        start_iso=session_start.strftime(
                            "%Y-%m-%dT%H:%M:%SZ"
                        ),
                        end_iso=session_end.strftime(
                            "%Y-%m-%dT%H:%M:%SZ"
                        ),
                        feed=data_feed,
                    )
                )

                atrs = (
                    self.alpaca
                    .get_previous_day_ranges_all(
                        symbols_csv=symbols_csv,
                        date_str=date_str,
                        feed=data_feed,
                    )
                )

                before_count = len(report.records)

                analyser = (
                    analyse_symbol_day_multiple_impulses
                    if multiple_impulses
                    else analyse_symbol_day
                )

                for symbol in self.stocks:
                    records = analyser(
                        date_str=date_str,
                        symbol=symbol,
                        data_feed=data_feed,
                        bars=bars_by_symbol.get(
                            symbol,
                            [],
                        ),
                        atr=atrs.get(symbol),
                        minimum_impulse_atr=(
                            minimum_impulse_atr
                        ),
                        slippage_bps=slippage_bps,
                        commission_per_share=(
                            commission_per_share
                        ),
                    )

                    report.records.extend(records)

                date_records = report.records[
                    before_count:
                ]

                setups = sum(
                    record.setup_found
                    for record in date_records
                )

                entries = sum(
                    record.outcome in {
                        "WIN",
                        "LOSS",
                    }
                    for record in date_records
                )

                print(
                    f"{date_str}: "
                    f"{len(self.stocks)} symbols, "
                    f"{setups} valid setups, "
                    f"{entries} entered trades."
                )

            except Exception as error:
                report.add_failure(
                    date_str,
                    error,
                )

                print(
                    f"{date_str}: FAILED - {error}"
                )

        print()
        print(
            "===== FIBONACCI RETRACEMENT REPORT ====="
        )
        print(
            f"Research records: {len(report.records)}"
        )
        print(
            f"Failed sessions: "
            f"{len(report.failed_sessions)}"
        )

        for row in report.summary_rows()[:3]:
            win_rate = (
                f"{row['win_rate_pct']:.2f}%"
                if row["win_rate_pct"] is not None
                else "N/A"
            )
            profit_factor = (
                f"{row['profit_factor']:.3f}"
                if row["profit_factor"] is not None
                else "N/A"
            )
            expectancy = (
                f"{row['expectancy_pct']:.4f}%"
                if row["expectancy_pct"] is not None
                else "N/A"
            )

            print(
                f"{row['fibonacci_level']}: "
                f"{row['entered_trades']} entries, "
                f"{win_rate} win rate, "
                f"{profit_factor} profit factor, "
                f"{expectancy} expectancy."
            )

        (
            detail_path,
            summary_path,
            failures_path,
        ) = report.write_csv(output_directory)

        print()
        print(f"Detailed results: {detail_path}")
        print(f"Summary results: {summary_path}")
        print(f"Failed sessions: {failures_path}")

        return report

    def run_fibonacci_entry_stop_comparison(
        self,
        start_date: str,
        end_date: str,
        output_directory: str | Path = (
            "reports/fibonacci-entry-stop-comparison"
        ),
        data_feed: str = MARKET_DATA_FEED,
        slippage_bps: float = 15.0,
        commission_per_share: float = 0.0,
        risk_dollars: float = 25.0,
        maximum_shares: int = 1000,
        maximum_position_value: float = 5000.0,
    ) -> tuple[Path, Path, Path]:
        """
        Compare four Fibonacci entry filters against four stop
        buffers using the current first-impulse research method.

        This workflow is strictly read-only. It cannot write Google
        Sheets, publish the dashboard, call Webull, create previews,
        or submit orders.
        """
        data_feed = data_feed.strip().lower()

        if data_feed not in {"iex", "sip"}:
            raise ValueError(
                "Market-data feed must be 'iex' or 'sip'."
            )

        if slippage_bps < 0:
            raise ValueError(
                "Slippage cannot be negative."
            )

        if commission_per_share < 0:
            raise ValueError(
                "Commission cannot be negative."
            )

        if risk_dollars <= 0:
            raise ValueError(
                "Risk dollars must be positive."
            )

        if maximum_shares <= 0:
            raise ValueError(
                "Maximum shares must be positive."
            )

        if maximum_position_value <= 0:
            raise ValueError(
                "Maximum position value must be positive."
            )

        try:
            start = datetime.strptime(
                start_date,
                "%Y-%m-%d",
            ).date()
            end = datetime.strptime(
                end_date,
                "%Y-%m-%d",
            ).date()
        except ValueError as error:
            raise ValueError(
                "Comparison dates must use YYYY-MM-DD."
            ) from error

        dates = weekday_dates(start, end)

        if not dates:
            raise ValueError(
                "Comparison range contains no weekdays."
            )

        output_directory = Path(output_directory)
        output_directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        entry_variants = [
            {
                "entry_variant": "CONTROL",
                "minimum_impulse_atr": 0.50,
                "minimum_duration_minutes": 15,
            },
            {
                "entry_variant": "DURATION_10",
                "minimum_impulse_atr": 0.50,
                "minimum_duration_minutes": 10,
            },
            {
                "entry_variant": "IMPULSE_045",
                "minimum_impulse_atr": 0.45,
                "minimum_duration_minutes": 15,
            },
            {
                "entry_variant": "COMBINED",
                "minimum_impulse_atr": 0.45,
                "minimum_duration_minutes": 10,
            },
        ]

        stop_variants = [
            {
                "stop_variant": "FIXED_001",
                "stop_buffer_atr": None,
            },
            {
                "stop_variant": "ATR_005",
                "stop_buffer_atr": 0.05,
            },
            {
                "stop_variant": "ATR_010",
                "stop_buffer_atr": 0.10,
            },
            {
                "stop_variant": "ATR_015",
                "stop_buffer_atr": 0.15,
            },
        ]

        variants = [
            {
                **entry_variant,
                **stop_variant,
                "variant": (
                    f"{entry_variant['entry_variant']}__"
                    f"{stop_variant['stop_variant']}"
                ),
            }
            for entry_variant in entry_variants
            for stop_variant in stop_variants
        ]

        records_by_variant = {
            variant["variant"]: []
            for variant in variants
        }

        detail_rows = []
        failure_rows = []

        eastern = ZoneInfo("America/New_York")
        utc = ZoneInfo("UTC")

        print()
        print("===================================")
        print(" Fibonacci Entry/Stop Comparison")
        print("===================================")
        print(
            f"Date range: {start_date} to {end_date}"
        )
        print(f"Market-data feed: {data_feed.upper()}")
        print(
            f"Modeled slippage: {slippage_bps:.1f} bps"
        )
        print(
            f"Risk per trade: ${risk_dollars:.2f}"
        )
        print(f"Variants: {len(variants)}")
        print("Fibonacci level: FIB_61_8")
        print(
            "READ-ONLY MODE: Google Sheets, dashboard, Webull, "
            "previews, and orders are disabled."
        )

        for trading_date in dates:
            date_str = trading_date.isoformat()

            try:
                with redirect_stdout(StringIO()):
                    self.refresh_symbols_for_date(
                        date_str,
                        data_feed=data_feed,
                    )

                symbols_csv = self.symbols_csv

                session_start = datetime.combine(
                    trading_date,
                    time(hour=9, minute=30),
                    tzinfo=eastern,
                ).astimezone(utc)

                session_end = datetime.combine(
                    trading_date,
                    time(hour=16),
                    tzinfo=eastern,
                ).astimezone(utc)

                bars_by_symbol = (
                    self.alpaca.get_historical_1min_bars(
                        symbols_csv=symbols_csv,
                        start_iso=session_start.strftime(
                            "%Y-%m-%dT%H:%M:%SZ"
                        ),
                        end_iso=session_end.strftime(
                            "%Y-%m-%dT%H:%M:%SZ"
                        ),
                        feed=data_feed,
                    )
                )

                atrs = (
                    self.alpaca
                    .get_previous_day_ranges_all(
                        symbols_csv=symbols_csv,
                        date_str=date_str,
                        feed=data_feed,
                    )
                )

                date_qualifying = 0

                for symbol in self.stocks:
                    bars = sorted(
                        bars_by_symbol.get(symbol, []),
                        key=lambda bar: str(bar["t"]),
                    )
                    atr = atrs.get(symbol)

                    for variant in variants:
                        setup = analyse_retracement_level(
                            date_str=date_str,
                            symbol=symbol,
                            data_feed=data_feed,
                            bars=bars,
                            atr=atr,
                            level_name="FIB_61_8",
                            ratio=FIBONACCI_LEVELS[
                                "FIB_61_8"
                            ],
                            minimum_impulse_atr=(
                                variant[
                                    "minimum_impulse_atr"
                                ]
                            ),
                            minimum_impulse_duration_minutes=(
                                variant[
                                    "minimum_duration_minutes"
                                ]
                            ),
                            minimum_reward_risk=1.5,
                            stop_buffer_atr=(
                                variant["stop_buffer_atr"]
                            ),
                            slippage_bps=slippage_bps,
                            commission_per_share=(
                                commission_per_share
                            ),
                        )

                        volume_valid = (
                            setup.pullback_volume_ratio
                            is not None
                            and setup.pullback_volume_ratio < 1.0
                        )

                        eligible = (
                            setup.setup_found
                            and volume_valid
                        )

                        if not setup.setup_found:
                            eligibility_reason = (
                                setup.rejection_reason
                                or "SETUP_NOT_FOUND"
                            )
                        elif not volume_valid:
                            eligibility_reason = (
                                "PULLBACK_VOLUME_NOT_LOWER"
                            )
                        else:
                            eligibility_reason = ""

                        stopped_then_target = False
                        risk_per_share = None
                        position_shares = None

                        if (
                            eligible
                            and setup.entry_price is not None
                            and setup.stop_price is not None
                            and setup.target_price is not None
                        ):
                            risk_per_share = (
                                float(setup.entry_price)
                                - float(setup.stop_price)
                            )

                            if risk_per_share > 0:
                                risk_sized_shares = int(
                                    risk_dollars
                                    / risk_per_share
                                )
                                value_sized_shares = int(
                                    maximum_position_value
                                    / float(setup.entry_price)
                                )

                                position_shares = max(
                                    0,
                                    min(
                                        risk_sized_shares,
                                        value_sized_shares,
                                        maximum_shares,
                                    ),
                                )

                            if (
                                setup.outcome == "LOSS"
                                and setup.exit_reason == "STOP"
                            ):
                                confirmation_index = None

                                for index, bar in enumerate(bars):
                                    bar_time = (
                                        datetime.fromisoformat(
                                            str(bar["t"]).replace(
                                                "Z",
                                                "+00:00",
                                            )
                                        )
                                        .astimezone(eastern)
                                        .strftime("%H:%M")
                                    )

                                    if (
                                        bar_time
                                        == setup.confirmation_time
                                    ):
                                        confirmation_index = index
                                        break

                                if confirmation_index is not None:
                                    stopped_then_target = (
                                        stopped_out_then_target(
                                            bars=bars[
                                                confirmation_index + 1:
                                            ],
                                            entry_price=float(
                                                setup.entry_price
                                            ),
                                            stop_price=float(
                                                setup.stop_price
                                            ),
                                            target_price=float(
                                                setup.target_price
                                            ),
                                        )
                                    )

                        row = {
                            "variant": variant["variant"],
                            "entry_variant": (
                                variant["entry_variant"]
                            ),
                            "stop_variant": (
                                variant["stop_variant"]
                            ),
                            "minimum_impulse_atr": (
                                variant[
                                    "minimum_impulse_atr"
                                ]
                            ),
                            "minimum_duration_minutes": (
                                variant[
                                    "minimum_duration_minutes"
                                ]
                            ),
                            "stop_buffer_atr": (
                                variant["stop_buffer_atr"]
                            ),
                            "eligible": eligible,
                            "eligibility_reason": (
                                eligibility_reason
                            ),
                            "stopped_out_then_target": (
                                stopped_then_target
                            ),
                            "risk_per_share": risk_per_share,
                            "position_shares": position_shares,
                            **asdict(setup),
                        }

                        detail_rows.append(row)

                        if eligible:
                            records_by_variant[
                                variant["variant"]
                            ].append(setup)
                            date_qualifying += 1

                print(
                    f"{date_str}: "
                    f"{len(self.stocks)} symbols, "
                    f"{date_qualifying} qualifying "
                    "variant observations."
                )

            except Exception as error:
                failure_rows.append({
                    "date": date_str,
                    "error": str(error),
                })

                print(
                    f"{date_str}: FAILED - {error}"
                )

        summary_rows = []

        for variant in variants:
            variant_name = variant["variant"]
            records = records_by_variant[variant_name]
            metrics = metrics_for(records)

            matching_details = [
                row
                for row in detail_rows
                if (
                    row["variant"] == variant_name
                    and row["eligible"]
                )
            ]

            stop_exits = sum(
                row["exit_reason"] == "STOP"
                for row in matching_details
            )

            stopped_then_target_count = sum(
                bool(row["stopped_out_then_target"])
                for row in matching_details
            )

            risks = [
                float(row["risk_per_share"])
                for row in matching_details
                if row["risk_per_share"] is not None
            ]

            shares = [
                int(row["position_shares"])
                for row in matching_details
                if row["position_shares"] is not None
            ]

            summary_rows.append({
                "variant": variant_name,
                "entry_variant": variant["entry_variant"],
                "stop_variant": variant["stop_variant"],
                "minimum_impulse_atr": (
                    variant["minimum_impulse_atr"]
                ),
                "minimum_duration_minutes": (
                    variant["minimum_duration_minutes"]
                ),
                "stop_buffer_atr": (
                    variant["stop_buffer_atr"]
                ),
                "qualifying_setups": metrics.setups,
                "entered_trades": metrics.entered_trades,
                "wins": metrics.wins,
                "losses": metrics.losses,
                "stop_exits": stop_exits,
                "stopped_out_then_target": (
                    stopped_then_target_count
                ),
                "win_rate_pct": metrics.win_rate_pct,
                "average_return_pct": (
                    metrics.average_return_pct
                ),
                "total_return_pct": (
                    metrics.total_return_pct
                ),
                "profit_factor": metrics.profit_factor,
                "expectancy_pct": metrics.expectancy_pct,
                "maximum_drawdown_pct_points": (
                    metrics.maximum_drawdown_pct_points
                ),
                "average_risk_per_share": (
                    sum(risks) / len(risks)
                    if risks
                    else None
                ),
                "average_position_shares_at_25_dollars": (
                    sum(shares) / len(shares)
                    if shares
                    else None
                ),
            })

        detail_path = (
            output_directory
            / "fibonacci_entry_stop_comparison_details.csv"
        )
        summary_path = (
            output_directory
            / "fibonacci_entry_stop_comparison_summary.csv"
        )
        failures_path = (
            output_directory
            / "fibonacci_entry_stop_comparison_failures.csv"
        )

        if detail_rows:
            with detail_path.open(
                "w",
                newline="",
                encoding="utf-8",
            ) as file:
                writer = csv.DictWriter(
                    file,
                    fieldnames=list(detail_rows[0].keys()),
                )
                writer.writeheader()
                writer.writerows(detail_rows)
        else:
            detail_path.touch()

        with summary_path.open(
            "w",
            newline="",
            encoding="utf-8",
        ) as file:
            writer = csv.DictWriter(
                file,
                fieldnames=list(summary_rows[0].keys()),
            )
            writer.writeheader()
            writer.writerows(summary_rows)

        with failures_path.open(
            "w",
            newline="",
            encoding="utf-8",
        ) as file:
            writer = csv.DictWriter(
                file,
                fieldnames=["date", "error"],
            )
            writer.writeheader()
            writer.writerows(failure_rows)

        ranked = sorted(
            summary_rows,
            key=lambda row: (
                row["expectancy_pct"]
                if row["expectancy_pct"] is not None
                else float("-inf"),
                row["entered_trades"],
            ),
            reverse=True,
        )

        print()
        print("===== ENTRY/STOP COMPARISON COMPLETE =====")
        print(f"Failed sessions: {len(failure_rows)}")
        print()
        print("Top variants by expectancy:")

        for row in ranked[:5]:
            expectancy = (
                f"{row['expectancy_pct']:.4f}%"
                if row["expectancy_pct"] is not None
                else "N/A"
            )
            win_rate = (
                f"{row['win_rate_pct']:.2f}%"
                if row["win_rate_pct"] is not None
                else "N/A"
            )

            print(
                f"{row['variant']}: "
                f"{row['entered_trades']} entries, "
                f"{win_rate} win rate, "
                f"{expectancy} expectancy, "
                f"{row['stopped_out_then_target']} "
                "stopped-then-target."
            )

        print()
        print(f"Detailed results: {detail_path}")
        print(f"Summary results: {summary_path}")
        print(f"Failed sessions: {failures_path}")
        print("No real orders were submitted.")

        return detail_path, summary_path, failures_path

    def run_fibonacci_impulse_comparison(
        self,
        start_date: str,
        end_date: str,
        output_directory: str | Path = (
            "reports/fibonacci-impulse-comparison"
        ),
        data_feed: str = MARKET_DATA_FEED,
        slippage_bps: float = 15.0,
        commission_per_share: float = 0.0,
        minimum_impulse_atr: float = 0.50,
    ) -> tuple[
        FibonacciRetracementReport,
        FibonacciRetracementReport,
    ]:
        """
        Compare the current first-impulse research method with the
        research-only multiple-impulse method.

        This workflow cannot write Google Sheets, publish dashboard
        sessions, call Webull, create previews, or submit orders.
        """
        output_directory = Path(output_directory)

        print()
        print("===================================")
        print(" Fibonacci Impulse Comparison")
        print("===================================")
        print(
            f"Date range: {start_date} to {end_date}"
        )
        print(f"Market-data feed: {data_feed.upper()}")
        print(
            f"Modeled slippage: {slippage_bps:.1f} bps"
        )
        print(
            "READ-ONLY MODE: Google Sheets, dashboard, Webull, "
            "previews, and orders are disabled."
        )

        print()
        print("Running current first-impulse method...")

        first_report = (
            self.run_fibonacci_retracement_research(
                start_date=start_date,
                end_date=end_date,
                output_directory=(
                    output_directory / "first-impulse"
                ),
                data_feed=data_feed,
                slippage_bps=slippage_bps,
                commission_per_share=(
                    commission_per_share
                ),
                minimum_impulse_atr=(
                    minimum_impulse_atr
                ),
                multiple_impulses=False,
            )
        )

        print()
        print(
            "Running research-only multiple-impulse method..."
        )

        multiple_report = (
            self.run_fibonacci_retracement_research(
                start_date=start_date,
                end_date=end_date,
                output_directory=(
                    output_directory / "multiple-impulses"
                ),
                data_feed=data_feed,
                slippage_bps=slippage_bps,
                commission_per_share=(
                    commission_per_share
                ),
                minimum_impulse_atr=(
                    minimum_impulse_atr
                ),
                multiple_impulses=True,
            )
        )

        output_directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        comparison_path = (
            output_directory
            / "fibonacci_impulse_comparison_summary.csv"
        )

        rows = []

        for method_name, report in (
            ("FIRST_IMPULSE", first_report),
            ("MULTIPLE_IMPULSES", multiple_report),
        ):
            for summary in report.summary_rows():
                if summary.get("scope") != "LEVEL":
                    continue

                rows.append({
                    "method": method_name,
                    "fibonacci_level": (
                        summary["fibonacci_level"]
                    ),
                    "setups": summary["setups"],
                    "entered_trades": (
                        summary["entered_trades"]
                    ),
                    "wins": summary["wins"],
                    "losses": summary["losses"],
                    "no_entry": summary["no_entry"],
                    "rejected_reward_risk": (
                        summary["rejected_reward_risk"]
                    ),
                    "win_rate_pct": (
                        summary["win_rate_pct"]
                    ),
                    "average_return_pct": (
                        summary["average_return_pct"]
                    ),
                    "total_return_pct": (
                        summary["total_return_pct"]
                    ),
                    "profit_factor": (
                        summary["profit_factor"]
                    ),
                    "expectancy_pct": (
                        summary["expectancy_pct"]
                    ),
                    "maximum_drawdown_pct_points": (
                        summary[
                            "maximum_drawdown_pct_points"
                        ]
                    ),
                })

        if not rows:
            raise RuntimeError(
                "Impulse comparison produced no summary rows."
            )

        with comparison_path.open(
            "w",
            newline="",
            encoding="utf-8",
        ) as file:
            writer = csv.DictWriter(
                file,
                fieldnames=list(rows[0].keys()),
            )
            writer.writeheader()
            writer.writerows(rows)

        print()
        print("===== IMPULSE COMPARISON COMPLETE =====")

        for level_name in FIBONACCI_LEVELS:
            first = next(
                row
                for row in rows
                if (
                    row["method"] == "FIRST_IMPULSE"
                    and row["fibonacci_level"]
                    == level_name
                )
            )

            multiple = next(
                row
                for row in rows
                if (
                    row["method"] == "MULTIPLE_IMPULSES"
                    and row["fibonacci_level"]
                    == level_name
                )
            )

            print()
            print(level_name)
            print(
                "First impulse:",
                f"{first['entered_trades']} entries,",
                f"{first['win_rate_pct']}% win rate,",
                f"{first['expectancy_pct']}% expectancy",
            )
            print(
                "Multiple impulses:",
                f"{multiple['entered_trades']} entries,",
                f"{multiple['win_rate_pct']}% win rate,",
                f"{multiple['expectancy_pct']}% expectancy",
            )

        print()
        print(f"Comparison summary: {comparison_path}")
        print("No real orders were submitted.")

        return first_report, multiple_report

    def run_fibonacci_research(
        self,
        start_date: str,
        end_date: str,
        output_directory: str | Path = "reports/fibonacci",
        data_feed: str = MARKET_DATA_FEED,
        slippage_bps: float = 0.0,
        commission_per_share: float = 0.0,
    ) -> FibonacciResearchReport:
        """
        Compare Fibonacci opening-range targets and setup rules.

        This workflow is research-only. It cannot write Google
        Sheets, upload the dashboard, call Webull, or submit orders.
        """
        data_feed = data_feed.strip().lower()

        if data_feed not in {"iex", "sip"}:
            raise ValueError(
                "Market-data feed must be 'iex' or 'sip'."
            )

        if slippage_bps < 0:
            raise ValueError(
                "Slippage cannot be negative."
            )

        if commission_per_share < 0:
            raise ValueError(
                "Commission cannot be negative."
            )

        try:
            start = datetime.strptime(
                start_date,
                "%Y-%m-%d",
            ).date()
            end = datetime.strptime(
                end_date,
                "%Y-%m-%d",
            ).date()
        except ValueError as error:
            raise ValueError(
                "Research dates must use YYYY-MM-DD format."
            ) from error

        dates = weekday_dates(start, end)

        if not dates:
            raise ValueError(
                "Research range contains no weekdays."
            )

        report = FibonacciResearchReport(
            start_date=start_date,
            end_date=end_date,
            data_feed=data_feed,
            slippage_bps=slippage_bps,
            commission_per_share=commission_per_share,
        )

        eastern = ZoneInfo("America/New_York")
        utc = ZoneInfo("UTC")

        print()
        print("===================================")
        print(" Fibonacci Strategy Research")
        print("===================================")
        print(
            f"Date range: {start_date} to {end_date}"
        )
        print(f"Market-data feed: {data_feed.upper()}")
        print(
            "READ-ONLY MODE: Google Sheets, dashboard, "
            "Webull, and orders are disabled."
        )

        for trading_date in dates:
            date_str = trading_date.isoformat()

            try:
                with redirect_stdout(StringIO()):
                    session = self.run_replay(
                        date_str=date_str,
                        speed=0,
                        publish_dashboard=False,
                        data_feed=data_feed,
                        slippage_bps=0.0,
                        commission_per_share=0.0,
                    )

                outcome_start = datetime.combine(
                    trading_date,
                    time(hour=9, minute=45),
                    tzinfo=eastern,
                ).astimezone(utc)

                outcome_end = datetime.combine(
                    trading_date,
                    time(hour=16),
                    tzinfo=eastern,
                ).astimezone(utc)

                outcome_bars = (
                    self.alpaca.get_historical_1min_bars(
                        symbols_csv=",".join(
                            session.stocks
                        ),
                        start_iso=outcome_start.strftime(
                            "%Y-%m-%dT%H:%M:%SZ"
                        ),
                        end_iso=outcome_end.strftime(
                            "%Y-%m-%dT%H:%M:%SZ"
                        ),
                        feed=data_feed,
                    )
                )

                for symbol, stock in (
                    session.stocks.items()
                ):
                    report.add_stock(
                        date_str=date_str,
                        symbol=symbol,
                        stock=stock,
                        bars_processed=(
                            session.summary
                            .processed_bars
                            .get(symbol, 0)
                        ),
                        outcome_bars=outcome_bars.get(
                            symbol,
                            [],
                        ),
                    )

                date_records = [
                    record
                    for record in report.records
                    if record.date == date_str
                ]

                eligible = sum(
                    record.setup_eligible
                    for record in date_records
                )

                print(
                    f"{date_str}: "
                    f"{len(session.stocks)} symbols, "
                    f"{eligible} eligible rule-target "
                    "observations."
                )

            except Exception as error:
                report.add_failure(
                    date_str,
                    error,
                )
                print(
                    f"{date_str}: FAILED - {error}"
                )

        report.print_summary()

        (
            detail_path,
            summary_path,
            symbol_path,
            failure_path,
        ) = report.write_csv(output_directory)

        print()
        print(f"Trade-level results: {detail_path}")
        print(f"Rule comparison: {summary_path}")
        print(f"Symbol comparison: {symbol_path}")
        print(f"Failed sessions: {failure_path}")

        return report

    def run_backtest(
            self,
            start_date: str,
            end_date: str,
        output_directory: str | Path = "reports",
        data_feed: str = MARKET_DATA_FEED,
        slippage_bps: float = 0.0,
        commission_per_share: float = 0.0,
        train_fraction: float = 0.70,
    ) -> BacktestReport:
        data_feed = data_feed.strip().lower()
        if data_feed not in {"iex", "sip"}:
            raise ValueError(
                "Market-data feed must be 'iex' or 'sip'."
            )
        if slippage_bps < 0:
            raise ValueError(
                "Slippage cannot be negative."
            )
        if commission_per_share < 0:
            raise ValueError(
                "Commission cannot be negative."
            )
        if not 0.1 <= train_fraction <= 0.9:
            raise ValueError(
                "Train fraction must be between 0.1 and 0.9."
            )
        try:
            start = datetime.strptime(
                start_date,
                "%Y-%m-%d",
            ).date()
            end = datetime.strptime(
                end_date,
                "%Y-%m-%d",
            ).date()
        except ValueError as error:
            raise ValueError(
                "Backtest dates must use YYYY-MM-DD format."
            ) from error

        dates = weekday_dates(start, end)
        if not dates:
            raise ValueError(
                "Backtest range contains no weekdays."
            )

        report = BacktestReport(
            start_date=start_date,
            end_date=end_date,
            data_feed=data_feed,
            slippage_bps=slippage_bps,
            commission_per_share=commission_per_share,
            train_fraction=train_fraction,
        )

        benchmark_start = (
            start - timedelta(days=60)
        ).isoformat()
        try:
            benchmark_bars = (
                self.alpaca.get_historical_daily_bars(
                    symbols_csv="SPY,QQQ",
                    start_date=benchmark_start,
                    end_date=end_date,
                    feed=data_feed,
                )
            )
            regimes = market_regimes_by_date(
                benchmark_bars,
                dates,
            )
        except Exception as error:
            print(
                "Market-regime data unavailable; "
                f"continuing without it: {error}"
            )
            regimes = {}

        print()
        print("===================================")
        print(" Multi-Day Historical Backtest")
        print("===================================")
        print(
            f"Date range: {start_date} to {end_date}"
        )
        print(f"Market-data feed: {data_feed.upper()}")
        print(
            "Execution assumptions: "
            f"{slippage_bps:.2f} bps slippage per side, "
            f"${commission_per_share:.4f} commission "
            "per share per side"
        )
        print(
            "READ-ONLY MODE: Google Sheets, dashboard "
            "uploads, Orders, and trading are disabled."
        )

        for trading_date in dates:
            date_str = trading_date.isoformat()

            try:
                with redirect_stdout(StringIO()):
                    session = self.run_replay(
                        date_str=date_str,
                        speed=0,
                        publish_dashboard=False,
                        data_feed=data_feed,
                        slippage_bps=slippage_bps,
                        commission_per_share=(
                            commission_per_share
                        ),
                    )
            except Exception as error:
                report.add_failure(date_str, error)
                print(
                    f"{date_str}: FAILED - {error}"
                )
                continue

            session.summary.market_regimes = regimes.get(
                date_str,
                {},
            )
            report.add_session(session)
            metrics = report.metrics_for([
                record
                for record in report.records
                if record.date == date_str
            ])

            print(
                f"{date_str}: "
                f"{metrics.invest_signals} signals, "
                f"{metrics.wins} wins, "
                f"{metrics.losses} losses, "
                f"{metrics.unresolved} unresolved, "
                f"{metrics.no_entry} no entry, "
                f"{metrics.incomplete_ticker_days} "
                "incomplete ticker-days"
            )

        report.print_summary()
        (
            detail_path,
            summary_path,
            missing_path,
            robustness_path,
            atr_path,
            split_path,
        ) = report.write_csv(output_directory)

        print()
        print(f"Detailed results: {detail_path}")
        print(f"Summary results: {summary_path}")
        print(
            f"Missing-bar diagnostics: {missing_path}"
        )
        print(
            f"Filter comparisons: {robustness_path}"
        )
        print(f"ATR diagnostics: {atr_path}")
        print(
            f"Chronological train/test: {split_path}"
        )

        return report

    def run_strategy_test(self) -> None:
        test_date = "2026-07-23"

        print()
        print(f"Testing strategy for {test_date}...")

        self.calculate_strategy(test_date)

        print()
        print("===== STRATEGY RESULTS =====")

        for stock in self.stocks.values():
            if stock.opening_bar is None:
                print(f"{stock.symbol}: no opening bar")
                continue

            if stock.atr is None:
                print(f"{stock.symbol}: insufficient ATR data")
                continue

            print()
            print(f"Symbol: {stock.symbol}")
            print(f"ATR: {stock.atr:.4f}")
            print(f"Opening range: {stock.candle_range:.4f}")
            print(f"ATR threshold: {stock.atr_threshold:.4f}")
            print(
                "Manipulation:",
                "YES" if stock.is_manipulation else "NO",
            )
            print(
                "Red candle:",
                "YES" if stock.is_red else "NO",
            )
            print(f"Signal: {stock.signal}")
            print(f"Limit buy: {stock.limit_buy:.4f}")
            print(f"Limit sell: {stock.limit_sell:.4f}")
            print(f"Stop loss: {stock.stop_loss:.4f}")
            print(
                "Trading stop loss:",
                f"{stock.trading_stop_loss:.4f}",
            )
            print(f"Proximity: {stock.proximity}")

        print()
        print("Strategy test completed.")

    def _calculate_manipulation_strategy(
            self,
            date_str: str,
    ) -> None:
        """
        Preserved manipulation strategy path.

        Retained for historical replay, comparison, and audit
        purposes. It is not deleted when Fibonacci becomes active.
        """
        opening_bars = self.alpaca.get_opening_15min_bars(
            symbols_csv=self.symbols_csv,
            date_str=date_str,
        )

        atrs = self.alpaca.get_previous_day_ranges_all(
            symbols_csv=self.symbols_csv,
            date_str=date_str,
        )

        for symbol, stock in self.stocks.items():
            opening_bar = opening_bars.get(symbol)
            atr = atrs.get(symbol)

            stock.opening_bar = opening_bar
            stock.atr = atr
            stock.strategy_name = MANIPULATION_STRATEGY_NAME
            stock.strategy_status = (
                "PRESERVED HISTORICAL STRATEGY"
            )

            if opening_bar is None or atr is None:
                stock.signal = "NO INVEST"

                print(
                    f"{symbol}: manipulation strategy skipped "
                    "because valid opening-bar or ATR data "
                    "was unavailable."
                )
                continue

            try:
                self.strategy.evaluate(
                    stock=stock,
                    opening_bar=opening_bar,
                    atr=atr,
                )

            except Exception as error:
                stock.signal = "NO INVEST"

                print(
                    f"{symbol}: manipulation strategy "
                    f"evaluation failed: {error}"
                )

    @staticmethod
    def _quick_flip_candle_from_bar(
            bar: dict,
    ) -> QuickFlipCandle:
        """
        Convert one Alpaca OHLC bar into the immutable candle
        representation used by Quick Flip.

        This conversion performs no strategy evaluation.
        """
        timestamp_text = str(
            bar["t"]
        ).strip()

        if timestamp_text.endswith("Z"):
            timestamp_text = (
                timestamp_text[:-1] + "+00:00"
            )

        return QuickFlipCandle(
            timestamp=datetime.fromisoformat(
                timestamp_text
            ),
            open=float(bar["o"]),
            high=float(bar["h"]),
            low=float(bar["l"]),
            close=float(bar["c"]),
            volume=float(
                bar.get("v", 0) or 0
            ),
        )

    def _calculate_quick_flip_strategy(
            self,
            date_str: str,
            evaluation_end: datetime | None = None,
            data_feed: str = MARKET_DATA_FEED,
    ) -> dict:
        """
        Evaluate Quick Flip independently of Manipulation.

        Quick Flip:
        - uses the completed 09:30-09:45 opening candle;
        - compares that candle with Wilder ATR14;
        - watches completed 5-minute candles from 09:45;
        - stops accepting new setups at 11:00 ET;
        - stores results separately from Stock.signal;
        - never creates a stop-loss value;
        - never submits an order.
        """
        eastern = ZoneInfo("America/New_York")
        utc = ZoneInfo("UTC")

        trading_date = datetime.strptime(
            date_str,
            "%Y-%m-%d",
        ).date()

        monitor_start = datetime.combine(
            trading_date,
            time(hour=9, minute=45),
            tzinfo=eastern,
        )

        monitor_cutoff = datetime.combine(
            trading_date,
            time(hour=11, minute=0),
            tzinfo=eastern,
        )

        if evaluation_end is None:
            normalized_end = monitor_cutoff
        else:
            normalized_end = evaluation_end

            if normalized_end.tzinfo is None:
                normalized_end = (
                    normalized_end.replace(
                        tzinfo=eastern,
                    )
                )
            else:
                normalized_end = (
                    normalized_end.astimezone(
                        eastern
                    )
                )

            if normalized_end > monitor_cutoff:
                normalized_end = monitor_cutoff

        self.quick_flip_results = {}
        self.quick_flip_status = {}

        opening_bars = (
            self.alpaca.get_opening_15min_bars(
                symbols_csv=self.symbols_csv,
                date_str=date_str,
                feed=data_feed,
            )
        )

        atrs = (
            self.alpaca.get_previous_day_ranges_all(
                symbols_csv=self.symbols_csv,
                date_str=date_str,
                feed=data_feed,
            )
        )

        bars_by_symbol = {
            symbol: []
            for symbol in self.stocks
        }

        if normalized_end > monitor_start:
            start_utc = (
                monitor_start
                .astimezone(utc)
            )

            end_utc = (
                normalized_end
                .astimezone(utc)
            )

            bars_by_symbol = (
                self.alpaca
                .get_historical_1min_bars(
                    symbols_csv=self.symbols_csv,
                    start_iso=start_utc.strftime(
                        "%Y-%m-%dT%H:%M:%SZ"
                    ),
                    end_iso=end_utc.strftime(
                        "%Y-%m-%dT%H:%M:%SZ"
                    ),
                    feed=data_feed,
                )
            )

        cutoff_reached = (
            normalized_end >= monitor_cutoff
        )

        for symbol in self.stocks:
            opening_bar = opening_bars.get(
                symbol
            )

            atr_14 = atrs.get(
                symbol
            )

            if opening_bar is None:
                self.quick_flip_results[
                    symbol
                ] = None

                self.quick_flip_status[
                    symbol
                ] = "MISSING_OPENING_BAR"

                print(
                    f"{symbol}: Quick Flip skipped "
                    "because the opening 15-minute "
                    "bar was unavailable."
                )

                continue

            if atr_14 is None:
                self.quick_flip_results[
                    symbol
                ] = None

                self.quick_flip_status[
                    symbol
                ] = "MISSING_ATR14"

                print(
                    f"{symbol}: Quick Flip skipped "
                    "because ATR14 was unavailable."
                )

                continue

            try:
                opening_candle = (
                    self._quick_flip_candle_from_bar(
                        opening_bar
                    )
                )

                result = (
                    self.quick_flip_monitor
                    .evaluate_minute_bars(
                        symbol=symbol,
                        opening_bar=opening_candle,
                        atr_14=float(atr_14),
                        minute_bars=(
                            bars_by_symbol.get(
                                symbol,
                                [],
                            )
                        ),
                        evaluation_end=(
                            normalized_end
                            .astimezone(utc)
                        ),
                        cutoff_reached=(
                            cutoff_reached
                        ),
                    )
                )

                self.quick_flip_results[
                    symbol
                ] = result

                self.quick_flip_status[
                    symbol
                ] = result.status

            except Exception as error:
                self.quick_flip_results[
                    symbol
                ] = None

                self.quick_flip_status[
                    symbol
                ] = "EVALUATION_FAILED"

                print(
                    f"{symbol}: Quick Flip "
                    f"evaluation failed: {error}"
                )

        return dict(
            self.quick_flip_results
        )

    def calculate_parallel_strategies(
            self,
            date_str: str,
            evaluation_end: datetime | None = None,
            data_feed: str = MARKET_DATA_FEED,
    ) -> dict:
        """
        Evaluate Manipulation and Quick Flip independently.

        Manipulation continues to own the legacy Stock strategy
        fields.

        Quick Flip writes only to self.quick_flip_results and
        self.quick_flip_status.

        Therefore one strategy cannot overwrite the other's
        signal state.
        """
        print()
        print(
            "Running Manipulation + Quick Flip "
            "in parallel..."
        )

        self._calculate_manipulation_strategy(
            date_str=date_str,
        )

        quick_flip_results = (
            self._calculate_quick_flip_strategy(
                date_str=date_str,
                evaluation_end=evaluation_end,
                data_feed=data_feed,
            )
        )

        manipulation_invest = [
            symbol
            for symbol, stock
            in self.stocks.items()
            if stock.signal == "INVEST"
        ]

        quick_flip_invest = [
            symbol
            for symbol, result
            in quick_flip_results.items()
            if (
                result is not None
                and result.signal is not None
                and result.signal.signal
                == "INVEST"
            )
        ]

        print(
            "Manipulation INVEST:",
            (
                ", ".join(
                    manipulation_invest
                )
                if manipulation_invest
                else "None"
            ),
        )

        print(
            "Quick Flip INVEST:",
            (
                ", ".join(
                    quick_flip_invest
                )
                if quick_flip_invest
                else "None"
            ),
        )

        return {
            "manipulation": (
                manipulation_invest
            ),
            "quick_flip": (
                quick_flip_invest
            ),
        }

    def _set_fibonacci_performance_metric(
            self,
            name: str,
            value,
    ) -> None:
        metrics = getattr(
            self,
            "_fibonacci_performance_metrics",
            None,
        )

        if metrics is None:
            metrics = {}
            self._fibonacci_performance_metrics = metrics

        metrics[name] = value

    def _print_fibonacci_cycle_performance(
            self,
            *,
            total_seconds: float,
            sheets_preview_seconds: float | None = None,
            dashboard_seconds: float | None = None,
    ) -> None:
        metrics = getattr(
            self,
            "_fibonacci_performance_metrics",
            {},
        )

        print()
        print("Fibonacci cycle performance:")

        if metrics.get("static_data_cached"):
            print("  Static session data: cached")
        elif "static_data_seconds" in metrics:
            print(
                "  Static session data: "
                f"{metrics['static_data_seconds']:.3f}s"
            )

        if metrics.get("intraday_fetch_cached"):
            print("  Intraday Alpaca fetch: cached")
        elif "intraday_fetch_seconds" in metrics:
            print(
                "  Intraday Alpaca fetch: "
                f"{metrics['intraday_fetch_seconds']:.3f}s"
            )

        if "strategy_compute_seconds" in metrics:
            print(
                "  Fibonacci calculation: "
                f"{metrics['strategy_compute_seconds']:.3f}s"
            )

        if "strategy_evaluation_seconds" in metrics:
            print(
                "  Strategy evaluation total: "
                f"{metrics['strategy_evaluation_seconds']:.3f}s"
            )

        if sheets_preview_seconds is not None:
            print(
                "  Sheets + Webull preview: "
                f"{sheets_preview_seconds:.3f}s"
            )

        if dashboard_seconds is not None:
            print(
                "  Dashboard upload: "
                f"{dashboard_seconds:.3f}s"
            )

        print(
            f"  Total cycle: {total_seconds:.3f}s"
        )

    def _get_fibonacci_session_static_data(
            self,
            *,
            date_str: str,
            data_feed: str,
    ) -> tuple[
        dict[str, dict | None],
        dict[str, float | None],
    ]:
        """
        Return Fibonacci inputs that remain fixed for a session.

        Opening 09:30-09:45 bars and prior-day ATR values do not
        change during the live Fibonacci monitoring window, so
        repeated Alpaca requests are avoided after the first load.

        The cache is isolated by trading date, market-data feed,
        and the exact selected symbol set.
        """
        cache = getattr(
            self,
            "_fibonacci_session_static_cache",
            None,
        )

        if cache is None:
            cache = {}
            self._fibonacci_session_static_cache = cache

        cache_key = (
            date_str,
            data_feed.strip().lower(),
            self.symbols_csv,
        )

        cached = cache.get(cache_key)

        if cached is not None:
            self._set_fibonacci_performance_metric(
                "static_data_cached",
                True,
            )
            self._set_fibonacci_performance_metric(
                "static_data_seconds",
                0.0,
            )
            return cached

        static_started = time_module.perf_counter()

        opening_bars = (
            self.alpaca.get_opening_15min_bars(
                symbols_csv=self.symbols_csv,
                date_str=date_str,
                feed=data_feed,
            )
        )

        atrs = (
            self.alpaca.get_previous_day_ranges_all(
                symbols_csv=self.symbols_csv,
                date_str=date_str,
                feed=data_feed,
            )
        )

        result = (
            opening_bars,
            atrs,
        )

        cache[cache_key] = result

        self._set_fibonacci_performance_metric(
            "static_data_cached",
            False,
        )
        self._set_fibonacci_performance_metric(
            "static_data_seconds",
            time_module.perf_counter()
            - static_started,
        )

        return result

    def _get_fibonacci_intraday_bars(
            self,
            *,
            date_str: str,
            data_feed: str,
            session_start: datetime,
            evaluation_end: datetime,
    ) -> dict[str, list[dict]]:
        """
        Return complete intraday Fibonacci history while only
        requesting newly available one-minute bars from Alpaca.

        The cache is isolated by trading date, feed, and selected
        symbols. Each incremental request overlaps the previous
        boundary by one minute and bars are deduplicated by
        timestamp, allowing late/revised data to be reconciled.
        """
        utc = ZoneInfo("UTC")

        cache = getattr(
            self,
            "_fibonacci_intraday_bar_cache",
            None,
        )

        if cache is None:
            cache = {}
            self._fibonacci_intraday_bar_cache = cache

        cache_key = (
            date_str,
            data_feed.strip().lower(),
            self.symbols_csv,
        )

        entry = cache.get(cache_key)

        if entry is None:
            entry = {
                "bars": {
                    symbol: []
                    for symbol in self.stocks
                },
                "fetched_through": None,
            }
            cache[cache_key] = entry

        fetched_through = entry["fetched_through"]

        # If this request is already covered by the cache, avoid
        # another Alpaca call and return only bars before the
        # requested completed-bar boundary.
        if (
            fetched_through is not None
            and evaluation_end <= fetched_through
        ):
            self._set_fibonacci_performance_metric(
                "intraday_fetch_cached",
                True,
            )
            self._set_fibonacci_performance_metric(
                "intraday_fetch_seconds",
                0.0,
            )

            end_iso = evaluation_end.astimezone(
                utc
            ).strftime("%Y-%m-%dT%H:%M:%SZ")

            return {
                symbol: [
                    bar
                    for bar in entry["bars"].get(
                        symbol,
                        [],
                    )
                    if str(bar["t"]) < end_iso
                ]
                for symbol in self.stocks
            }

        if fetched_through is None:
            fetch_start = session_start
        else:
            # Deliberately overlap by one minute. This allows a
            # late IEX bar at the previous boundary to be picked
            # up without creating duplicates in the cache.
            fetch_start = max(
                session_start,
                fetched_through - timedelta(minutes=1),
            )

        start_iso = fetch_start.astimezone(
            utc
        ).strftime("%Y-%m-%dT%H:%M:%SZ")

        end_iso = evaluation_end.astimezone(
            utc
        ).strftime("%Y-%m-%dT%H:%M:%SZ")

        intraday_started = time_module.perf_counter()

        incremental = (
            self.alpaca.get_historical_1min_bars(
                symbols_csv=self.symbols_csv,
                start_iso=start_iso,
                end_iso=end_iso,
                feed=data_feed,
            )
        )

        self._set_fibonacci_performance_metric(
            "intraday_fetch_cached",
            False,
        )
        self._set_fibonacci_performance_metric(
            "intraday_fetch_seconds",
            time_module.perf_counter()
            - intraday_started,
        )

        merged_by_symbol = {}

        for symbol in self.stocks:
            by_timestamp = {
                str(bar["t"]): bar
                for bar in entry["bars"].get(
                    symbol,
                    [],
                )
            }

            for bar in incremental.get(symbol, []):
                by_timestamp[str(bar["t"])] = bar

            merged_by_symbol[symbol] = sorted(
                by_timestamp.values(),
                key=lambda bar: str(bar["t"]),
            )

        # Only update the cache after the Alpaca request and merge
        # complete successfully. A failed request therefore leaves
        # the previous known-good cache untouched.
        entry["bars"] = merged_by_symbol
        entry["fetched_through"] = evaluation_end

        return {
            symbol: [
                bar
                for bar in merged_by_symbol.get(
                    symbol,
                    [],
                )
                if str(bar["t"]) < end_iso
            ]
            for symbol in self.stocks
        }

    def _calculate_fibonacci_strategy(
            self,
            date_str: str,
            evaluation_end: datetime | None = None,
            data_feed: str = MARKET_DATA_FEED,
    ) -> None:
        """
        Evaluate Fibonacci using only bars available through
        evaluation_end.

        For today's session, evaluation_end is always clamped to
        the current New York time to prevent future-bar look-ahead.
        """
        eastern = ZoneInfo("America/New_York")
        utc = ZoneInfo("UTC")

        trading_date = datetime.strptime(
            date_str,
            "%Y-%m-%d",
        ).date()

        now_eastern = datetime.now(eastern)

        session_start = datetime.combine(
            trading_date,
            time(hour=9, minute=30),
            tzinfo=eastern,
        )

        session_close = datetime.combine(
            trading_date,
            time(hour=16),
            tzinfo=eastern,
        )

        if evaluation_end is None:
            if trading_date == now_eastern.date():
                evaluation_end_eastern = now_eastern
            else:
                evaluation_end_eastern = session_close
        elif evaluation_end.tzinfo is None:
            evaluation_end_eastern = evaluation_end.replace(
                tzinfo=eastern
            )
        else:
            evaluation_end_eastern = (
                evaluation_end.astimezone(eastern)
            )

        evaluation_end_eastern = min(
            evaluation_end_eastern,
            session_close,
        )

        if trading_date == now_eastern.date():
            evaluation_end_eastern = min(
                evaluation_end_eastern,
                now_eastern,
            )

        opening_bars, atrs = (
            self._get_fibonacci_session_static_data(
                date_str=date_str,
                data_feed=data_feed,
            )
        )

        if evaluation_end_eastern <= session_start:
            bars_by_symbol = {
                symbol: []
                for symbol in self.stocks
            }
        else:
            bars_by_symbol = (
                self._get_fibonacci_intraday_bars(
                    date_str=date_str,
                    data_feed=data_feed,
                    session_start=session_start,
                    evaluation_end=evaluation_end_eastern,
                )
            )

        strategy_compute_started = (
            time_module.perf_counter()
        )

        print(
            "Fibonacci evaluation cutoff:",
            evaluation_end_eastern.strftime(
                "%Y-%m-%d %H:%M:%S %Z"
            ),
        )

        for symbol, stock in self.stocks.items():
            stock.opening_bar = opening_bars.get(symbol)
            stock.atr = atrs.get(symbol)

            try:
                self.fibonacci_strategy.evaluate(
                    stock=stock,
                    date_str=date_str,
                    bars=bars_by_symbol.get(symbol, []),
                    atr=stock.atr,
                    data_feed=data_feed,
                )

            except Exception as error:
                stock.signal = "NO INVEST"
                stock.strategy_name = (
                    FIBONACCI_STRATEGY_NAME
                )
                stock.strategy_status = (
                    "ACTIVE PAPER/PREVIEW — NOT SUBMITTED"
                )
                stock.strategy_detail = str(error)
                stock.strategy_rejection_reason = (
                    "STRATEGY_EVALUATION_FAILED"
                )

                print(
                    f"{symbol}: Fibonacci strategy "
                    f"evaluation failed: {error}"
                )

        self._set_fibonacci_performance_metric(
            "strategy_compute_seconds",
            time_module.perf_counter()
            - strategy_compute_started,
        )

    def calculate_strategy(
            self,
            date_str: str,
            evaluation_end: datetime | None = None,
            data_feed: str = MARKET_DATA_FEED,
    ) -> None:
        """
        Route active signals without deleting either strategy.
        """
        print(f"Configured active strategy: {ACTIVE_STRATEGY}")

        if ACTIVE_STRATEGY == FIBONACCI_STRATEGY_NAME:
            self._calculate_fibonacci_strategy(
                date_str=date_str,
                evaluation_end=evaluation_end,
                data_feed=data_feed,
            )
            return

        if ACTIVE_STRATEGY == MANIPULATION_STRATEGY_NAME:
            self._calculate_manipulation_strategy(
                date_str=date_str,
            )
            return

        raise RuntimeError(
            f"Unsupported active strategy: {ACTIVE_STRATEGY}"
        )

    def current_invest_symbols(self) -> list[str]:
        """
        Return the symbols currently approved by the active
        strategy for paper/preview handling.
        """
        return [
            stock.symbol
            for stock in self.stocks.values()
            if stock.signal == "INVEST"
        ]

    def current_signal_signature(
            self,
    ) -> tuple[tuple[object, ...], ...]:
        """
        Create a stable representation of current INVEST signals.

        The Fibonacci monitor uses this to avoid duplicate Sheets
        writes, Webull previews, and Cloudflare updates.
        """
        return tuple(
            sorted(
                (
                    stock.symbol,
                    stock.strategy_name,
                    stock.signal,
                    stock.limit_buy,
                    stock.limit_sell,
                    stock.trading_stop_loss,
                    stock.confirmation_time,
                )
                for stock in self.stocks.values()
                if stock.signal == "INVEST"
            )
        )

    def evaluate_active_strategy(
            self,
            date_str: str,
            evaluation_end: datetime | None = None,
            data_feed: str = MARKET_DATA_FEED,
    ) -> list[str]:
        """
        Evaluate the configured strategy without writing external
        outputs.
        """
        print()
        print(f"Running strategy for {date_str}...")

        if (
            evaluation_end is None
            and data_feed == MARKET_DATA_FEED
        ):
            # Preserve compatibility with the original one-argument
            # strategy interface and existing controlled tests.
            self.calculate_strategy(date_str)
        else:
            self.calculate_strategy(
                date_str=date_str,
                evaluation_end=evaluation_end,
                data_feed=data_feed,
            )

        invest_symbols = self.current_invest_symbols()

        print(
            "INVEST signals:",
            ", ".join(invest_symbols)
            if invest_symbols
            else "None",
        )

        return invest_symbols

    def request_webull_approval(
            self,
            symbol: str,
    ) -> WebullApprovalTicket:
        """
        Create a durable manual-approval ticket from a recent
        redacted preview proposal.

        This method cannot submit, modify, replace, or cancel a
        broker order.
        """
        normalized_symbol = symbol.strip().upper()

        if not normalized_symbol:
            raise WebullApprovalError(
                "APPROVAL_SYMBOL_REQUIRED"
            )

        if self.webull_approval_queue is None:
            raise WebullApprovalError(
                "APPROVAL_STORE_UNAVAILABLE"
            )

        try:
            preview = WebullPreviewStore().load_preview(
                normalized_symbol
            )
        except WebullPreviewStoreError as error:
            raise WebullApprovalError(
                "PREVIEW_STORE_UNAVAILABLE"
            ) from error

        if preview is None:
            raise WebullApprovalError(
                "PREVIEW_NOT_FOUND"
            )

        if preview["status"] != "PREVIEW READY":
            raise WebullApprovalError(
                "PREVIEW_NOT_READY"
            )

        created_at = datetime.fromisoformat(
            str(preview["createdAt"]).replace(
                "Z",
                "+00:00",
            )
        ).astimezone(UTC)

        preview_age_seconds = (
            datetime.now(UTC) - created_at
        ).total_seconds()

        if preview_age_seconds < 0:
            raise WebullApprovalError(
                "PREVIEW_TIMESTAMP_IN_FUTURE"
            )

        if preview_age_seconds > 300:
            raise WebullApprovalError(
                "PREVIEW_EXPIRED"
            )

        proposal = WebullOrderProposal(
            symbol=normalized_symbol,
            side="BUY",
            quantity=int(preview["quantity"]),
            limit_price=float(
                preview["limitPrice"]
            ),
            manually_approved=False,
        )

        stored_exposure = round(
            float(preview["proposedExposure"]),
            2,
        )

        if (
            proposal.proposed_exposure
            != stored_exposure
        ):
            raise WebullApprovalError(
                "PREVIEW_EXPOSURE_MISMATCH"
            )

        if (
            self.webull_approval_queue
            .has_active_duplicate(proposal)
        ):
            raise WebullApprovalError(
                "DUPLICATE_ACTIVE_APPROVAL"
            )

        account = (
            WebullAccountSnapshotClient()
            .get_account_state()
        )

        return self.webull_approval_queue.create(
            proposal=proposal,
            account=account,
        )

    def confirm_webull_approval(
            self,
            *,
            approval_id: str,
            approval_token: str,
    ) -> str:
        """
        Confirm a pending Webull preview approval.

        This method only changes local approval state. It does not
        submit, replace, modify, or cancel any broker order.
        """
        if self.webull_approval_queue is None:
            raise WebullApprovalError(
                "APPROVAL_STORE_UNAVAILABLE"
            )

        normalized_id = approval_id.strip()

        if not normalized_id:
            raise WebullApprovalError(
                "APPROVAL_ID_REQUIRED"
            )

        if not approval_token:
            raise WebullApprovalError(
                "APPROVAL_TOKEN_REQUIRED"
            )

        self.webull_approval_queue.approve(
            approval_id=normalized_id,
            approval_token=approval_token,
        )

        return self.webull_approval_queue.status(
            normalized_id
        )

    def submit_webull_paper_order(
            self,
            *,
            symbol: str,
            approval_id: str,
            approval_token: str,
    ) -> WebullPaperOrderRecord:
        """
        Record a locally simulated Webull paper order from an
        approved preview.

        This method performs no broker submission, replacement,
        modification, or cancellation.
        """
        if self.webull_approval_queue is None:
            raise WebullPaperOrderServiceError(
                "APPROVAL_STORE_UNAVAILABLE"
            )

        service = WebullPaperOrderService(
            approval_queue=self.webull_approval_queue,
        )

        return service.submit_paper_order(
            symbol=symbol,
            approval_id=approval_id,
            approval_token=approval_token,
        )

    @staticmethod
    def _paper_trade_failure_message(
            error: Exception,
    ) -> str:
        """
        Convert LOCAL PAPER risk failures into clear operator
        messages without exposing approval credentials or changing
        any broker-submission behavior.
        """
        reason = str(error).strip()

        messages = {
            "PAPER_INSUFFICIENT_AVAILABLE_CASH": (
                "BLOCKED BY PAPER RISK · insufficient "
                "simulated cash available for this order"
            ),
            "PAPER_DAILY_LOSS_LIMIT_REACHED": (
                "BLOCKED BY PAPER RISK · daily realized-loss "
                "limit has been reached"
            ),
            "PAPER_NO_AVAILABLE_CASH": (
                "BLOCKED BY PAPER RISK · no simulated cash "
                "is available for new orders"
            ),
        }

        if reason in messages:
            return messages[reason]

        if reason.startswith("PAPER_RISK_CHECK_FAILED:"):
            return (
                "BLOCKED BY PAPER RISK · local paper risk "
                "status could not be verified safely"
            )

        return f"LOCAL PAPER trade failed · {reason}"

    def process_webull_paper_confirmations(
            self,
            *,
            preview_results: list[dict],
            input_fn=input,
            date_str: str | None = None,
    ) -> list[WebullPaperOrderRecord]:
        """
        Offer one interactive confirmation for each ready local
        paper preview.

        Approval IDs and one-time tokens remain internal to this
        process. No Webull broker order is submitted.
        """
        submitted_records: list[WebullPaperOrderRecord] = []

        if date_str is None:
            date_str = datetime.now(
                ZoneInfo("America/New_York")
            ).strftime("%Y-%m-%d")

        tracker = getattr(
            self,
            "webull_paper_lifecycle_tracker",
            None,
        )

        portfolio_store = (
            tracker.store
            if tracker is not None
            else None
        )

        for preview in preview_results:
            if preview.get("status") != "PREVIEW READY":
                continue

            symbol = str(
                preview.get("symbol", "")
            ).strip().upper()

            if not symbol:
                continue

            print()
            print(
                f"{symbol}: LOCAL PAPER TRADE READY"
            )
            print(
                f"Shares: {preview['quantity']} · "
                f"Limit: ${preview['limitBuy']:.4f} · "
                f"Exposure: "
                f"${preview['estimatedPositionValue']:.2f} · "
                f"Trading stop: "
                f"${preview['tradingStopLoss']:.4f}"
            )
            print(
                "This records a LOCAL PAPER order only. "
                "No Webull broker order will be submitted."
            )

            try:
                paper_risk = (
                    load_webull_paper_risk_status(
                        date_str=date_str,
                        store=portfolio_store,
                    )
                )
            except Exception as error:
                paper_risk = None
                print(
                    "Paper risk status: UNAVAILABLE · "
                    "the final submission check will still "
                    "fail closed if risk cannot be verified."
                )
            else:
                print(
                    "Paper risk: "
                    f"{'TRADING ALLOWED' if paper_risk.trading_allowed else 'TRADING HALTED'}"
                )
                print(
                    "Available for new orders: "
                    f"${paper_risk.available_for_new_orders:.2f} · "
                    "Pending reserved: "
                    f"${paper_risk.pending_reserved_cash:.2f}"
                )
                print(
                    "Daily realized P&L: "
                    f"${paper_risk.daily_realized_pnl:.2f} · "
                    "Remaining daily loss: "
                    f"${paper_risk.remaining_daily_loss:.2f} "
                    f"of ${paper_risk.max_daily_loss:.2f}"
                )

                if not paper_risk.trading_allowed:
                    print(
                        f"{symbol}: "
                        f"{self._paper_trade_failure_message(
                            RuntimeError(paper_risk.reason)
                        )}"
                    )
                    print(
                        "NO WEBULL BROKER ORDER WAS SUBMITTED"
                    )
                    continue

            try:
                response = input_fn(
                    f"Approve LOCAL PAPER trade for "
                    f"{symbol}? [y/N]: "
                )
            except (EOFError, KeyboardInterrupt):
                print(
                    f"{symbol}: LOCAL PAPER trade declined."
                )
                continue

            if response.strip().lower() not in {
                "y",
                "yes",
            }:
                print(
                    f"{symbol}: LOCAL PAPER trade declined."
                )
                continue

            try:
                ticket = self.request_webull_approval(
                    symbol
                )

                status = self.confirm_webull_approval(
                    approval_id=ticket.approval_id,
                    approval_token=ticket.approval_token,
                )

                if status != "APPROVED":
                    raise WebullApprovalError(
                        "APPROVAL_CONFIRMATION_FAILED"
                    )

                record = self.submit_webull_paper_order(
                    symbol=symbol,
                    approval_id=ticket.approval_id,
                    approval_token=ticket.approval_token,
                )

            except Exception as error:
                print(
                    f"{symbol}: "
                    f"{self._paper_trade_failure_message(error)}"
                )
                print(
                    "NO WEBULL BROKER ORDER WAS SUBMITTED"
                )
                continue

            submitted_records.append(record)

            print()
            print(
                f"{symbol}: PAPER ORDER RECORDED"
            )
            print(
                f"Status: {record.status}"
            )
            print(
                "NO WEBULL BROKER ORDER WAS SUBMITTED"
            )

        return submitted_records

    @staticmethod
    def _notify_manipulation_preview(
            preview: dict,
    ) -> None:
        """
        Show a macOS desktop notification for a newly created
        Manipulation Webull preview.

        Notification failure never interrupts strategy execution.
        """
        if preview.get("status") != "PREVIEW READY":
            return

        symbol = str(
            preview.get("symbol", "")
        )

        quantity = int(
            preview.get("quantity", 0)
        )

        entry = float(
            preview.get("limitBuy", 0)
        )

        target = float(
            preview.get("target", 0)
        )

        trading_stop = float(
            preview.get("tradingStopLoss", 0)
        )

        title = (
            "Manipulation Webull Preview Ready"
        )

        message = (
            f"{symbol} · {quantity} shares · "
            f"Entry ${entry:.4f} · "
            f"Target ${target:.4f} · "
            f"Trading Stop ${trading_stop:.4f}"
        )

        safe_title = (
            title
            .replace("\\", "\\\\")
            .replace('"', '\\"')
        )

        safe_message = (
            message
            .replace("\\", "\\\\")
            .replace('"', '\\"')
        )

        script = (
            'display notification '
            f'"{safe_message}" '
            f'with title "{safe_title}"'
        )

        try:
            subprocess.run(
                [
                    "osascript",
                    "-e",
                    script,
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
        except Exception as error:
            print(
                "WARNING: Manipulation preview "
                f"notification failed: {error}"
            )

    def prepare_webull_previews(
            self,
    ) -> list[dict]:
        """
        Build Webull previews for current INVEST signals.

        This method never submits, places, cancels, or replaces
        an order.
        """
        print()
        print("Preparing Webull order previews...")

        try:
            preview_service = WebullPreviewService()
            preview_results = (
                preview_service.prepare_previews(
                    stocks=self.stocks,
                )
            )

            if not preview_results:
                print(
                    "No Webull previews were generated."
                )

            for preview in preview_results:
                symbol = preview["symbol"]
                status = preview["status"]

                if status == "PREVIEW READY":
                    self._notify_manipulation_preview(
                        preview
                    )

                    print(
                        f"{symbol}: PREVIEW READY · "
                        f"{preview['quantity']} shares · "
                        f"limit ${preview['limitBuy']:.4f} · "
                        f"target ${preview['target']:.4f} · "
                        "trading stop "
                        f"${preview['tradingStopLoss']:.4f} · "
                        "position value "
                        f"${preview['estimatedPositionValue']:.2f} "
                        f"of ${preview['maxPositionValue']:.2f} · "
                        "sizing constraint "
                        f"{preview['sizingConstraint']} · "
                        "estimated cost "
                        f"${preview['estimatedCost']:.2f} · "
                        "fee "
                        f"${preview['estimatedTransactionFee']:.2f} · "
                        "NOT SUBMITTED"
                    )
                else:
                    print(
                        f"{symbol}: PREVIEW FAILED · "
                        f"{preview.get('error', 'Unknown error')}"
                    )

            return preview_results

        except Exception as error:
            print(
                "Webull preview preparation failed. "
                "Strategy results were preserved."
            )
            print(f"Webull preview error: {error}")
            return []

    def publish_current_strategy_results(
            self,
            date_str: str,
            initialise_sheets: bool = True,
            interactive_paper_confirmation: bool = False,
    ) -> None:
        """
        Write current strategy state to Google Sheets and prepare
        non-submitted Webull previews.

        Workbook finalisation is intentionally separate.
        """
        if initialise_sheets:
            self.initialise_sheets()

        if self.sheets is None:
            raise RuntimeError(
                "Google Sheets was not initialised."
            )

        write_errors: list[str] = []

        if ACTIVE_STRATEGY == FIBONACCI_STRATEGY_NAME:
            invest_sheet_name = "Fibonacci Invest"
            orders_sheet_name = "Fibonacci Orders"
        else:
            invest_sheet_name = "Invest"
            orders_sheet_name = "Orders"

        try:
            self.sheets.write_strategy_results(
                date_str=date_str,
                stocks=self.stocks,
                sheet_name=invest_sheet_name,
            )
        except Exception as error:
            write_errors.append(
                f"{invest_sheet_name} sheet: {error}"
            )
            print(
                f"{invest_sheet_name} sheet write failed. "
                f"Error: {error}"
            )

        preview_results = self.prepare_webull_previews()

        if interactive_paper_confirmation:
            self.process_webull_paper_confirmations(
                preview_results=preview_results,
                date_str=date_str,
            )

        try:
            self.sheets.write_orders(
                date_str=date_str,
                stocks=self.stocks,
                sheet_name=orders_sheet_name,
            )
        except Exception as error:
            write_errors.append(
                f"{orders_sheet_name} sheet: {error}"
            )
            print(
                f"{orders_sheet_name} sheet write failed. "
                f"Error: {error}"
            )

        if write_errors:
            raise RuntimeError(
                "One or more strategy writes failed: "
                + " | ".join(write_errors)
            )

        print("Current strategy results written successfully.")

    def finalise_strategy_workbook(
            self,
            date_str: str,
    ) -> None:
        """
        Finalise the daily workbook once after monitoring ends.
        """
        if self.sheets is None:
            raise RuntimeError(
                "Google Sheets was not initialised."
            )

        try:
            paper_report = (
                load_webull_paper_daily_performance(
                    date_str=date_str,
                )
            )

            self.sheets.write_paper_performance(
                report=paper_report,
            )

            print(
                "LOCAL PAPER daily performance written "
                "to Google Sheets."
            )

        except Exception as error:
            print(
                "LOCAL PAPER performance write failed. "
                f"Reason: {error}"
            )

        try:
            analytics_report = (
                load_webull_paper_analytics()
            )

            self.sheets.write_paper_analytics(
                date_str=date_str,
                report=analytics_report,
            )

            print(
                "LOCAL PAPER cumulative analytics written "
                "to Google Sheets."
            )

        except Exception as error:
            print(
                "LOCAL PAPER analytics write failed. "
                f"Reason: {error}"
            )

        try:
            evaluation = (
                load_fibonacci_paper_evaluation()
            )

            self.sheets.write_paper_evaluation(
                date_str=date_str,
                evaluation=evaluation,
            )

            print(
                "FIBONACCI PAPER evaluation written "
                "to Google Sheets."
            )

        except Exception as error:
            print(
                "FIBONACCI PAPER evaluation write failed. "
                f"Reason: {error}"
            )

        try:
            tracker = getattr(
                self,
                "webull_paper_lifecycle_tracker",
                None,
            )

            portfolio_store = (
                tracker.store
                if tracker is not None
                else None
            )

            portfolio = getattr(
                self,
                "_webull_paper_portfolio_snapshot",
                None,
            )

            if portfolio is None:
                portfolio = (
                    load_webull_paper_portfolio(
                        store=portfolio_store,
                    )
                )

            try:
                risk_status = (
                    load_webull_paper_risk_status(
                        date_str=date_str,
                        store=portfolio_store,
                    )
                )
            except Exception as error:
                risk_status = None
                print(
                    "LOCAL PAPER risk status unavailable "
                    "for Google Sheets. "
                    f"Reason: {error}"
                )

            self.sheets.write_paper_portfolio(
                date_str=date_str,
                portfolio=portfolio,
                risk_status=risk_status,
            )

            print(
                "LOCAL PAPER portfolio written "
                "to Google Sheets."
            )

        except Exception as error:
            print(
                "LOCAL PAPER portfolio write failed. "
                f"Reason: {error}"
            )

        try:
            self.sheets.finalise_daily_workbook(
                date_str=date_str,
            )
        except Exception as error:
            print(
                "Google Sheets daily archive finalisation "
                f"failed: {error}"
            )

    def run_strategy_and_write(
            self,
            date_str: str | None = None,
            evaluation_end: datetime | None = None,
            finalise: bool = True,
    ) -> None:
        """
        Compatibility workflow for one strategy evaluation.

        Fibonacci monitoring will call the smaller methods directly
        so repeated evaluation does not repeatedly finalise the
        workbook.
        """
        if date_str is None:
            eastern = ZoneInfo("America/New_York")
            date_str = datetime.now(eastern).strftime(
                "%Y-%m-%d"
            )

        self.evaluate_active_strategy(
            date_str=date_str,
            evaluation_end=evaluation_end,
        )

        self.publish_current_strategy_results(
            date_str=date_str,
        )

        if finalise:
            self.finalise_strategy_workbook(
                date_str=date_str,
            )

    @staticmethod
    def _session_clock(
            date_value,
            clock_value: str,
            timezone,
    ) -> datetime:
        """
        Build one timezone-aware session timestamp from HH:MM.
        """
        parsed = datetime.strptime(
            clock_value,
            "%H:%M",
        ).time()

        return datetime.combine(
            date_value,
            parsed,
            tzinfo=timezone,
        )

    def calculate_live_fibonacci_outcomes(
            self,
            date_str: str,
            outcome_end: datetime,
            data_feed: str = MARKET_DATA_FEED,
    ) -> None:
        """
        Calculate hypothetical Fibonacci outcomes through the
        supplied cutoff.

        This is analysis only. It cannot submit, cancel, or
        replace an order.
        """
        eastern = ZoneInfo("America/New_York")
        utc = ZoneInfo("UTC")

        trading_date = datetime.strptime(
            date_str,
            "%Y-%m-%d",
        ).date()

        outcome_start = datetime.combine(
            trading_date,
            time(hour=9, minute=45),
            tzinfo=eastern,
        ).astimezone(utc)

        normalized_end = outcome_end

        if normalized_end.tzinfo is None:
            normalized_end = normalized_end.replace(
                tzinfo=eastern,
            )

        normalized_end = normalized_end.astimezone(utc)

        invest_symbols = [
            symbol
            for symbol, stock in self.stocks.items()
            if stock.signal == "INVEST"
        ]

        for stock in self.stocks.values():
            stock.outcome = None

        if not invest_symbols:
            print(
                "No INVEST signals require outcome tracking."
            )
            return

        outcome_bars = (
            self.alpaca.get_historical_1min_bars(
                symbols_csv=",".join(invest_symbols),
                start_iso=outcome_start.strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                ),
                end_iso=normalized_end.strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                ),
                feed=data_feed,
            )
        )

        replay = HistoricalReplay(
            stocks=self.stocks,
            strategy=self.strategy,
            speed=0,
        )

        replay.calculate_outcomes(
            bars_by_symbol=outcome_bars,
            close_open_positions=False,
        )

        tracked = sum(
            stock.outcome is not None
            for stock in self.stocks.values()
        )

        print(
            "Hypothetical outcomes calculated for "
            f"{tracked} INVEST signal"
            f"{'' if tracked == 1 else 's'}."
        )
        print("PAPER ANALYSIS ONLY — NOT SUBMITTED")

    def _cached_fibonacci_bars_for_lifecycle(
            self,
            *,
            date_str: str,
            evaluation_end: datetime,
            data_feed: str,
    ) -> dict[str, list[dict]]:
        """
        Return already-fetched Fibonacci bars for local paper
        lifecycle tracking without making another Alpaca request.
        """
        cache = getattr(
            self,
            "_fibonacci_intraday_bar_cache",
            {},
        )

        cache_key = (
            date_str,
            data_feed.strip().lower(),
            self.symbols_csv,
        )

        entry = cache.get(cache_key)

        if not entry:
            return {}

        utc = ZoneInfo("UTC")
        end_iso = evaluation_end.astimezone(
            utc
        ).strftime("%Y-%m-%dT%H:%M:%SZ")

        return {
            symbol: [
                bar
                for bar in entry["bars"].get(
                    symbol,
                    [],
                )
                if str(bar["t"]) < end_iso
            ]
            for symbol in self.stocks
        }

    @staticmethod
    def _print_webull_paper_lifecycle_changes(
            *,
            before: dict,
            changed: list[WebullPaperOrderRecord],
    ) -> None:
        for record in changed:
            previous = before.get(
                record.paper_order_id
            )

            previous_status = (
                previous.lifecycle_status
                if previous is not None
                else None
            )

            if (
                record.lifecycle_status
                == previous_status
            ):
                continue

            print()

            if record.lifecycle_status == "OPEN":
                print(
                    f"{record.symbol}: LOCAL PAPER FILLED"
                )
                print(
                    f"{record.quantity} shares @ "
                    f"${record.fill_price:.4f}"
                )
                continue

            if record.lifecycle_status == "CLOSED":
                print(
                    f"{record.symbol}: LOCAL PAPER CLOSED"
                )
                print(
                    f"Reason: {record.exit_reason}"
                )

                if record.exit_price is None:
                    print(
                        "No simulated entry occurred."
                    )
                    continue

                print(
                    f"Exit: ${record.exit_price:.4f}"
                )
                print(
                    f"P&L: ${record.realized_pnl:+.2f}"
                )
                print(
                    f"Return: {record.return_pct:+.4f}%"
                )
                print(
                    f"MFE: {record.mfe_pct:+.4f}%"
                )
                print(
                    f"MAE: {record.mae_pct:+.4f}%"
                )

    def _refresh_webull_paper_portfolio(
            self,
            *,
            bars_by_symbol: dict[str, list[dict]],
            store,
    ):
        """
        Reconstruct and mark the LOCAL PAPER portfolio using only
        already-cached completed Fibonacci bars.

        No Alpaca request and no Webull broker action occurs here.
        """
        latest_prices = (
            latest_prices_from_completed_bars(
                bars_by_symbol
            )
        )

        portfolio = load_webull_paper_portfolio(
            latest_prices=latest_prices,
            store=store,
        )

        self._webull_paper_portfolio_snapshot = (
            portfolio
        )

        return portfolio

    def _process_webull_paper_lifecycle(
            self,
            *,
            date_str: str,
            evaluation_end: datetime,
            data_feed: str,
    ) -> None:
        tracker = getattr(
            self,
            "webull_paper_lifecycle_tracker",
            None,
        )

        if tracker is None:
            return

        bars = self._cached_fibonacci_bars_for_lifecycle(
            date_str=date_str,
            evaluation_end=evaluation_end,
            data_feed=data_feed,
        )

        if not bars:
            return

        before = tracker.store.load()

        changed = tracker.process_bars(
            bars_by_symbol=bars,
        )

        self._print_webull_paper_lifecycle_changes(
            before=before,
            changed=changed,
        )

        self._refresh_webull_paper_portfolio(
            bars_by_symbol=bars,
            store=tracker.store,
        )

    def _finalize_webull_paper_lifecycle(
            self,
            *,
            date_str: str,
            cutoff: datetime,
            data_feed: str,
    ) -> None:
        tracker = getattr(
            self,
            "webull_paper_lifecycle_tracker",
            None,
        )

        if tracker is None:
            return

        bars = self._cached_fibonacci_bars_for_lifecycle(
            date_str=date_str,
            evaluation_end=cutoff,
            data_feed=data_feed,
        )

        before = tracker.store.load()

        tracker.finalize_at_cutoff(
            cutoff=cutoff,
            bars_by_symbol=bars,
        )

        after = tracker.store.load()

        changed = [
            record
            for paper_order_id, record
            in after.items()
            if record != before.get(paper_order_id)
        ]

        self._print_webull_paper_lifecycle_changes(
            before=before,
            changed=changed,
        )

        self._refresh_webull_paper_portfolio(
            bars_by_symbol=bars,
            store=tracker.store,
        )

    def run_fibonacci_monitor(
            self,
            date_str: str,
            write_sheets: bool = True,
            publish_dashboard: bool = True,
            now_fn=None,
            sleep_fn=None,
    ) -> None:
        """
        Monitor the active Fibonacci strategy using only completed
        one-minute bars.

        External outputs are refreshed only when the INVEST signal
        signature changes. The workbook is finalised once when the
        monitoring window ends.

        No order is submitted.
        """
        if ACTIVE_STRATEGY != FIBONACCI_STRATEGY_NAME:
            raise RuntimeError(
                "Fibonacci monitoring requires "
                "ACTIVE_STRATEGY=FIBONACCI_61_8."
            )

        eastern = ZoneInfo("America/New_York")
        now_fn = now_fn or (
            lambda: datetime.now(eastern)
        )
        sleep_fn = sleep_fn or time_module.sleep

        trading_date = datetime.strptime(
            date_str,
            "%Y-%m-%d",
        ).date()

        monitor_start = self._session_clock(
            trading_date,
            FIBONACCI_MONITOR_START,
            eastern,
        )
        monitor_cutoff = self._session_clock(
            trading_date,
            FIBONACCI_MONITOR_CUTOFF,
            eastern,
        )

        print()
        print("===================================")
        print(" Fibonacci Live Monitor")
        print("===================================")
        print(f"Trading date: {date_str}")
        print(
            "Monitoring window:",
            FIBONACCI_MONITOR_START,
            "to",
            FIBONACCI_MONITOR_CUTOFF,
            "New York time",
        )
        print("PAPER/PREVIEW ONLY — NOT SUBMITTED")

        now = now_fn()

        if now < monitor_start:
            wait_seconds = (
                monitor_start - now
            ).total_seconds()

            print(
                "Waiting for Fibonacci monitoring to begin "
                f"at {FIBONACCI_MONITOR_START} ET..."
            )
            sleep_fn(wait_seconds)
            now = now_fn()

        if now >= monitor_cutoff:
            print(
                "Fibonacci monitoring cutoff has already passed."
            )
            return

        last_signature = None
        previous_poll_time = None

        while True:
            now = now_fn()

            if previous_poll_time is not None:
                elapsed_seconds = (
                    now - previous_poll_time
                ).total_seconds()

                expected_seconds = (
                    FIBONACCI_MONITOR_INTERVAL_SECONDS
                )

                if elapsed_seconds > max(
                    expected_seconds * 2,
                    120,
                ):
                    print(
                        "WARNING: Fibonacci monitoring resumed "
                        f"after a {elapsed_seconds:.0f}-second gap. "
                        "The process may have been suspended or "
                        "the computer may have slept. Catching up "
                        "using the latest completed minute."
                    )

            previous_poll_time = now

            if now >= monitor_cutoff:
                break

            # Alpaca's end timestamp acts as the completed-bar
            # boundary. Seconds and microseconds are removed so
            # the currently forming minute is never evaluated.
            evaluation_end = now.replace(
                second=0,
                microsecond=0,
            )

            cycle_started = time_module.perf_counter()
            self._fibonacci_performance_metrics = {}

            evaluation_started = time_module.perf_counter()

            try:
                self.evaluate_active_strategy(
                    date_str=date_str,
                    evaluation_end=evaluation_end,
                    data_feed=MARKET_DATA_FEED,
                )
            except Exception as error:
                print(
                    "WARNING: Fibonacci evaluation failed for "
                    f"{evaluation_end.strftime('%H:%M:%S')}: "
                    f"{error}. Skipping this evaluation and "
                    "continuing the live monitor."
                )

                sleep_fn(
                    FIBONACCI_MONITOR_INTERVAL_SECONDS
                )
                continue

            self._set_fibonacci_performance_metric(
                "strategy_evaluation_seconds",
                time_module.perf_counter()
                - evaluation_started,
            )

            signature = self.current_signal_signature()

            sheets_preview_seconds = None
            dashboard_seconds = None

            if signature != last_signature:
                print(
                    "Active Fibonacci signal state changed."
                )

                if write_sheets:
                    sheets_preview_started = (
                        time_module.perf_counter()
                    )

                    self.publish_current_strategy_results(
                        date_str=date_str,
                        initialise_sheets=False,
                        interactive_paper_confirmation=True,
                    )

                    sheets_preview_seconds = (
                        time_module.perf_counter()
                        - sheets_preview_started
                    )
                else:
                    print(
                        "DRY-RUN MODE: Sheets and Webull "
                        "preview publishing skipped."
                    )

                if publish_dashboard:
                    dashboard_started = (
                        time_module.perf_counter()
                    )

                    processed_bars = {
                        symbol: (
                            stock.green_minutes
                            + stock.red_minutes
                        )
                        for symbol, stock in self.stocks.items()
                    }

                    self._publish_dashboard_session(
                        date_str=date_str,
                        source="LIVE_FIBONACCI",
                        processed_bars=processed_bars,
                        data_feed=MARKET_DATA_FEED,
                    )

                    dashboard_seconds = (
                        time_module.perf_counter()
                        - dashboard_started
                    )
                else:
                    print(
                        "DRY-RUN MODE: Cloudflare dashboard "
                        "publishing skipped."
                    )

                last_signature = signature
            else:
                print(
                    "No Fibonacci signal change. "
                    "External outputs were not rewritten."
                )

            try:
                self._process_webull_paper_lifecycle(
                    date_str=date_str,
                    evaluation_end=evaluation_end,
                    data_feed=MARKET_DATA_FEED,
                )
            except Exception as error:
                # Lifecycle tracking must never terminate the
                # strategy monitor or turn missing market data
                # into a simulated fill/exit.
                print(
                    "WARNING: LOCAL PAPER lifecycle update "
                    f"failed: {error}. "
                    "Fibonacci monitoring will continue."
                )

            self._print_fibonacci_cycle_performance(
                total_seconds=(
                    time_module.perf_counter()
                    - cycle_started
                ),
                sheets_preview_seconds=(
                    sheets_preview_seconds
                ),
                dashboard_seconds=dashboard_seconds,
            )

            sleep_fn(
                FIBONACCI_MONITOR_INTERVAL_SECONDS
            )

        print()
        print("Running final Fibonacci evaluation...")

        self.evaluate_active_strategy(
            date_str=date_str,
            evaluation_end=monitor_cutoff,
            data_feed=MARKET_DATA_FEED,
        )

        final_signature = self.current_signal_signature()

        if final_signature != last_signature and write_sheets:
            self.publish_current_strategy_results(
                date_str=date_str,
                initialise_sheets=False,
                interactive_paper_confirmation=True,
            )

        try:
            self._finalize_webull_paper_lifecycle(
                date_str=date_str,
                cutoff=monitor_cutoff,
                data_feed=MARKET_DATA_FEED,
            )
        except Exception as error:
            print(
                "WARNING: LOCAL PAPER cutoff finalization "
                f"failed: {error}. "
                "No broker action was attempted."
            )

        print()
        print("Calculating hypothetical outcomes through cutoff...")

        self.calculate_live_fibonacci_outcomes(
            date_str=date_str,
            outcome_end=monitor_cutoff,
            data_feed=MARKET_DATA_FEED,
        )

        if publish_dashboard:
            processed_bars = {
                symbol: (
                    stock.green_minutes
                    + stock.red_minutes
                )
                for symbol, stock in self.stocks.items()
            }

            self._publish_dashboard_session(
                date_str=date_str,
                source="LIVE_FIBONACCI_FINAL",
                processed_bars=processed_bars,
                data_feed=MARKET_DATA_FEED,
            )
        else:
            print(
                "DRY-RUN MODE: Final Cloudflare dashboard "
                "publishing skipped."
            )

        if write_sheets:
            self.finalise_strategy_workbook(
                date_str=date_str,
            )

        print("Fibonacci monitoring completed.")
        print("No real orders were submitted.")

    def run_production(self) -> None:
        eastern = ZoneInfo("America/New_York")
        now = datetime.now(eastern)

        date_str = now.strftime("%Y-%m-%d")

        if now.weekday() >= 5:
            print()
            print("The market is closed today.")
            print("Production mode was not started.")
            return

        market_open = datetime.combine(
            now.date(),
            time(hour=9, minute=30),
            tzinfo=eastern,
        )

        strategy_time = datetime.combine(
            now.date(),
            time(hour=9, minute=45),
            tzinfo=eastern,
        ) + timedelta(seconds=15)

        production_cutoff = datetime.combine(
            now.date(),
            (
                time(hour=11)
                if ACTIVE_STRATEGY
                == FIBONACCI_STRATEGY_NAME
                else time(hour=10)
            ),
            tzinfo=eastern,
        )

        print()
        print("===================================")
        print(" Production Trading Mode")
        print("===================================")
        print(f"Trading date: {date_str}")

        if now >= production_cutoff:
            print()
            print(
                "The 10:00 New York production cutoff "
                "has passed."
            )
            print(
                "Tracking, strategy calculation, and "
                "spreadsheet writes were not started."
            )
            return

        if now < market_open:
            wait_seconds = (
                    market_open - now
            ).total_seconds()

            print(
                "Waiting for market open at "
                "09:30 New York time..."
            )

            time_module.sleep(wait_seconds)

        elif now >= strategy_time:
            print()
            print("The opening tracking window has ended.")
            print("Skipping the opening tracker.")

            if ACTIVE_STRATEGY == FIBONACCI_STRATEGY_NAME:
                print(
                    "Starting Fibonacci monitoring from "
                    "the current completed minute..."
                )

                self.refresh_symbols_for_date(date_str)
                self.initialise_sheets()

                self.run_fibonacci_monitor(
                    date_str=date_str,
                    write_sheets=True,
                    publish_dashboard=True,
                )
            else:
                print(
                    "Running the preserved manipulation "
                    "strategy immediately..."
                )

                self.run_strategy_and_write(
                    date_str=date_str
                )

            print()
            print("Production workflow completed.")
            return

        else:
            print()
            print("The opening window has already started.")
            print("Starting the tracker now...")

        self.run_live_tracker()

        print()
        print("Production workflow completed.")
