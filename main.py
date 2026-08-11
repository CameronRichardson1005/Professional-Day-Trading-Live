import getpass
import logging
import sys
from datetime import date

from trading_bot.bot import TradingBot
from trading_bot.config import MARKET_DATA_FEED
from trading_bot.fibonacci_paper import print_fibonacci_paper_status
from trading_bot.fibonacci_dashboard import FibonacciDashboardPublisher
from trading_bot.market_calendar import nyse_trading_dates
from trading_bot.utils import setup_logging


def main() -> int:
    log_path = setup_logging()

    print(f"Log file: {log_path}")

    mode = (
        sys.argv[1].lower()
        if len(sys.argv) > 1
        else "test"
    )

    try:
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
                    f"NYSE is scheduled to trade on "
                    f"{check_date.isoformat()}."
                )
                return 0

            print(
                f"NYSE is closed on "
                f"{check_date.isoformat()}."
            )
            return 2

        bot = TradingBot()

        if mode == "test":
            bot.run()

        elif mode == "smoke":
            date_str = (
                sys.argv[2]
                if len(sys.argv) > 2
                else None
            )

            succeeded = bot.run_scanner_smoke(
                date_str=date_str
            )

            if not succeeded:
                return 1

        elif mode == "preflight":
            date_str = (
                sys.argv[2]
                if len(sys.argv) > 2
                else None
            )

            succeeded = bot.run_preflight(
                date_str=date_str
            )

            if not succeeded:
                return 1

        elif mode == "live":
            bot.run_live_tracker()

        elif mode == "live-dry-run":
            bot.run_live_tracker(
                write_sheets=False,
                publish_dashboard=False,
            )

        elif mode == "live-recover":
            if len(sys.argv) != 3:
                print(
                    "Usage: python main.py live-recover "
                    "YYYY-MM-DD"
                )
                return 2

            bot.run_live_recovery(
                date_str=sys.argv[2],
            )

        elif mode == "strategy":
            bot.run_strategy_test()

        elif mode == "write":
            date_str = (
                sys.argv[2]
                if len(sys.argv) > 2
                else None
            )

            bot.run_strategy_and_write(
                date_str=date_str
            )

        elif mode == "replay":
            if len(sys.argv) < 3:
                print(
                    "Usage: python main.py replay "
                    "YYYY-MM-DD [--speed NUMBER] "
                    "[--feed iex|sip]"
                )
                return 2

            date_str = sys.argv[2]
            speed = 60.0
            data_feed = MARKET_DATA_FEED
            replay_options = sys.argv[3:]

            if len(replay_options) % 2:
                print(
                    "Usage: python main.py replay "
                    "YYYY-MM-DD [--speed NUMBER] "
                    "[--feed iex|sip]"
                )
                return 2

            for index in range(0, len(replay_options), 2):
                option = replay_options[index]
                value = replay_options[index + 1]

                if option == "--speed":
                    try:
                        speed = float(value)
                    except ValueError:
                        print("Replay speed must be a number.")
                        return 2
                elif option == "--feed":
                    data_feed = value.lower()
                    if data_feed not in {"iex", "sip"}:
                        print("Feed must be 'iex' or 'sip'.")
                        return 2
                else:
                    print(
                        "Usage: python main.py replay "
                        "YYYY-MM-DD [--speed NUMBER] "
                        "[--feed iex|sip]"
                    )
                    return 2

            bot.run_replay(
                date_str=date_str,
                speed=speed,
                data_feed=data_feed,
            )

        elif mode == "dashboard-backfill":
            if len(sys.argv) not in {4, 6}:
                print(
                    "Usage: python main.py dashboard-backfill "
                    "START_DATE END_DATE [--feed iex|sip]"
                )
                return 2

            start_date = sys.argv[2]
            end_date = sys.argv[3]
            data_feed = MARKET_DATA_FEED

            if len(sys.argv) == 6:
                if sys.argv[4] != "--feed":
                    print(
                        "Usage: python main.py "
                        "dashboard-backfill START_DATE "
                        "END_DATE [--feed iex|sip]"
                    )
                    return 2

                data_feed = sys.argv[5].lower()

                if data_feed not in {"iex", "sip"}:
                    print("Feed must be 'iex' or 'sip'.")
                    return 2

            bot.run_dashboard_backfill(
                start_date=start_date,
                end_date=end_date,
                data_feed=data_feed,
            )

        elif mode == "fibonacci-paper-status":
            if len(sys.argv) != 2:
                print(
                    "Usage: python main.py "
                    "fibonacci-paper-status"
                )
                return 2

            print_fibonacci_paper_status()

        elif mode == "fibonacci-paper-publish":
            if len(sys.argv) != 2:
                print(
                    "Usage: python main.py "
                    "fibonacci-paper-publish"
                )
                return 2

            publisher = FibonacciDashboardPublisher()
            result = publisher.publish()

            if result is None:
                print(
                    "Fibonacci dashboard upload skipped: "
                    "DASHBOARD_INGEST_KEY is not configured."
                )
                return 0

            print(
                "Fibonacci paper status uploaded: "
                "PAPER ONLY — NOT SUBMITTED"
            )

        elif mode == "fibonacci-paper":
            date_str = None
            output_path = (
                "reports/fibonacci-paper/"
                "fibonacci_paper_ledger.csv"
            )
            data_feed = MARKET_DATA_FEED
            slippage_bps = 15.0
            publish_outputs = False

            options_start = 2

            if (
                len(sys.argv) > 2
                and not sys.argv[2].startswith("--")
            ):
                date_str = sys.argv[2]
                options_start = 3

            options = sys.argv[options_start:]

            if len(options) % 2:
                print(
                    "Usage: python main.py "
                    "fibonacci-paper [YYYY-MM-DD] "
                    "[--output FILE] "
                    "[--feed iex|sip] "
                    "[--slippage-bps NUMBER] "
                    "[--publish yes|no]"
                )
                return 2

            for index in range(0, len(options), 2):
                option = options[index]
                value = options[index + 1]

                if option == "--output":
                    output_path = value

                elif option == "--feed":
                    data_feed = value.lower()

                    if data_feed not in {"iex", "sip"}:
                        print(
                            "Feed must be 'iex' or 'sip'."
                        )
                        return 2

                elif option == "--slippage-bps":
                    try:
                        slippage_bps = float(value)
                    except ValueError:
                        print(
                            "Slippage bps must be a number."
                        )
                        return 2

                    if slippage_bps < 0:
                        print(
                            "Slippage bps cannot be negative."
                        )
                        return 2

                elif option == "--publish":
                    normalized = value.strip().lower()

                    if normalized not in {
                        "yes",
                        "no",
                        "true",
                        "false",
                    }:
                        print(
                            "--publish must be yes or no."
                        )
                        return 2

                    publish_outputs = (
                        normalized in {"yes", "true"}
                    )

                else:
                    print(
                        "Usage: python main.py "
                        "fibonacci-paper [YYYY-MM-DD] "
                        "[--output FILE] "
                        "[--feed iex|sip] "
                        "[--slippage-bps NUMBER]"
                    )
                    return 2

            bot.run_fibonacci_paper(
                date_str=date_str,
                output_path=output_path,
                data_feed=data_feed,
                slippage_bps=slippage_bps,
                            publish_outputs=publish_outputs,
)

        elif mode == "fibonacci-retracement":
            if len(sys.argv) < 4:
                print(
                    "Usage: python main.py "
                    "fibonacci-retracement "
                    "START_DATE END_DATE "
                    "[--output DIRECTORY] "
                    "[--feed iex|sip] "
                    "[--slippage-bps NUMBER] "
                    "[--commission-per-share NUMBER] "
                    "[--minimum-impulse-atr NUMBER]"
                )
                return 2

            output_directory = (
                "reports/fibonacci-retracement"
            )
            data_feed = MARKET_DATA_FEED
            slippage_bps = 0.0
            commission_per_share = 0.0
            minimum_impulse_atr = 1.0
            options = sys.argv[4:]

            if len(options) % 2:
                print(
                    "Usage: python main.py "
                    "fibonacci-retracement "
                    "START_DATE END_DATE "
                    "[--output DIRECTORY] "
                    "[--feed iex|sip] "
                    "[--slippage-bps NUMBER] "
                    "[--commission-per-share NUMBER] "
                    "[--minimum-impulse-atr NUMBER]"
                )
                return 2

            for index in range(
                0,
                len(options),
                2,
            ):
                option = options[index]
                value = options[index + 1]

                if option == "--output":
                    output_directory = value

                elif option == "--feed":
                    data_feed = value.lower()

                    if data_feed not in {"iex", "sip"}:
                        print(
                            "Feed must be 'iex' or 'sip'."
                        )
                        return 2

                elif option == "--slippage-bps":
                    try:
                        slippage_bps = float(value)
                    except ValueError:
                        print(
                            "Slippage bps must be a number."
                        )
                        return 2

                elif option == "--commission-per-share":
                    try:
                        commission_per_share = float(
                            value
                        )
                    except ValueError:
                        print(
                            "Commission per share must be "
                            "a number."
                        )
                        return 2

                elif option == "--minimum-impulse-atr":
                    try:
                        minimum_impulse_atr = float(value)
                    except ValueError:
                        print(
                            "Minimum impulse ATR must be "
                            "a number."
                        )
                        return 2

                    if minimum_impulse_atr <= 0:
                        print(
                            "Minimum impulse ATR must be "
                            "positive."
                        )
                        return 2

                else:
                    print(
                        "Usage: python main.py "
                        "fibonacci-retracement "
                        "START_DATE END_DATE "
                        "[--output DIRECTORY] "
                        "[--feed iex|sip] "
                        "[--slippage-bps NUMBER] "
                        "[--commission-per-share NUMBER] "
                    "[--minimum-impulse-atr NUMBER]"
                    )
                    return 2

            bot.run_fibonacci_retracement_research(
                start_date=sys.argv[2],
                end_date=sys.argv[3],
                output_directory=output_directory,
                data_feed=data_feed,
                slippage_bps=slippage_bps,
                commission_per_share=(
                    commission_per_share
                ),
                minimum_impulse_atr=(
                    minimum_impulse_atr
                ),
            )

        elif mode == "fibonacci-entry-stop-comparison":
            if len(sys.argv) < 4:
                print(
                    "Usage: python main.py "
                    "fibonacci-entry-stop-comparison "
                    "START_DATE END_DATE "
                    "[--output DIRECTORY] "
                    "[--feed iex|sip] "
                    "[--slippage-bps NUMBER] "
                    "[--commission-per-share NUMBER]"
                )
                return 2

            output_directory = (
                "reports/fibonacci-entry-stop-comparison"
            )
            data_feed = MARKET_DATA_FEED
            slippage_bps = 15.0
            commission_per_share = 0.0
            options = sys.argv[4:]

            if len(options) % 2:
                print(
                    "Comparison options must use "
                    "option/value pairs."
                )
                return 2

            for index in range(0, len(options), 2):
                option = options[index]
                value = options[index + 1]

                if option == "--output":
                    output_directory = value

                elif option == "--feed":
                    data_feed = value.lower()

                    if data_feed not in {"iex", "sip"}:
                        print("Feed must be 'iex' or 'sip'.")
                        return 2

                elif option == "--slippage-bps":
                    try:
                        slippage_bps = float(value)
                    except ValueError:
                        print(
                            "Slippage bps must be a number."
                        )
                        return 2

                    if slippage_bps < 0:
                        print(
                            "Slippage bps cannot be negative."
                        )
                        return 2

                elif option == "--commission-per-share":
                    try:
                        commission_per_share = float(value)
                    except ValueError:
                        print(
                            "Commission per share must be "
                            "a number."
                        )
                        return 2

                    if commission_per_share < 0:
                        print(
                            "Commission cannot be negative."
                        )
                        return 2

                else:
                    print(f"Unknown option: {option}")
                    return 2

            bot.run_fibonacci_entry_stop_comparison(
                start_date=sys.argv[2],
                end_date=sys.argv[3],
                output_directory=output_directory,
                data_feed=data_feed,
                slippage_bps=slippage_bps,
                commission_per_share=(
                    commission_per_share
                ),
            )

        elif mode == "fibonacci-impulse-comparison":
            if len(sys.argv) < 4:
                print(
                    "Usage: python main.py "
                    "fibonacci-impulse-comparison "
                    "START_DATE END_DATE "
                    "[--output DIRECTORY] "
                    "[--feed iex|sip] "
                    "[--slippage-bps NUMBER] "
                    "[--commission-per-share NUMBER] "
                    "[--minimum-impulse-atr NUMBER]"
                )
                return 2

            output_directory = (
                "reports/fibonacci-impulse-comparison"
            )
            data_feed = MARKET_DATA_FEED
            slippage_bps = 15.0
            commission_per_share = 0.0
            minimum_impulse_atr = 0.50
            options = sys.argv[4:]

            if len(options) % 2:
                print(
                    "Comparison options must use "
                    "option/value pairs."
                )
                return 2

            for index in range(0, len(options), 2):
                option = options[index]
                value = options[index + 1]

                if option == "--output":
                    output_directory = value

                elif option == "--feed":
                    data_feed = value.lower()

                    if data_feed not in {"iex", "sip"}:
                        print("Feed must be 'iex' or 'sip'.")
                        return 2

                elif option == "--slippage-bps":
                    try:
                        slippage_bps = float(value)
                    except ValueError:
                        print(
                            "Slippage bps must be a number."
                        )
                        return 2

                    if slippage_bps < 0:
                        print(
                            "Slippage bps cannot be negative."
                        )
                        return 2

                elif option == "--commission-per-share":
                    try:
                        commission_per_share = float(value)
                    except ValueError:
                        print(
                            "Commission per share must be "
                            "a number."
                        )
                        return 2

                    if commission_per_share < 0:
                        print(
                            "Commission cannot be negative."
                        )
                        return 2

                elif option == "--minimum-impulse-atr":
                    try:
                        minimum_impulse_atr = float(value)
                    except ValueError:
                        print(
                            "Minimum impulse ATR must be "
                            "a number."
                        )
                        return 2

                    if minimum_impulse_atr <= 0:
                        print(
                            "Minimum impulse ATR must be "
                            "positive."
                        )
                        return 2

                else:
                    print(f"Unknown option: {option}")
                    return 2

            bot.run_fibonacci_impulse_comparison(
                start_date=sys.argv[2],
                end_date=sys.argv[3],
                output_directory=output_directory,
                data_feed=data_feed,
                slippage_bps=slippage_bps,
                commission_per_share=(
                    commission_per_share
                ),
                minimum_impulse_atr=(
                    minimum_impulse_atr
                ),
            )

        elif mode == "fibonacci-research":
            if len(sys.argv) < 4:
                print(
                    "Usage: python main.py fibonacci-research "
                    "START_DATE END_DATE "
                    "[--output DIRECTORY] "
                    "[--feed iex|sip] "
                    "[--slippage-bps NUMBER] "
                    "[--commission-per-share NUMBER]"
                )
                return 2

            output_directory = "reports/fibonacci"
            data_feed = MARKET_DATA_FEED
            slippage_bps = 0.0
            commission_per_share = 0.0
            research_options = sys.argv[4:]

            if len(research_options) % 2:
                print(
                    "Usage: python main.py fibonacci-research "
                    "START_DATE END_DATE "
                    "[--output DIRECTORY] "
                    "[--feed iex|sip] "
                    "[--slippage-bps NUMBER] "
                    "[--commission-per-share NUMBER]"
                )
                return 2

            for index in range(
                0,
                len(research_options),
                2,
            ):
                option = research_options[index]
                value = research_options[index + 1]

                if option == "--output":
                    output_directory = value

                elif option == "--feed":
                    data_feed = value.lower()

                    if data_feed not in {"iex", "sip"}:
                        print(
                            "Feed must be 'iex' or 'sip'."
                        )
                        return 2

                elif option == "--slippage-bps":
                    try:
                        slippage_bps = float(value)
                    except ValueError:
                        print(
                            "Slippage bps must be a number."
                        )
                        return 2

                elif option == "--commission-per-share":
                    try:
                        commission_per_share = float(
                            value
                        )
                    except ValueError:
                        print(
                            "Commission per share must be "
                            "a number."
                        )
                        return 2

                else:
                    print(
                        "Usage: python main.py "
                        "fibonacci-research "
                        "START_DATE END_DATE "
                        "[--output DIRECTORY] "
                        "[--feed iex|sip] "
                        "[--slippage-bps NUMBER] "
                        "[--commission-per-share NUMBER]"
                    )
                    return 2

            bot.run_fibonacci_research(
                start_date=sys.argv[2],
                end_date=sys.argv[3],
                output_directory=output_directory,
                data_feed=data_feed,
                slippage_bps=slippage_bps,
                commission_per_share=(
                    commission_per_share
                ),
            )

        elif mode == "backtest":
            if len(sys.argv) < 4:
                print(
                    "Usage: python main.py backtest "
                    "START_DATE END_DATE "
                    "[--output DIRECTORY] "
                    "[--feed iex|sip] "
                    "[--slippage-bps NUMBER] "
                    "[--commission-per-share NUMBER] "
                    "[--train-fraction NUMBER]"
                )
                return 2

            output_directory = "reports"
            data_feed = MARKET_DATA_FEED
            slippage_bps = 0.0
            commission_per_share = 0.0
            train_fraction = 0.70
            backtest_options = sys.argv[4:]

            if len(backtest_options) % 2:
                print(
                    "Usage: python main.py backtest "
                    "START_DATE END_DATE "
                    "[--output DIRECTORY] "
                    "[--feed iex|sip] "
                    "[--slippage-bps NUMBER] "
                    "[--commission-per-share NUMBER] "
                    "[--train-fraction NUMBER]"
                )
                return 2

            for index in range(0, len(backtest_options), 2):
                option = backtest_options[index]
                value = backtest_options[index + 1]

                if option == "--output":
                    output_directory = value
                elif option == "--feed":
                    data_feed = value.lower()
                    if data_feed not in {"iex", "sip"}:
                        print("Feed must be 'iex' or 'sip'.")
                        return 2
                elif option == "--slippage-bps":
                    try:
                        slippage_bps = float(value)
                    except ValueError:
                        print(
                            "Slippage bps must be a number."
                        )
                        return 2
                elif option == "--commission-per-share":
                    try:
                        commission_per_share = float(value)
                    except ValueError:
                        print(
                            "Commission per share must be "
                            "a number."
                        )
                        return 2
                elif option == "--train-fraction":
                    try:
                        train_fraction = float(value)
                    except ValueError:
                        print(
                            "Train fraction must be a number."
                        )
                        return 2
                else:
                    print(
                        "Usage: python main.py backtest "
                        "START_DATE END_DATE "
                        "[--output DIRECTORY] "
                        "[--feed iex|sip] "
                        "[--slippage-bps NUMBER] "
                        "[--commission-per-share NUMBER] "
                        "[--train-fraction NUMBER]"
                    )
                    return 2

            bot.run_backtest(
                start_date=sys.argv[2],
                end_date=sys.argv[3],
                output_directory=output_directory,
                data_feed=data_feed,
                slippage_bps=slippage_bps,
                commission_per_share=(
                    commission_per_share
                ),
                train_fraction=train_fraction,
            )

        elif mode == "webull-approval-request":
            if len(sys.argv) != 3:
                print(
                    "Usage: python main.py "
                    "webull-approval-request SYMBOL"
                )
                return 2

            try:
                ticket = bot.request_webull_approval(
                    sys.argv[2]
                )
            except Exception as error:
                print(
                    "Webull approval request rejected: "
                    f"{error}"
                )
                return 1

            # Deliberately bypass normal logging so the one-time
            # token is shown only in the local terminal.
            sys.__stdout__.write(
                "\nWEBULL PREVIEW APPROVAL CREATED\n"
                "--------------------------------\n"
                f"Symbol: {ticket.symbol}\n"
                f"Quantity: {ticket.quantity}\n"
                f"Limit price: ${ticket.limit_price:.4f}\n"
                "Proposed exposure: "
                f"${ticket.proposed_exposure:.2f}\n"
                f"Expires: {ticket.expires_at.isoformat()}\n"
                f"Approval ID: {ticket.approval_id}\n"
                "One-time approval token:\n"
                f"{ticket.approval_token}\n"
                "\nNOT SUBMITTED — KILL SWITCH ACTIVE\n"
            )
            sys.__stdout__.flush()

        elif mode == "webull-approval-confirm":
            if len(sys.argv) != 3:
                print(
                    "Usage: python main.py "
                    "webull-approval-confirm APPROVAL_ID"
                )
                return 2

            approval_token = getpass.getpass(
                "One-time approval token: "
            )

            try:
                status = bot.confirm_webull_approval(
                    approval_id=sys.argv[2],
                    approval_token=approval_token,
                )
            except Exception as error:
                print(
                    "Webull approval confirmation rejected: "
                    f"{error}"
                )
                return 1

            print()
            print("WEBULL APPROVAL CONFIRMED")
            print("--------------------------------")
            print(f"Status: {status}")
            print("NO WEBULL BROKER ORDER WAS SUBMITTED")

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
                        approval_token=approval_token,
                    )
                )
            except Exception as error:
                print(
                    "Webull paper submission rejected: "
                    f"{error}"
                )
                return 1

            print()
            print("WEBULL PAPER ORDER RECORDED")
            print("--------------------------------")
            print(f"Paper order ID: {paper_order.paper_order_id}")
            print(f"Symbol: {paper_order.symbol}")
            print(f"Side: {paper_order.side}")
            print(f"Quantity: {paper_order.quantity}")
            print(
                "Limit price: "
                f"${paper_order.limit_price:.4f}"
            )
            print(
                "Proposed exposure: "
                f"${paper_order.proposed_exposure:.2f}"
            )
            print(f"Status: {paper_order.status}")
            print(
                "Safety result: "
                f"{paper_order.safety_reason}"
            )
            print("LOCAL PAPER LEDGER ONLY")
            print("NO WEBULL BROKER ORDER WAS SUBMITTED")

        elif mode == "webull-pnl":
            if len(sys.argv) != 3:
                print(
                    "Usage: python main.py "
                    "webull-pnl YYYY-MM-DD"
                )
                return 2

            date_str = sys.argv[2]

            try:
                result = bot.write_webull_daily_pnl(
                    date_str=date_str,
                )
            except Exception as error:
                print(
                    "Webull P&L import failed: "
                    f"{error}"
                )
                return 1

            summary = result["summary"]

            print()
            print("WEBULL DAILY P&L IMPORT COMPLETE")
            print("--------------------------------")
            print(
                f"Trading date: {summary.date}"
            )
            print(
                f"Closed trades: "
                f"{summary.closed_trades}"
            )
            print(
                f"Winning trades: "
                f"{summary.winning_trades}"
            )
            print(
                f"Losing trades: "
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
                "NO WEBULL BROKER ORDER WAS SUBMITTED"
            )

        elif mode == "production":
            bot.run_production()

        else:
            print(f"Unknown mode: {mode}")
            print(
                "Available modes: "
                "test, smoke, preflight, live, live-dry-run, "
                "live-recover, strategy, "
                "write, replay, fibonacci-research, "
                "fibonacci-retracement, "
                "fibonacci-entry-stop-comparison, "
                "fibonacci-impulse-comparison, "
                "fibonacci-paper, "
                "fibonacci-paper-status, "
                "fibonacci-paper-publish, "
                "backtest, webull-approval-request, "
                "webull-approval-confirm, "
                "webull-paper-submit, webull-pnl, "
                "production"
            )
            return 2

    except KeyboardInterrupt:
        print("Bot stopped by user.")
        return 130

    except Exception:
        logging.getLogger(
            "trading_bot"
        ).exception("Bot workflow failed.")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
