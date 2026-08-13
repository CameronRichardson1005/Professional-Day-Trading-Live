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
from .webull_strategy_market_data import (
    WebullStrategyMarketData,
)
from .quick_flip_webull_preview_service import (
    QuickFlipWebullPreviewService,
)
from .quick_flip_monitor import (
    QuickFlipMonitor,
    reconcile_minute_bars,
)
from .quick_flip_strategy import QuickFlipCandle

from .config import (
    CANDIDATE_TICKERS,
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
from .webull_paper_portfolio import (
    latest_prices_from_completed_bars,
    load_webull_paper_portfolio,
)
from .webull_paper_risk import (
    load_webull_paper_risk_status,
)
from .scanner import StockScanner
from .sheets_client import SheetsClient
from .strategy import ManipulationStrategy


class TradingBot:
    def __init__(self) -> None:
        self.stocks = {
            symbol: Stock(symbol=symbol)
            for symbol in TICKERS
        }

        self.symbols_csv = ",".join(self.stocks.keys())

        self.alpaca = AlpacaClient()

        # Lazily initialized read-only Webull market-data
        # adapter for live Manipulation and Quick Flip.
        #
        # Keeping initialization lazy prevents ordinary
        # TradingBot construction and unit tests from
        # authenticating against Webull.
        self.webull_strategy_market_data = None

        # Active live Manipulation strategy.
        self.strategy = ManipulationStrategy()

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

        # Forward research only. These variants never replace
        # Manipulation signal, entry, target, stop, or preview.
        self.manipulation_selling_pressure_shadows = {}

        # Legacy workbook used by the existing tracker and
        # historical workflow.
        self.sheets = None

        # Separate clean workbook for Manipulation + Quick Flip.
        # This never replaces self.sheets.
        self.trading_sheets = None

        self.dashboard = DashboardExporter()

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

    def _get_webull_strategy_market_data(
            self,
    ) -> WebullStrategyMarketData:
        """
        Lazily construct the read-only Webull market-data
        adapter used by live Manipulation and Quick Flip.

        This method exposes no order functionality.
        """
        existing = getattr(
            self,
            "webull_strategy_market_data",
            None,
        )

        if existing is not None:
            return existing

        import logging

        from webull.core.client import ApiClient
        from webull.data.data_client import DataClient

        from .config import (
            WEBULL_APP_KEY,
            WEBULL_APP_SECRET,
        )

        if not WEBULL_APP_KEY:
            raise RuntimeError(
                "WEBULL_APP_KEY is not configured."
            )

        if not WEBULL_APP_SECRET:
            raise RuntimeError(
                "WEBULL_APP_SECRET is not configured."
            )

        # Suppress Webull SDK token metadata logging.
        logging.disable(
            logging.CRITICAL
        )

        try:
            api_client = ApiClient(
                WEBULL_APP_KEY,
                WEBULL_APP_SECRET,
                "us",
            )

            api_client.add_endpoint(
                "us",
                "api.webull.com",
            )

            data_client = DataClient(
                api_client
            )

        finally:
            logging.disable(
                logging.NOTSET
            )

        self.webull_strategy_market_data = (
            WebullStrategyMarketData(
                market_data=(
                    data_client.market_data
                ),
            )
        )

        return (
            self.webull_strategy_market_data
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

    def build_manipulation_selling_pressure_shadows(
            self,
            date_str: str,
            data_feed: str = MARKET_DATA_FEED,
    ) -> dict:
        """
        Build forward research-only selling-pressure variants.

        Live Manipulation Stock values are never modified.
        """
        from datetime import datetime, timedelta

        from .manipulation_selling_pressure_runner import (
            prior_opening_average,
        )
        from .manipulation_selling_pressure_shadow import (
            build_selling_pressure_shadow,
        )

        current_day = datetime.strptime(
            date_str,
            "%Y-%m-%d",
        )

        history_start = (
            current_day - timedelta(days=60)
        ).strftime("%Y-%m-%d")

        symbols = [
            stock.symbol
            for stock in self.stocks.values()
            if (
                stock.signal == "INVEST"
                and isinstance(
                    stock.opening_bar,
                    dict,
                )
            )
        ]

        if not symbols:
            self.manipulation_selling_pressure_shadows = {}
            return {}

        historical = (
            self.alpaca.get_historical_opening_15min_bars(
                symbols_csv=",".join(symbols),
                start_date=history_start,
                end_date=date_str,
                feed=data_feed,
            )
        )

        shadows = {}

        for symbol in symbols:
            stock = self.stocks[symbol]

            average_volume = prior_opening_average(
                opening_bars=historical.get(
                    symbol,
                    [],
                ),
                current_date=date_str,
            )

            if average_volume is None:
                continue

            shadow = build_selling_pressure_shadow(
                stock=stock,
                average_opening_volume=average_volume,
            )

            if shadow is not None:
                shadows[symbol] = shadow

        self.manipulation_selling_pressure_shadows = shadows

        return shadows


    def write_manipulation_selling_pressure_research(
            self,
            date_str: str,
    ) -> None:
        """
        Write forward selling-pressure shadow setups into the
        standalone research workbook only.
        """
        self.initialise_trading_sheets()

        if self.trading_sheets is None:
            raise RuntimeError(
                "New trading workbook was not initialised."
            )

        self.trading_sheets.\
            write_manipulation_selling_pressure_research(
                date_str=date_str,
                shadows=getattr(
                    self,
                    "manipulation_selling_pressure_shadows",
                    {},
                ),
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
            "Checking Google Sheets "
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
                "initialisation."
            )
            print(f"Preflight error: {error}")
            return False

        required_worksheets = {
            "Scanner Dashboard",
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

        print("Google Sheets check passed.")
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
        print(
            "Native-timeframe live mode enabled."
        )

        opening_close_eastern = datetime.combine(
            today_eastern,
            time(hour=9, minute=45),
            tzinfo=eastern,
        )

        now_eastern = datetime.now(eastern)

        if now_eastern < opening_close_eastern:
            wait_seconds = (
                opening_close_eastern
                - now_eastern
            ).total_seconds()

            print(
                "Waiting for the 09:30-09:45 "
                "opening candle to close..."
            )

            Event().wait(
                wait_seconds
            )

        print(
            "Opening window complete."
        )
        print(
            "Manipulation will use Alpaca "
            "native 15Min bars."
        )

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

        try:
            shadows = (
                self.build_manipulation_selling_pressure_shadows(
                    date_str=date_str,
                    data_feed=MARKET_DATA_FEED,
                )
            )

            if shadows:
                print(
                    "Selling-pressure shadow trigger(s): "
                    + ", ".join(
                        sorted(shadows)
                    )
                )
            else:
                print(
                    "No selling-pressure shadow triggers "
                    "for this session."
                )

        except Exception as error:
            self.manipulation_selling_pressure_shadows = {}

            print(
                "WARNING: Selling-pressure research "
                "calculation failed. "
                "Live Manipulation remains unchanged."
            )
            print(
                f"Selling-pressure research error: {error}"
            )

        if write_sheets:
            try:
                self.write_new_manipulation_results(
                    date_str=date_str,
                )

                self.write_manipulation_selling_pressure_research(
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

        processed_bars = {
            symbol: (
                15
                if getattr(
                    stock,
                    "opening_bar",
                    None,
                ) is not None
                else 0
            )
            for symbol, stock
            in self.stocks.items()
        }

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
                stream_factory=None,
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


    @staticmethod
    def _quick_flip_signal_key(
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

    @staticmethod
    def _notify_quick_flip_preview(
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


    def _merge_quick_flip_stream_snapshot(
            self,
            *,
            stream,
            intraday_bars: dict,
    ) -> None:
        """
        Merge the latest WebSocket representation first.

        REST reconciliation is deliberately applied afterward,
        so REST remains authoritative when both sources contain
        the same completed minute.
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

    def _evaluate_quick_flip_current_state(
            self,
            *,
            opening_bars: dict,
            atrs: dict,
            intraday_bars: dict,
            evaluation_end: datetime,
            cutoff_reached: bool,
            utc,
    ) -> None:
        self.quick_flip_results = {}
        self.quick_flip_status = {}

        evaluation_end_utc = (
            evaluation_end.astimezone(utc)
        )

        for symbol in self.stocks:
            opening_bar = opening_bars.get(symbol)
            atr_14 = atrs.get(symbol)

            if opening_bar is None:
                self.quick_flip_results[symbol] = None
                self.quick_flip_status[
                    symbol
                ] = "MISSING_OPENING_BAR"
                continue

            if atr_14 is None:
                self.quick_flip_results[symbol] = None
                self.quick_flip_status[
                    symbol
                ] = "MISSING_ATR14"
                continue

            try:
                native_candles = []

                for bar in intraday_bars[symbol]:
                    candle = (
                        self._quick_flip_candle_from_bar(
                            bar
                        )
                    )

                    # Webull timestamps native 5Min bars
                    # at the start of their interval.
                    # Evaluate only after all five minutes
                    # have completed.
                    if (
                        candle.timestamp
                        + timedelta(minutes=5)
                        <= evaluation_end_utc
                    ):
                        native_candles.append(candle)

                result = (
                    self.quick_flip_monitor
                    .evaluate_five_minute_candles(
                        symbol=symbol,
                        opening_bar=(
                            self._quick_flip_candle_from_bar(
                                opening_bar
                            )
                        ),
                        atr_14=float(atr_14),
                        candles=native_candles,
                        cutoff_reached=cutoff_reached,
                    )
                )

                self.quick_flip_results[symbol] = result
                self.quick_flip_status[
                    symbol
                ] = result.status

            except Exception as error:
                self.quick_flip_results[symbol] = None
                self.quick_flip_status[
                    symbol
                ] = "EVALUATION_FAILED"

                print(
                    f"{symbol}: Quick Flip "
                    f"evaluation failed: {error}"
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
        # Quick Flip uses Webull native 5Min REST bars.
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

        market_data = (
            self._get_webull_strategy_market_data()
        )

        opening_bars = (
            market_data.get_opening_15min_bars(
                symbols_csv=self.symbols_csv,
                date_str=date_str,
            )
        )

        atrs = (
            market_data.get_previous_day_ranges_all(
                symbols_csv=self.symbols_csv,
                date_str=date_str,
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
                        "quick-flip-market-data-stream"
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
                    self._quick_flip_signal_key(
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

                    self._notify_quick_flip_preview(
                        preview
                    )
                else:
                    print(
                        f"{symbol}: QUICK FLIP "
                        "WEBULL PREVIEW FAILED · "
                        f"{preview.get('error', 'Unknown error')}"
                    )

            return previews

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
            self._merge_quick_flip_stream_snapshot(
                stream=stream,
                intraday_bars=intraday_bars,
            )

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
                        market_data
                        .get_historical_5min_bars(
                            symbols_csv=self.symbols_csv,
                            start_iso=start_utc.strftime(
                                "%Y-%m-%dT%H:%M:%SZ"
                            ),
                            end_iso=end_utc.strftime(
                                "%Y-%m-%dT%H:%M:%SZ"
                            ),
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

            self._evaluate_quick_flip_current_state(
                opening_bars=opening_bars,
                atrs=atrs,
                intraday_bars=intraday_bars,
                evaluation_end=evaluation_end,
                cutoff_reached=False,
                utc=utc,
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
        self._merge_quick_flip_stream_snapshot(
            stream=stream,
            intraday_bars=intraday_bars,
        )

        # --------------------------------------------
        # Final 11:00 evaluation.
        # --------------------------------------------
        if fetch_start < monitor_cutoff:
            try:
                final_fetch = (
                    market_data
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

        self._evaluate_quick_flip_current_state(
            opening_bars=opening_bars,
            atrs=atrs,
            intraday_bars=intraday_bars,
            evaluation_end=monitor_cutoff,
            cutoff_reached=True,
            utc=utc,
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
        live standalone dashboard sessions.

        This is reconstructed simulation state only and never
        represents broker balances or broker-submitted positions.
        """
        if source.upper() != "LIVE_MANIPULATION":
            return None

        try:
            portfolio_store = None

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
        Return completed LOCAL PAPER performance for the live
        standalone dashboard session.

        Ledger failures never interrupt trading or dashboard
        publishing.
        """
        if source.upper() != "LIVE_MANIPULATION":
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
        Return cumulative LOCAL PAPER analytics for the live
        standalone dashboard session.

        Ledger failures are nonfatal and never affect strategy or
        order-processing behavior.
        """
        if source.upper() != "LIVE_MANIPULATION":
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

    def _calculate_manipulation_strategy(
            self,
            date_str: str,
    ) -> None:
        """
        Calculate the standalone live Manipulation strategy from
        Webull's 15-minute opening candle and daily ATR history.
        """
        market_data = (
            self._get_webull_strategy_market_data()
        )

        opening_bars = (
            market_data.get_opening_15min_bars(
                symbols_csv=self.symbols_csv,
                date_str=date_str,
            )
        )

        atrs = (
            market_data.get_previous_day_ranges_all(
                symbols_csv=self.symbols_csv,
                date_str=date_str,
            )
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
        Convert one normalized OHLC bar into the immutable candle
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

        market_data = (
            self._get_webull_strategy_market_data()
        )

        opening_bars = (
            market_data.get_opening_15min_bars(
                symbols_csv=self.symbols_csv,
                date_str=date_str,
            )
        )

        atrs = (
            market_data.get_previous_day_ranges_all(
                symbols_csv=self.symbols_csv,
                date_str=date_str,
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

            market_data = (
                self._get_webull_strategy_market_data()
            )

            bars_by_symbol = (
                market_data
                .get_historical_1min_bars(
                    symbols_csv=self.symbols_csv,
                    start_iso=start_utc.strftime(
                        "%Y-%m-%dT%H:%M:%SZ"
                    ),
                    end_iso=end_utc.strftime(
                        "%Y-%m-%dT%H:%M:%SZ"
                    ),
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

    def calculate_strategy(
            self,
            date_str: str,
            evaluation_end: datetime | None = None,
            data_feed: str = MARKET_DATA_FEED,
    ) -> None:
        """
        Calculate the standalone live Manipulation strategy.

        evaluation_end and data_feed remain in the signature for
        compatibility with existing callers.
        """
        self._calculate_manipulation_strategy(
            date_str=date_str,
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
        Create a stable representation of current INVEST signals
        for duplicate-suppression and preview handling.
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

        portfolio_store = None

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
            portfolio_store = None

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
        Run one standalone Manipulation strategy evaluation,
        publish its results, and optionally finalise the workbook.
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


    def _run_production_eod_pnl(
            self,
            date_str: str,
            eastern,
    ) -> None:
        """
        Wait until 16:05 New York time and reconcile the day's
        realized Webull P&L into Google Sheets.

        READ ONLY with respect to Webull broker activity.
        """
        now = datetime.now(eastern)

        eod_pnl_time = datetime.combine(
            now.date(),
            time(hour=16, minute=5),
            tzinfo=eastern,
        )

        if now < eod_pnl_time:
            wait_seconds = (
                eod_pnl_time - now
            ).total_seconds()

            print()
            print(
                "Morning strategy workflow complete."
            )
            print(
                "Waiting until 16:05 New York time "
                "for the end-of-day P&L update..."
            )

            time_module.sleep(wait_seconds)

        print()
        print(
            "Running read-only end-of-day Webull P&L "
            "reconciliation..."
        )

        try:
            self.write_webull_daily_pnl(
                date_str=date_str,
            )
        except Exception as error:
            print(
                "WARNING: End-of-day Webull P&L "
                "update failed."
            )
            print(
                f"End-of-day P&L error: {error}"
            )
            return

        print(
            "End-of-day Google Sheets P&L "
            "update completed."
        )


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
            time(hour=11),
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
                "The 11:00 New York strategy cutoff "
                "has passed."
            )
            print(
                "Morning trading workflow will not "
                "be started."
            )

            self._run_production_eod_pnl(
                date_str=date_str,
                eastern=eastern,
            )

            print()
            print("Production workflow completed.")
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
            print(
                "The opening tracking window has ended."
            )
            print("Skipping the opening tracker.")

            print(
                "Running Manipulation strategy "
                "immediately..."
            )

            self.run_strategy_and_write(
                date_str=date_str
            )

            self._run_production_eod_pnl(
                date_str=date_str,
                eastern=eastern,
            )

            print()
            print("Production workflow completed.")
            return

        else:
            print()
            print(
                "The opening window has already started."
            )
            print("Starting the tracker now...")

        self.run_live_tracker()

        self._run_production_eod_pnl(
            date_str=date_str,
            eastern=eastern,
        )

        print()
        print("Production workflow completed.")
