from __future__ import annotations

from .config import (
    WEBULL_EXECUTION_LEDGER_FILE,
    WEBULL_EXECUTION_MODE,
    WEBULL_SANDBOX_ACCOUNT_ID,
)
from .webull_execution_ledger import (
    WebullExecutionLedger,
)
from .webull_sandbox_broker import (
    WebullSandboxBroker,
)
from .webull_sandbox_preflight import (
    WebullSandboxAccountSnapshotClient,
    WebullSandboxPreflight,
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
