import getpass
import logging
import sys
from datetime import date

from trading_bot.bot import TradingBot
from trading_bot.market_calendar import nyse_trading_dates
from trading_bot.webull_sandbox_runtime import build_webull_sandbox_preflight
from trading_bot.utils import setup_logging


AVAILABLE_MODES = (
    "market-day",
    "backfill",
    "scanner-research",
    "scanner-realized-research",
    "test",
    "smoke",
    "preflight",
    "live",
    "live-dry-run",
    "webull-approval-request",
    "webull-approval-confirm",
    "webull-paper-submit",
    "webull-sandbox-preflight",
    "webull-pnl",
    "production",
)


def print_available_modes() -> None:
    print(
        "Available modes: "
        + ", ".join(AVAILABLE_MODES)
    )


def main() -> int:
    log_path = setup_logging()

    print(f"Log file: {log_path}")

    mode = (
        sys.argv[1].lower()
        if len(sys.argv) > 1
        else "test"
    )

    try:
        # -----------------------------------------
        # Market-calendar utility
        # -----------------------------------------
        if mode == "market-day":
            if len(sys.argv) > 3:
                print(
                    "Usage: python main.py market-day "
                    "[YYYY-MM-DD]"
                )
                return 2

            try:
                check_date = (
                    date.fromisoformat(sys.argv[2])
                    if len(sys.argv) == 3
                    else date.today()
                )
            except ValueError:
                print(
                    "Market date must use YYYY-MM-DD."
                )
                return 1

            trading_dates = nyse_trading_dates(
                check_date,
                check_date,
            )

            if trading_dates:
                print(
                    "NYSE is scheduled to trade on "
                    f"{check_date.isoformat()}."
                )
                return 0

            print(
                "NYSE is closed on "
                f"{check_date.isoformat()}."
            )
            return 2

        # -----------------------------------------
        # Read-only Webull sandbox execution preflight
        #
        # This command cannot place, modify, or cancel orders.
        # -----------------------------------------
        if mode == "webull-sandbox-preflight":
            if len(sys.argv) != 2:
                print(
                    "Usage: python main.py "
                    "webull-sandbox-preflight"
                )
                return 2

            try:
                preflight = (
                    build_webull_sandbox_preflight()
                )

                report = preflight.run()

            except Exception as error:
                print()
                print(
                    "WEBULL SANDBOX PREFLIGHT FAILED"
                )
                print(
                    "--------------------------------"
                )
                print(f"Reason: {error}")
                print(
                    "NO WEBULL ORDER WAS PLACED, "
                    "MODIFIED, OR CANCELLED"
                )
                return 1

            print()
            print(
                "WEBULL SANDBOX PREFLIGHT PASSED"
            )
            print(
                "--------------------------------"
            )
            print(
                f"Account: {report.account_id}"
            )
            print(
                "Available cash: "
                f"${report.available_cash:.2f}"
            )
            print(
                "Current exposure: "
                f"${report.current_exposure:.2f}"
            )
            print(
                "Open orders: "
                f"{report.open_orders}"
            )
            print(
                "Orders reconciled: "
                f"{report.reconciled_orders}"
            )
            print(
                "Active manual overrides: "
                f"{report.active_manual_overrides}"
            )
            print(
                f"Status: {report.reason}"
            )
            print(
                "READ-ONLY — NO WEBULL ORDER "
                "WAS PLACED, MODIFIED, OR CANCELLED"
            )

            return 0

        bot = TradingBot()

        # -----------------------------------------
        # Local connection / validation modes
        # -----------------------------------------
        if mode == "scanner-research":
            if len(sys.argv) != 4:
                print(
                    "Usage: python main.py "
                    "scanner-research "
                    "START_DATE END_DATE"
                )
                return 2

            bot.run_scanner_research(
                sys.argv[2],
                sys.argv[3],
            )

        elif mode == "scanner-realized-research":
            if len(sys.argv) != 4:
                print(
                    "Usage: python main.py "
                    "scanner-realized-research "
                    "START_DATE END_DATE"
                )
                return 2

            bot.run_scanner_realized_research(
                sys.argv[2],
                sys.argv[3],
            )

        elif mode == "test":
            bot.run()

        elif mode == "smoke":
            if len(sys.argv) > 3:
                print(
                    "Usage: python main.py smoke "
                    "[YYYY-MM-DD]"
                )
                return 2

            date_str = (
                sys.argv[2]
                if len(sys.argv) == 3
                else None
            )

            succeeded = bot.run_scanner_smoke(
                date_str=date_str
            )

            if not succeeded:
                return 1

        elif mode == "preflight":
            if len(sys.argv) > 3:
                print(
                    "Usage: python main.py preflight "
                    "[YYYY-MM-DD]"
                )
                return 2

            date_str = (
                sys.argv[2]
                if len(sys.argv) == 3
                else None
            )

            succeeded = bot.run_preflight(
                date_str=date_str
            )

            if not succeeded:
                return 1

        # -----------------------------------------
        # Native-timeframe live workflow
        #
        # Manipulation:
        #   Webull native 15Min opening candle
        #
        # Quick Flip:
        #   Webull native 15Min opening box
        #   Webull native completed 5Min candles
        # -----------------------------------------
        elif mode == "live":
            if len(sys.argv) != 2:
                print(
                    "Usage: python main.py live"
                )
                return 2

            bot.run_live_tracker()

        elif mode == "live-dry-run":
            if len(sys.argv) != 2:
                print(
                    "Usage: python main.py "
                    "live-dry-run"
                )
                return 2

            bot.run_live_tracker(
                write_sheets=False,
                publish_dashboard=False,
            )

        # -----------------------------------------
        # Webull preview approval
        #
        # These commands cannot submit a real
        # Webull broker order.
        # -----------------------------------------
        elif mode == "webull-approval-request":
            if len(sys.argv) != 3:
                print(
                    "Usage: python main.py "
                    "webull-approval-request SYMBOL"
                )
                return 2

            try:
                ticket = (
                    bot.request_webull_approval(
                        sys.argv[2]
                    )
                )
            except Exception as error:
                print(
                    "Webull approval request rejected: "
                    f"{error}"
                )
                return 1

            # Deliberately bypass normal logging so
            # the one-time token is shown only in
            # the local terminal.
            sys.__stdout__.write(
                "\nWEBULL PREVIEW APPROVAL CREATED\n"
                "--------------------------------\n"
                f"Symbol: {ticket.symbol}\n"
                f"Quantity: {ticket.quantity}\n"
                "Limit price: "
                f"${ticket.limit_price:.4f}\n"
                "Proposed exposure: "
                f"${ticket.proposed_exposure:.2f}\n"
                "Expires: "
                f"{ticket.expires_at.isoformat()}\n"
                "Approval ID: "
                f"{ticket.approval_id}\n"
                "One-time approval token:\n"
                f"{ticket.approval_token}\n"
                "\nNOT SUBMITTED — "
                "KILL SWITCH ACTIVE\n"
            )
            sys.__stdout__.flush()

        elif mode == "webull-approval-confirm":
            if len(sys.argv) != 3:
                print(
                    "Usage: python main.py "
                    "webull-approval-confirm "
                    "APPROVAL_ID"
                )
                return 2

            approval_token = getpass.getpass(
                "One-time approval token: "
            )

            try:
                status = (
                    bot.confirm_webull_approval(
                        approval_id=sys.argv[2],
                        approval_token=(
                            approval_token
                        ),
                    )
                )
            except Exception as error:
                print(
                    "Webull approval confirmation "
                    f"rejected: {error}"
                )
                return 1

            print()
            print("WEBULL APPROVAL CONFIRMED")
            print("--------------------------------")
            print(f"Status: {status}")
            print(
                "NO WEBULL BROKER ORDER "
                "WAS SUBMITTED"
            )

        # -----------------------------------------
        # Local paper ledger only
        # -----------------------------------------
        elif mode == "webull-paper-submit":
            if len(sys.argv) != 4:
                print(
                    "Usage: python main.py "
                    "webull-paper-submit "
                    "SYMBOL APPROVAL_ID"
                )
                return 2

            approval_token = getpass.getpass(
                "One-time approval token: "
            )

            try:
                paper_order = (
                    bot.submit_webull_paper_order(
                        symbol=sys.argv[2],
                        approval_id=sys.argv[3],
                        approval_token=(
                            approval_token
                        ),
                    )
                )
            except Exception as error:
                print(
                    "Webull paper submission "
                    f"rejected: {error}"
                )
                return 1

            print()
            print("WEBULL PAPER ORDER RECORDED")
            print("--------------------------------")
            print(
                "Paper order ID: "
                f"{paper_order.paper_order_id}"
            )
            print(
                f"Symbol: {paper_order.symbol}"
            )
            print(
                f"Side: {paper_order.side}"
            )
            print(
                f"Quantity: {paper_order.quantity}"
            )
            print(
                "Limit price: "
                f"${paper_order.limit_price:.4f}"
            )
            print(
                "Proposed exposure: "
                f"${paper_order.proposed_exposure:.2f}"
            )
            print(
                f"Status: {paper_order.status}"
            )
            print(
                "Safety result: "
                f"{paper_order.safety_reason}"
            )
            print("LOCAL PAPER LEDGER ONLY")
            print(
                "NO WEBULL BROKER ORDER "
                "WAS SUBMITTED"
            )

        # -----------------------------------------
        # Read-only Webull trade-history P&L
        # -----------------------------------------
        elif mode == "webull-pnl":
            if len(sys.argv) != 3:
                print(
                    "Usage: python main.py "
                    "webull-pnl YYYY-MM-DD"
                )
                return 2

            date_str = sys.argv[2]

            try:
                result = (
                    bot.write_webull_daily_pnl(
                        date_str=date_str,
                    )
                )
            except Exception as error:
                print(
                    "Webull P&L import failed: "
                    f"{error}"
                )
                return 1

            summary = result["summary"]

            print()
            print(
                "WEBULL DAILY P&L "
                "IMPORT COMPLETE"
            )
            print("--------------------------------")
            print(
                f"Trading date: {summary.date}"
            )
            print(
                "Closed trades: "
                f"{summary.closed_trades}"
            )
            print(
                "Winning trades: "
                f"{summary.winning_trades}"
            )
            print(
                "Losing trades: "
                f"{summary.losing_trades}"
            )
            print(
                "Gross realized P&L: "
                f"${summary.realized_pnl:.2f}"
            )
            print(
                "READ-ONLY WEBULL ORDER HISTORY"
            )
            print(
                "NO WEBULL BROKER ORDER "
                "WAS SUBMITTED"
            )

        # -----------------------------------------
        # Historical Google Sheets backfill
        # -----------------------------------------
        elif mode == "backfill":
            if len(sys.argv) != 3:
                print(
                    "Usage: python main.py "
                    "backfill YYYY-MM-DD"
                )
                return 2

            date_str = sys.argv[2]

            try:
                trading_date = date.fromisoformat(
                    date_str
                )
            except ValueError:
                print(
                    "Backfill date must use YYYY-MM-DD."
                )
                return 2

            if not nyse_trading_dates(
                trading_date,
                trading_date,
            ):
                print(
                    "Backfill rejected: NYSE was "
                    f"closed on {date_str}."
                )
                return 2

            try:
                result = bot.run_historical_backfill(
                    date_str=date_str,
                )
            except Exception as error:
                print(
                    "Historical backfill failed: "
                    f"{error}"
                )
                return 1

            print()
            print(
                "HISTORICAL GOOGLE SHEETS "
                "BACKFILL COMPLETE"
            )
            print("--------------------------------")
            print(f"Trading date: {date_str}")
            print(
                "Selected symbols: "
                + ", ".join(
                    result["selected_symbols"]
                )
            )
            print(
                "Manipulation INVEST: "
                + (
                    ", ".join(
                        result["manipulation"]
                    )
                    if result["manipulation"]
                    else "None"
                )
            )
            print(
                "Quick Flip INVEST: "
                + (
                    ", ".join(
                        result["quick_flip"]
                    )
                    if result["quick_flip"]
                    else "None"
                )
            )
            print(
                "Google Sheets rows were reconciled "
                "by trading date."
            )

        # -----------------------------------------
        # Production wrapper
        # -----------------------------------------
        elif mode == "production":
            if len(sys.argv) != 2:
                print(
                    "Usage: python main.py production"
                )
                return 2

            bot.run_production()

        else:
            print(f"Unknown mode: {mode}")
            print_available_modes()
            return 2

    except KeyboardInterrupt:
        print("Bot stopped by user.")
        return 130

    except Exception:
        logging.getLogger(
            "trading_bot"
        ).exception(
            "Bot workflow failed."
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
