from __future__ import annotations

from .config import (
    WEBULL_EXECUTION_LEDGER_FILE,
    WEBULL_EXECUTION_MODE,
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
