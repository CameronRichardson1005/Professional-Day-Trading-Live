import getpass
import logging
import sys
import time
from datetime import date

from trading_bot.bot import TradingBot
from trading_bot.market_calendar import nyse_trading_dates
from trading_bot.config import (
    WEBULL_SANDBOX_ORDER_MANAGEMENT_ENABLED,
    WEBULL_SANDBOX_ORDER_SUBMISSION_ENABLED,
    WEBULL_TRADING_KILL_SWITCH,
)
from trading_bot.webull_sandbox_manual_order import (
    CANCEL_CONFIRMATION_PHRASE,
    CONFIRMATION_PHRASE,
    REPLACE_CONFIRMATION_PHRASE,
    WebullSandboxManualOrderRequest,
)
from trading_bot.webull_sandbox_runtime import (
    build_webull_sandbox_manual_order_service,
    build_webull_sandbox_preflight,
    build_webull_sandbox_trade_events_runtime,
    discover_webull_sandbox_accounts,
    inspect_webull_sandbox_account,
)
from trading_bot.webull_sandbox_manual_close import (
    CLOSE_CANCEL_CONFIRMATION_PHRASE,
    CLOSE_CONFIRMATION_PHRASE,
    WebullSandboxManualCloseRequest,
)
from trading_bot.webull_sandbox_runtime import (
    build_webull_sandbox_manual_close_service,
)
from trading_bot.webull_trade_events_lifecycle import (
    WebullTradeEventsLifecycle,
)
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
    "webull-sandbox-account-status",
    "webull-sandbox-accounts",
    "webull-sandbox-preflight",
    "webull-sandbox-trade-events-check",
    "webull-sandbox-trade-events-watch",
    "webull-sandbox-test-cancel",
    "webull-sandbox-test-close",
    "webull-sandbox-test-close-cancel",
    "webull-sandbox-test-order",
    "webull-sandbox-test-replace",
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
        if mode == "webull-sandbox-account-status":
            if len(sys.argv) != 3:
                print(
                    "Usage: python main.py "
                    "webull-sandbox-account-status "
                    "ACCOUNT_ID"
                )
                return 2

            account_id = sys.argv[2].strip()

            try:
                snapshot = (
                    inspect_webull_sandbox_account(
                        account_id
                    )
                )

            except Exception as error:
                print()
                print(
                    "WEBULL SANDBOX ACCOUNT "
                    "STATUS FAILED"
                )
                print(
                    "--------------------------------"
                )
                print(f"Reason: {error}")
                print(
                    "READ-ONLY — NO WEBULL ORDER "
                    "WAS PLACED, MODIFIED, OR CANCELLED"
                )
                return 1

            state = snapshot.account_state

            print()
            print(
                "WEBULL SANDBOX ACCOUNT STATUS"
            )
            print(
                "--------------------------------"
            )
            print(
                f"Account: {snapshot.account_id}"
            )
            print(
                f"Type: {state.account_type}"
            )
            print(
                "Available cash: "
                f"${state.available_cash:.2f}"
            )

            if state.buying_power is None:
                print(
                    "Buying power: unavailable"
                )
            else:
                print(
                    "Buying power: "
                    f"${state.buying_power:.2f}"
                )

            print(
                "Positions: "
                f"{snapshot.position_count}"
            )
            print(
                "Position exposure: "
                f"${state.position_exposure:.2f}"
            )
            print(
                "Open orders: "
                f"{snapshot.open_order_count}"
            )
            print(
                "Open BUY exposure: "
                f"${state.open_buy_order_exposure:.2f}"
            )
            print(
                "Total exposure: "
                f"${state.current_total_exposure:.2f}"
            )
            print(
                "--------------------------------"
            )
            print(
                "READ-ONLY — NO WEBULL ORDER "
                "WAS PLACED, MODIFIED, OR CANCELLED"
            )

            return 0

        if mode == "webull-sandbox-accounts":
            if len(sys.argv) != 2:
                print(
                    "Usage: python main.py "
                    "webull-sandbox-accounts"
                )
                return 2

            try:
                accounts = (
                    discover_webull_sandbox_accounts()
                )

            except Exception as error:
                print()
                print(
                    "WEBULL SANDBOX ACCOUNT "
                    "DISCOVERY FAILED"
                )
                print(
                    "--------------------------------"
                )
                print(f"Reason: {error}")
                print(
                    "READ-ONLY — NO WEBULL ORDER "
                    "WAS PLACED, MODIFIED, OR CANCELLED"
                )
                return 1

            print()
            print(
                "WEBULL SANDBOX ACCOUNTS"
            )
            print(
                "--------------------------------"
            )

            for account in accounts:
                print(
                    f"{account.account_id} "
                    f"({account.account_type})"
                )

            print(
                "--------------------------------"
            )
            print(
                "READ-ONLY — NO WEBULL ORDER "
                "WAS PLACED, MODIFIED, OR CANCELLED"
            )

            return 0

        # -----------------------------------------
        # One-shot Webull sandbox Trade Events check.
        #
        # This command may connect to the Webull sandbox and
        # perform read-only reconciliation, but it cannot place,
        # replace, cancel, or close a broker order.
        #
        # It additionally refuses to run unless BOTH sandbox
        # mutation arms remain off and the live kill switch
        # remains on.
        # -----------------------------------------
        if mode == "webull-sandbox-trade-events-check":
            if len(sys.argv) != 2:
                print(
                    "Usage: python main.py "
                    "webull-sandbox-trade-events-check"
                )
                return 2

            if (
                WEBULL_SANDBOX_ORDER_SUBMISSION_ENABLED
                or WEBULL_SANDBOX_ORDER_MANAGEMENT_ENABLED
                or not WEBULL_TRADING_KILL_SWITCH
            ):
                print()
                print(
                    "WEBULL SANDBOX TRADE EVENTS "
                    "CHECK REFUSED"
                )
                print(
                    "--------------------------------"
                )
                print(
                    "Reason: connectivity check requires "
                    "sandbox submission=false, sandbox "
                    "management=false, and live kill "
                    "switch=true."
                )
                print(
                    "READ-ONLY — NO WEBULL ORDER WAS "
                    "PLACED, MODIFIED, OR CANCELLED"
                )
                return 1

            runtime = None
            lifecycle = None
            startup_result = None
            startup_error = None
            shutdown_error = None

            try:
                runtime = (
                    build_webull_sandbox_trade_events_runtime()
                )

                lifecycle = (
                    WebullTradeEventsLifecycle(
                        runtime=runtime
                    )
                )

                startup_result = lifecycle.start()

                if (
                    getattr(
                        startup_result,
                        "trusted",
                        False,
                    )
                    is not True
                ):
                    raise RuntimeError(
                        "TRADE_EVENTS_NOT_TRUSTED"
                    )

            except Exception as error:
                startup_error = error

            finally:
                # Always attempt shutdown if a lifecycle was
                # constructed, including startup failures after
                # the isolated child has already been spawned.
                if lifecycle is not None:
                    try:
                        lifecycle.stop()
                    except Exception as error:
                        shutdown_error = error

                # Independently verify no Trade Events child is
                # left alive before this one-shot command exits.
                if runtime is not None:
                    try:
                        if runtime.supervisor.is_alive():
                            raise RuntimeError(
                                "TRADE_EVENTS_WORKER_"
                                "STILL_RUNNING"
                            )
                    except Exception as error:
                        if shutdown_error is None:
                            shutdown_error = error

            if (
                startup_error is not None
                or shutdown_error is not None
            ):
                print()
                print(
                    "WEBULL SANDBOX TRADE EVENTS "
                    "CHECK FAILED"
                )
                print(
                    "--------------------------------"
                )

                if startup_error is not None:
                    print(
                        f"Reason: {startup_error}"
                    )
                else:
                    print(
                        f"Reason: {shutdown_error}"
                    )

                if (
                    startup_error is not None
                    and shutdown_error is not None
                ):
                    print(
                        "Shutdown failure: "
                        f"{shutdown_error}"
                    )

                print(
                    "READ-ONLY — NO WEBULL ORDER WAS "
                    "PLACED, MODIFIED, OR CANCELLED"
                )
                return 1

            print()
            print(
                "WEBULL SANDBOX TRADE EVENTS "
                "CHECK PASSED"
            )
            print(
                "--------------------------------"
            )
            print("Connected: True")
            print("Reconciled: True")
            print(
                "Trusted: "
                f"{startup_result.trusted}"
            )
            print(
                "Startup polls: "
                f"{startup_result.polls}"
            )
            print("Worker stopped: True")
            print(
                "--------------------------------"
            )
            print(
                "READ-ONLY — NO WEBULL ORDER WAS "
                "PLACED, MODIFIED, OR CANCELLED"
            )

            return 0

        # -----------------------------------------
        # Bounded read-only Webull sandbox Trade Events watch.
        #
        # The watcher may connect and receive sanitized broker
        # events, but it cannot place, replace, cancel, or close
        # an order. Both sandbox mutation arms must remain off.
        # -----------------------------------------
        if mode == "webull-sandbox-trade-events-watch":
            if len(sys.argv) > 3:
                print(
                    "Usage: python main.py "
                    "webull-sandbox-trade-events-watch "
                    "[SECONDS]"
                )
                return 2

            try:
                watch_seconds = (
                    float(sys.argv[2])
                    if len(sys.argv) == 3
                    else 30.0
                )
            except ValueError:
                print(
                    "Watch seconds must be numeric."
                )
                return 2

            if (
                watch_seconds < 1.0
                or watch_seconds > 300.0
            ):
                print(
                    "Watch seconds must be between "
                    "1 and 300."
                )
                return 2

            if (
                WEBULL_SANDBOX_ORDER_SUBMISSION_ENABLED
                or WEBULL_SANDBOX_ORDER_MANAGEMENT_ENABLED
                or not WEBULL_TRADING_KILL_SWITCH
            ):
                print()
                print(
                    "WEBULL SANDBOX TRADE EVENTS "
                    "WATCH REFUSED"
                )
                print(
                    "--------------------------------"
                )
                print(
                    "Reason: watcher requires sandbox "
                    "submission=false, sandbox "
                    "management=false, and live kill "
                    "switch=true."
                )
                print(
                    "READ-ONLY — NO WEBULL ORDER WAS "
                    "PLACED, MODIFIED, OR CANCELLED"
                )
                return 1

            runtime = None
            lifecycle = None
            startup_result = None
            watch_polls = 0
            initial_events = 0
            final_events = 0
            watch_error = None
            shutdown_error = None

            try:
                runtime = (
                    build_webull_sandbox_trade_events_runtime()
                )

                initial_events = (
                    runtime.journal.event_count()
                )

                lifecycle = (
                    WebullTradeEventsLifecycle(
                        runtime=runtime
                    )
                )

                startup_result = lifecycle.start()

                if (
                    getattr(
                        startup_result,
                        "trusted",
                        False,
                    )
                    is not True
                ):
                    raise RuntimeError(
                        "TRADE_EVENTS_NOT_TRUSTED"
                    )

                deadline = (
                    time.monotonic()
                    + watch_seconds
                )

                while (
                    time.monotonic()
                    < deadline
                ):
                    result = lifecycle.poll_once()
                    watch_polls += 1

                    if (
                        getattr(
                            result,
                            "trusted",
                            False,
                        )
                        is not True
                    ):
                        fatal_reason = getattr(
                            runtime.health,
                            "fatal_reason",
                            None,
                        )

                        reason = (
                            str(fatal_reason)
                            if fatal_reason
                            else "TRADE_EVENTS_TRUST_LOST"
                        )

                        raise RuntimeError(
                            "TRADE_EVENTS_WATCH_"
                            f"UNTRUSTED:{reason}"
                        )

                    time.sleep(
                        0.10
                    )

                final_events = (
                    runtime.journal.event_count()
                )

            except Exception as error:
                watch_error = error

            finally:
                if lifecycle is not None:
                    try:
                        lifecycle.stop()
                    except Exception as error:
                        shutdown_error = error

                if runtime is not None:
                    try:
                        if runtime.supervisor.is_alive():
                            raise RuntimeError(
                                "TRADE_EVENTS_WORKER_"
                                "STILL_RUNNING"
                            )
                    except Exception as error:
                        if shutdown_error is None:
                            shutdown_error = error

            if (
                watch_error is not None
                or shutdown_error is not None
            ):
                print()
                print(
                    "WEBULL SANDBOX TRADE EVENTS "
                    "WATCH FAILED"
                )
                print(
                    "--------------------------------"
                )

                if watch_error is not None:
                    print(
                        f"Reason: {watch_error}"
                    )
                else:
                    print(
                        f"Reason: {shutdown_error}"
                    )

                if (
                    watch_error is not None
                    and shutdown_error is not None
                ):
                    print(
                        "Shutdown failure: "
                        f"{shutdown_error}"
                    )

                print(
                    "READ-ONLY — NO WEBULL ORDER WAS "
                    "PLACED, MODIFIED, OR CANCELLED"
                )
                return 1

            new_events = max(
                0,
                final_events - initial_events,
            )

            print()
            print(
                "WEBULL SANDBOX TRADE EVENTS "
                "WATCH COMPLETE"
            )
            print(
                "--------------------------------"
            )
            print("Connected: True")
            print("Reconciled: True")
            print("Trusted during watch: True")
            print(
                "Watch seconds: "
                f"{watch_seconds:.1f}"
            )
            print(
                "Startup polls: "
                f"{startup_result.polls}"
            )
            print(
                "Watch polls: "
                f"{watch_polls}"
            )
            print(
                "New journaled events: "
                f"{new_events}"
            )
            print(
                "Total journaled events: "
                f"{final_events}"
            )
            print("Worker stopped: True")
            print(
                "--------------------------------"
            )
            print(
                "READ-ONLY — NO WEBULL ORDER WAS "
                "PLACED, MODIFIED, OR CANCELLED"
            )

            return 0

        if mode == "webull-sandbox-test-close-cancel":
            if len(sys.argv) != 4:
                print(
                    "Usage: python main.py "
                    "webull-sandbox-test-close-cancel "
                    "CLIENT_ORDER_ID "
                    "CONFIRM_SANDBOX_CLOSE_CANCEL"
                )
                return 2

            client_order_id = (
                sys.argv[2].strip()
            )

            confirmation = (
                sys.argv[3].strip()
            )

            if (
                confirmation
                != CLOSE_CANCEL_CONFIRMATION_PHRASE
            ):
                print(
                    "Sandbox close-cancel confirmation "
                    "phrase was incorrect."
                )
                return 2

            try:
                service = (
                    build_webull_sandbox_manual_close_service()
                )

                result = service.cancel(
                    client_order_id=(
                        client_order_id
                    ),
                    confirmation=confirmation,
                )

            except Exception as error:
                print()
                print(
                    "WEBULL SANDBOX TEST "
                    "CLOSE CANCEL FAILED"
                )
                print(
                    "--------------------------------"
                )
                print(f"Reason: {error}")
                print(
                    "SANDBOX ONLY — LIVE TRADING "
                    "WAS NOT USED"
                )
                return 1

            print()
            print(
                "WEBULL SANDBOX TEST CLOSE CANCEL"
            )
            print(
                "--------------------------------"
            )
            print(
                "Client order ID: "
                f"{result.client_order_id}"
            )
            print(
                f"Symbol: {result.symbol}"
            )
            print(
                f"Status: {result.status}"
            )
            print(
                "Filled quantity: "
                f"{result.filled_quantity}"
            )
            print(
                "Position reconciled: "
                f"{result.position_reconciled}"
            )

            if result.broker_order_id:
                print(
                    "Broker order ID: "
                    f"{result.broker_order_id}"
                )

            if result.broker_status:
                print(
                    "Broker status: "
                    f"{result.broker_status}"
                )

            print(
                "--------------------------------"
            )
            print(
                "SANDBOX ONLY — NO LIVE "
                "WEBULL ORDER WAS MODIFIED"
            )

            return 0

        if mode == "webull-sandbox-test-close":
            if len(sys.argv) != 6:
                print(
                    "Usage: python main.py "
                    "webull-sandbox-test-close "
                    "SYMBOL QUANTITY LIMIT_PRICE "
                    "CONFIRM_SANDBOX_CLOSE"
                )
                return 2

            symbol = sys.argv[2].strip()

            try:
                quantity = int(
                    sys.argv[3]
                )

                limit_price = float(
                    sys.argv[4]
                )

            except ValueError:
                print(
                    "Quantity must be an integer "
                    "and limit price must be numeric."
                )
                return 2

            confirmation = (
                sys.argv[5].strip()
            )

            if (
                confirmation
                != CLOSE_CONFIRMATION_PHRASE
            ):
                print(
                    "Sandbox close confirmation "
                    "phrase was incorrect."
                )
                return 2

            try:
                request = (
                    WebullSandboxManualCloseRequest(
                        symbol=symbol,
                        quantity=quantity,
                        limit_price=limit_price,
                        confirmation=confirmation,
                    )
                )

                service = (
                    build_webull_sandbox_manual_close_service()
                )

                result = service.close(
                    request
                )

            except Exception as error:
                print()
                print(
                    "WEBULL SANDBOX TEST CLOSE FAILED"
                )
                print(
                    "--------------------------------"
                )
                print(f"Reason: {error}")
                print(
                    "SANDBOX ONLY — LIVE TRADING "
                    "WAS NOT USED"
                )
                return 1

            print()
            print(
                "WEBULL SANDBOX TEST CLOSE"
            )
            print(
                "--------------------------------"
            )
            print(
                "Client order ID: "
                f"{result.client_order_id}"
            )
            print(
                f"Symbol: {result.symbol}"
            )
            print(
                f"Side: {result.side}"
            )
            print(
                f"Quantity: {result.quantity}"
            )
            print(
                "Limit price: "
                f"${result.limit_price:.4f}"
            )
            print(
                f"Status: {result.status}"
            )
            print(
                "Filled quantity: "
                f"{result.filled_quantity}"
            )
            print(
                "Position reconciled: "
                f"{result.position_reconciled}"
            )

            if result.broker_order_id:
                print(
                    "Broker order ID: "
                    f"{result.broker_order_id}"
                )

            if result.broker_status:
                print(
                    "Broker status: "
                    f"{result.broker_status}"
                )

            print(
                "--------------------------------"
            )
            print(
                "SANDBOX ONLY — NO LIVE "
                "WEBULL POSITION WAS CLOSED"
            )

            return 0

        if mode == "webull-sandbox-test-cancel":
            if len(sys.argv) != 4:
                print(
                    "Usage: python main.py "
                    "webull-sandbox-test-cancel "
                    "CLIENT_ORDER_ID "
                    "CONFIRM_SANDBOX_CANCEL"
                )
                return 2

            client_order_id = (
                sys.argv[2].strip()
            )

            confirmation = (
                sys.argv[3].strip()
            )

            if (
                confirmation
                != CANCEL_CONFIRMATION_PHRASE
            ):
                print(
                    "Sandbox cancel confirmation "
                    "phrase was incorrect."
                )
                return 2

            try:
                service = (
                    build_webull_sandbox_manual_order_service()
                )

                result = service.cancel(
                    client_order_id=(
                        client_order_id
                    ),
                    confirmation=confirmation,
                )

            except Exception as error:
                print()
                print(
                    "WEBULL SANDBOX TEST CANCEL FAILED"
                )
                print(
                    "--------------------------------"
                )
                print(f"Reason: {error}")
                print(
                    "SANDBOX ONLY — LIVE TRADING "
                    "WAS NOT USED"
                )
                return 1

            print()
            print(
                "WEBULL SANDBOX TEST CANCEL"
            )
            print(
                "--------------------------------"
            )
            print(
                "Client order ID: "
                f"{result.client_order_id}"
            )
            print(
                f"Symbol: {result.symbol}"
            )
            print(
                f"Status: {result.status}"
            )

            if result.broker_status:
                print(
                    "Broker status: "
                    f"{result.broker_status}"
                )

            print(
                "Manual override: "
                f"{result.manual_override}"
            )
            print(
                "--------------------------------"
            )
            print(
                "SANDBOX ONLY — NO LIVE "
                "WEBULL ORDER WAS MODIFIED"
            )

            return 0

        if mode == "webull-sandbox-test-replace":
            if len(sys.argv) != 6:
                print(
                    "Usage: python main.py "
                    "webull-sandbox-test-replace "
                    "CLIENT_ORDER_ID QUANTITY LIMIT_PRICE "
                    "CONFIRM_SANDBOX_REPLACE"
                )
                return 2

            client_order_id = (
                sys.argv[2].strip()
            )

            try:
                quantity = int(
                    sys.argv[3]
                )

                limit_price = float(
                    sys.argv[4]
                )

            except ValueError:
                print(
                    "Quantity must be an integer "
                    "and limit price must be numeric."
                )
                return 2

            confirmation = (
                sys.argv[5].strip()
            )

            if (
                confirmation
                != REPLACE_CONFIRMATION_PHRASE
            ):
                print(
                    "Sandbox replace confirmation "
                    "phrase was incorrect."
                )
                return 2

            try:
                service = (
                    build_webull_sandbox_manual_order_service()
                )

                result = service.replace(
                    client_order_id=(
                        client_order_id
                    ),
                    quantity=quantity,
                    limit_price=limit_price,
                    confirmation=confirmation,
                )

            except Exception as error:
                print()
                print(
                    "WEBULL SANDBOX TEST REPLACE FAILED"
                )
                print(
                    "--------------------------------"
                )
                print(f"Reason: {error}")
                print(
                    "SANDBOX ONLY — LIVE TRADING "
                    "WAS NOT USED"
                )
                return 1

            print()
            print(
                "WEBULL SANDBOX TEST REPLACE"
            )
            print(
                "--------------------------------"
            )
            print(
                "Client order ID: "
                f"{result.client_order_id}"
            )
            print(
                f"Symbol: {result.symbol}"
            )
            print(
                f"Quantity: {result.quantity}"
            )
            print(
                "Limit price: "
                f"${result.limit_price:.4f}"
            )
            print(
                f"Status: {result.status}"
            )

            if result.broker_status:
                print(
                    "Broker status: "
                    f"{result.broker_status}"
                )

            print(
                "Manual override: "
                f"{result.manual_override}"
            )
            print(
                "--------------------------------"
            )
            print(
                "SANDBOX ONLY — NO LIVE "
                "WEBULL ORDER WAS MODIFIED"
            )

            return 0

        if mode == "webull-sandbox-test-order":
            if len(sys.argv) != 6:
                print(
                    "Usage: python main.py "
                    "webull-sandbox-test-order "
                    "SYMBOL QUANTITY LIMIT_PRICE "
                    "CONFIRM_SANDBOX_ORDER"
                )
                return 2

            symbol = sys.argv[2]

            try:
                quantity = int(
                    sys.argv[3]
                )

                limit_price = float(
                    sys.argv[4]
                )

            except ValueError:
                print(
                    "Quantity must be an integer "
                    "and limit price must be numeric."
                )
                return 2

            confirmation = sys.argv[5]

            if (
                confirmation
                != CONFIRMATION_PHRASE
            ):
                print(
                    "Sandbox order confirmation "
                    "phrase was incorrect."
                )
                return 2

            try:
                request = (
                    WebullSandboxManualOrderRequest(
                        symbol=symbol,
                        quantity=quantity,
                        limit_price=limit_price,
                        confirmation=confirmation,
                    )
                )

                service = (
                    build_webull_sandbox_manual_order_service()
                )

                result = service.place(
                    request
                )

            except Exception as error:
                print()
                print(
                    "WEBULL SANDBOX TEST ORDER FAILED"
                )
                print(
                    "--------------------------------"
                )
                print(f"Reason: {error}")
                print(
                    "SANDBOX ONLY — LIVE TRADING "
                    "WAS NOT USED"
                )
                return 1

            print()
            print(
                "WEBULL SANDBOX TEST ORDER"
            )
            print(
                "--------------------------------"
            )
            print(
                f"Client order ID: "
                f"{result.client_order_id}"
            )
            print(
                f"Symbol: {result.symbol}"
            )
            print(
                f"Quantity: {result.quantity}"
            )
            print(
                f"Limit price: "
                f"${result.limit_price:.4f}"
            )
            print(
                f"Status: {result.status}"
            )

            if result.broker_order_id:
                print(
                    "Broker order ID: "
                    f"{result.broker_order_id}"
                )

            if result.broker_status:
                print(
                    "Broker status: "
                    f"{result.broker_status}"
                )

            print(
                "--------------------------------"
            )
            print(
                "SANDBOX ONLY — NO LIVE "
                "WEBULL ORDER WAS PLACED"
            )

            return 0

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
