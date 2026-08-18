from __future__ import annotations

import multiprocessing as mp
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .config import (
    WEBULL_EXECUTION_LEDGER_FILE,
    WEBULL_EXECUTION_MODE,
    WEBULL_TRADE_EVENTS_JOURNAL_FILE,
    WEBULL_SANDBOX_ACCOUNT_ID,
    WEBULL_SANDBOX_APP_KEY,
    WEBULL_SANDBOX_APP_SECRET,
    WEBULL_SANDBOX_ORDER_MANAGEMENT_ENABLED,
    WEBULL_SANDBOX_ORDER_SUBMISSION_ENABLED,
)
from .webull_execution_ledger import (
    WebullExecutionLedger,
)
from .webull_execution_manager import (
    WebullSandboxExecutionManager,
)
from .webull_reduce_only_close import (
    WebullReduceOnlyCloseLedger,
)
from .webull_reduce_only_close_manager import (
    WebullSandboxReduceOnlyCloseManager,
)
from .webull_sandbox_manual_close import (
    WebullSandboxManualCloseService,
)
from .webull_sdk_safety import (
    build_quiet_trade_client,
)
from .webull_sandbox_manual_order import (
    WebullSandboxManualOrderService,
)
from .webull_sandbox_broker import (
    SANDBOX_ENDPOINT,
    WebullSandboxBroker,
)
from .webull_sandbox_preflight import (
    WebullSandboxAccountSnapshotClient,
    WebullSandboxPreflight,
    WebullSandboxPreflightError,
    list_sandbox_accounts,
)


from .webull_trade_events_journal import (
    WebullTradeEventsHealthState,
    WebullTradeEventsJournal,
)
from .webull_trade_events_parent import (
    WebullTradeEventsParentController,
)
from .webull_trade_events_process import (
    WebullTradeEventsProcessSupervisor,
)
from .webull_trade_events_reconciliation import (
    WebullTradeEventsPreflightReconciler,
)
from .webull_trade_events_worker import (
    WEBULL_SANDBOX_EVENTS_HOST,
    run_webull_trade_events_worker,
)


def build_webull_sandbox_preflight(
) -> WebullSandboxPreflight:
    """
    Build the read-only Webull sandbox preflight.

    The broker is deliberately constructed with sandbox order
    submission disabled, regardless of external arming flags.
    """

    snapshot_client = (
        WebullSandboxAccountSnapshotClient(
            account_id=(
                WEBULL_SANDBOX_ACCOUNT_ID
            ),
            execution_mode=(
                WEBULL_EXECUTION_MODE
            ),
        )
    )

    broker = WebullSandboxBroker(
        account_id=WEBULL_SANDBOX_ACCOUNT_ID,
        execution_mode=WEBULL_EXECUTION_MODE,

        # Critical safety property:
        # preflight can NEVER mutate broker orders.
        submission_enabled=False,
    )

    ledger = WebullExecutionLedger(
        WEBULL_EXECUTION_LEDGER_FILE
    )

    return WebullSandboxPreflight(
        snapshot_client=snapshot_client,
        broker=broker,
        ledger=ledger,
    )



def discover_webull_sandbox_accounts(
):
    """
    Read the Webull sandbox account list.

    No account ID is required and no trading/order operation
    is exposed by this function.
    """

    if WEBULL_EXECUTION_MODE != "SANDBOX":
        raise WebullSandboxPreflightError(
            "SANDBOX_MODE_REQUIRED"
        )

    if not WEBULL_SANDBOX_APP_KEY:
        raise WebullSandboxPreflightError(
            "SANDBOX_APP_KEY_REQUIRED"
        )

    if not WEBULL_SANDBOX_APP_SECRET:
        raise WebullSandboxPreflightError(
            "SANDBOX_APP_SECRET_REQUIRED"
        )

    trade_client = build_quiet_trade_client(
        app_key=WEBULL_SANDBOX_APP_KEY,
        app_secret=WEBULL_SANDBOX_APP_SECRET,
        endpoint=SANDBOX_ENDPOINT,
    )

    try:
        response = (
            trade_client.account_v2
            .get_account_list()
        )
    except Exception as error:
        raise WebullSandboxPreflightError(
            "SANDBOX_ACCOUNT_LIST_TRANSPORT_ERROR"
        ) from error

    if getattr(
        response,
        "status_code",
        None,
    ) != 200:
        raise WebullSandboxPreflightError(
            "SANDBOX_ACCOUNT_LIST_HTTP_"
            f"{getattr(response, 'status_code', None)!r}"
        )

    try:
        payload = response.json()
    except Exception as error:
        raise WebullSandboxPreflightError(
            "SANDBOX_ACCOUNT_LIST_INVALID_JSON"
        ) from error

    return list_sandbox_accounts(
        payload
    )



def inspect_webull_sandbox_account(
    account_id: str,
):
    """
    Return a read-only snapshot for one explicitly selected
    Webull sandbox account.

    No placement, replacement, or cancellation operation is
    exposed.
    """

    selected = account_id.strip()

    if not selected:
        raise ValueError(
            "SANDBOX_ACCOUNT_ID_REQUIRED"
        )

    client = (
        WebullSandboxAccountSnapshotClient(
            account_id=selected,
            execution_mode=WEBULL_EXECUTION_MODE,
        )
    )

    return client.get_snapshot()



def build_webull_sandbox_manual_order_service(
) -> WebullSandboxManualOrderService:
    """
    Build the explicitly manual sandbox-order service.

    Unlike the read-only preflight builder, this builder passes
    the sandbox submission arming flag into the broker. Live
    modes remain rejected by the underlying execution layer.
    """

    snapshot_client = (
        WebullSandboxAccountSnapshotClient(
            account_id=(
                WEBULL_SANDBOX_ACCOUNT_ID
            ),
            execution_mode=(
                WEBULL_EXECUTION_MODE
            ),
        )
    )

    broker = WebullSandboxBroker(
        account_id=WEBULL_SANDBOX_ACCOUNT_ID,
        execution_mode=WEBULL_EXECUTION_MODE,
        submission_enabled=(
            WEBULL_SANDBOX_ORDER_SUBMISSION_ENABLED
        ),
    )

    ledger = WebullExecutionLedger(
        WEBULL_EXECUTION_LEDGER_FILE
    )

    preflight = WebullSandboxPreflight(
        snapshot_client=snapshot_client,
        broker=broker,
        ledger=ledger,
    )

    manager = WebullSandboxExecutionManager(
        broker=broker,
        ledger=ledger,
        execution_mode=WEBULL_EXECUTION_MODE,
    )

    return WebullSandboxManualOrderService(
        preflight=preflight,
        snapshot_client=snapshot_client,
        execution_manager=manager,
        submission_armed=(
            WEBULL_SANDBOX_ORDER_SUBMISSION_ENABLED
        ),
        management_armed=(
            WEBULL_SANDBOX_ORDER_MANAGEMENT_ENABLED
        ),
    )



def build_webull_sandbox_manual_close_service(
) -> WebullSandboxManualCloseService:
    """
    Build the explicitly manual sandbox reduce-only close
    service.

    Normal BUY-order submission is forced off. A new reduce-only
    SELL may only proceed through the independent sandbox order
    management arm enforced by the close service.
    """

    snapshot_client = (
        WebullSandboxAccountSnapshotClient(
            account_id=(
                WEBULL_SANDBOX_ACCOUNT_ID
            ),
            execution_mode=(
                WEBULL_EXECUTION_MODE
            ),
        )
    )

    broker = WebullSandboxBroker(
        account_id=WEBULL_SANDBOX_ACCOUNT_ID,
        execution_mode=WEBULL_EXECUTION_MODE,
        submission_enabled=False,
    )

    close_ledger = (
        WebullReduceOnlyCloseLedger()
    )

    close_manager = (
        WebullSandboxReduceOnlyCloseManager(
            broker=broker,
            ledger=close_ledger,
            snapshot_client=snapshot_client,
            execution_mode=(
                WEBULL_EXECUTION_MODE
            ),
        )
    )

    return WebullSandboxManualCloseService(
        snapshot_client=snapshot_client,
        close_manager=close_manager,
        management_armed=(
            WEBULL_SANDBOX_ORDER_MANAGEMENT_ENABLED
        ),
    )



WEBULL_TRADE_EVENTS_EVENT_QUEUE_MAXSIZE = 256
WEBULL_TRADE_EVENTS_CONTROL_QUEUE_MAXSIZE = 32


class WebullSandboxTradeEventsRuntimeError(
    RuntimeError
):
    pass


@dataclass(frozen=True)
class WebullSandboxTradeEventsRuntime:
    """
    Offline-constructible parent/worker Trade Events runtime.

    Merely constructing this object cannot open a Webull
    connection. The child supervisor must be started
    explicitly by a future lifecycle layer.
    """

    event_queue: Any
    control_queue: Any
    journal: WebullTradeEventsJournal
    health: WebullTradeEventsHealthState
    supervisor: WebullTradeEventsProcessSupervisor
    controller: WebullTradeEventsParentController


def _run_webull_trade_events_worker_entry(
    app_key: str,
    app_secret: str,
    account_ids: tuple[str, ...],
    event_queue: Any,
    control_queue: Any,
    host: str,
) -> None:
    """
    Positional multiprocessing adapter for the worker's
    keyword-only public API.
    """

    run_webull_trade_events_worker(
        app_key=app_key,
        app_secret=app_secret,
        account_ids=account_ids,
        event_queue=event_queue,
        control_queue=control_queue,
        host=host,
    )



def _build_webull_trade_events_reconcile_callback(
    *,
    preflight_factory: Callable[[], Any],
    expected_account_id: str,
) -> Callable[[], Any]:
    """
    Build a lazy Trade Events reconciliation callback.

    No preflight object and no Webull SDK client is constructed
    here. The factory is invoked only when reconciliation is
    actually required after CONNECTED.
    """

    if not callable(preflight_factory):
        raise WebullSandboxTradeEventsRuntimeError(
            "TRADE_EVENTS_PREFLIGHT_FACTORY_INVALID"
        )

    account_id = str(
        expected_account_id
    ).strip()

    if not account_id:
        raise WebullSandboxTradeEventsRuntimeError(
            "TRADE_EVENTS_SANDBOX_ACCOUNT_ID_REQUIRED"
        )

    def reconcile() -> Any:
        preflight = preflight_factory()

        reconciler = (
            WebullTradeEventsPreflightReconciler(
                preflight=preflight,
                expected_account_id=account_id,
            )
        )

        return reconciler()

    return reconcile


def build_webull_sandbox_trade_events_runtime(
    *,
    event_handler: (
        Callable[[dict[str, Any]], None]
        | None
    ) = None,
    queue_factory: (
        Callable[..., Any]
        | None
    ) = None,
    process_factory: (
        Callable[..., Any]
        | None
    ) = None,
    journal_path: (
        str | Path | None
    ) = None,
    preflight_factory: (
        Callable[[], Any]
        | None
    ) = None,
) -> WebullSandboxTradeEventsRuntime:
    """
    Assemble the Webull sandbox Trade Events runtime without
    starting it.

    Construction performs no Webull API call and cannot place,
    replace, cancel, or close an order.

    Activation is intentionally absent from this builder.
    """

    if WEBULL_EXECUTION_MODE != "SANDBOX":
        raise WebullSandboxTradeEventsRuntimeError(
            "TRADE_EVENTS_SANDBOX_MODE_REQUIRED"
        )

    if not WEBULL_SANDBOX_APP_KEY:
        raise WebullSandboxTradeEventsRuntimeError(
            "TRADE_EVENTS_SANDBOX_APP_KEY_REQUIRED"
        )

    if not WEBULL_SANDBOX_APP_SECRET:
        raise WebullSandboxTradeEventsRuntimeError(
            "TRADE_EVENTS_SANDBOX_APP_SECRET_REQUIRED"
        )

    if not WEBULL_SANDBOX_ACCOUNT_ID:
        raise WebullSandboxTradeEventsRuntimeError(
            "TRADE_EVENTS_SANDBOX_ACCOUNT_ID_REQUIRED"
        )

    if (
        event_handler is not None
        and not callable(event_handler)
    ):
        raise WebullSandboxTradeEventsRuntimeError(
            "TRADE_EVENTS_HANDLER_INVALID"
        )

    selected_preflight_factory = (
        preflight_factory
        if preflight_factory is not None
        else build_webull_sandbox_preflight
    )

    reconcile = (
        _build_webull_trade_events_reconcile_callback(
            preflight_factory=(
                selected_preflight_factory
            ),
            expected_account_id=(
                WEBULL_SANDBOX_ACCOUNT_ID
            ),
        )
    )

    if queue_factory is None:
        context = mp.get_context(
            "spawn"
        )

        queue_factory = (
            context.Queue
        )

        if process_factory is None:
            process_factory = (
                context.Process
            )

    event_queue = queue_factory(
        maxsize=(
            WEBULL_TRADE_EVENTS_EVENT_QUEUE_MAXSIZE
        )
    )

    control_queue = queue_factory(
        maxsize=(
            WEBULL_TRADE_EVENTS_CONTROL_QUEUE_MAXSIZE
        )
    )

    journal = WebullTradeEventsJournal(
        path=(
            journal_path
            if journal_path is not None
            else WEBULL_TRADE_EVENTS_JOURNAL_FILE
        )
    )

    health = (
        WebullTradeEventsHealthState()
    )

    supervisor = (
        WebullTradeEventsProcessSupervisor(
            worker_target=(
                _run_webull_trade_events_worker_entry
            ),
            worker_args=(
                WEBULL_SANDBOX_APP_KEY,
                WEBULL_SANDBOX_APP_SECRET,
                (
                    WEBULL_SANDBOX_ACCOUNT_ID,
                ),
                event_queue,
                control_queue,
                WEBULL_SANDBOX_EVENTS_HOST,
            ),
            process_factory=process_factory,
        )
    )

    controller = (
        WebullTradeEventsParentController(
            event_queue=event_queue,
            control_queue=control_queue,
            journal=journal,
            reconcile=reconcile,
            event_handler=event_handler,
            ensure_worker_healthy=(
                supervisor.ensure_healthy
            ),
            health=health,
        )
    )

    return WebullSandboxTradeEventsRuntime(
        event_queue=event_queue,
        control_queue=control_queue,
        journal=journal,
        health=health,
        supervisor=supervisor,
        controller=controller,
    )
