from __future__ import annotations

from .config import (
    WEBULL_MAX_TOTAL_EXPOSURE_DOLLARS,
    WEBULL_OPERATIONAL_EXPOSURE_CAP_DOLLARS,
    WEBULL_ORDER_SUBMISSION_ENABLED,
    WEBULL_REQUIRE_MANUAL_APPROVAL,
)
from .webull_account_snapshot import (
    WebullAccountSnapshotClient,
    WebullAccountSnapshotError,
)
from .webull_safety import WebullAccountState


def format_account_diagnostic(
    state: WebullAccountState,
) -> str:
    remaining_operational = round(
        max(
            0.0,
            WEBULL_OPERATIONAL_EXPOSURE_CAP_DOLLARS
            - state.current_total_exposure,
        ),
        2,
    )

    remaining_hard = round(
        max(
            0.0,
            WEBULL_MAX_TOTAL_EXPOSURE_DOLLARS
            - state.current_total_exposure,
        ),
        2,
    )

    safe_for_preview = (
        state.data_is_current
        and state.account_type.strip().upper() == "CASH"
        and state.available_cash > 0
        and remaining_operational > 0
    )

    lines = [
        "WEBULL READ-ONLY ACCOUNT DIAGNOSTIC",
        "-----------------------------------",
        f"Account type: {state.account_type}",
        f"Available cash: ${state.available_cash:,.2f}",
        (
            "Position exposure: "
            f"${state.position_exposure:,.2f}"
        ),
        (
            "Open-buy exposure: "
            f"${state.open_buy_order_exposure:,.2f}"
        ),
        (
            "Current total exposure: "
            f"${state.current_total_exposure:,.2f}"
        ),
        (
            "Operational exposure cap: "
            f"${WEBULL_OPERATIONAL_EXPOSURE_CAP_DOLLARS:,.2f}"
        ),
        (
            "Hard exposure cap: "
            f"${WEBULL_MAX_TOTAL_EXPOSURE_DOLLARS:,.2f}"
        ),
        (
            "Remaining operational allowance: "
            f"${remaining_operational:,.2f}"
        ),
        (
            "Remaining hard-cap allowance: "
            f"${remaining_hard:,.2f}"
        ),
        (
            "Account data current: "
            f"{'YES' if state.data_is_current else 'NO'}"
        ),
        (
            "Cash account confirmed: "
            f"{'YES' if state.account_type.strip().upper() == 'CASH' else 'NO'}"
        ),
        (
            "Manual approval required: "
            f"{'YES' if WEBULL_REQUIRE_MANUAL_APPROVAL else 'NO'}"
        ),
        (
            "Real order submission enabled: "
            f"{'YES' if WEBULL_ORDER_SUBMISSION_ENABLED else 'NO'}"
        ),
        (
            "Preview safety status: "
            f"{'ELIGIBLE' if safe_for_preview else 'BLOCKED'}"
        ),
        "",
        "READ ONLY — NO ORDERS SUBMITTED OR MODIFIED",
    ]

    return "\n".join(lines)


def run_diagnostic(
    snapshot_client: (
        WebullAccountSnapshotClient | None
    ) = None,
) -> int:
    client = (
        snapshot_client
        or WebullAccountSnapshotClient()
    )

    try:
        state = client.get_account_state()
    except WebullAccountSnapshotError as error:
        print("WEBULL READ-ONLY ACCOUNT DIAGNOSTIC")
        print("-----------------------------------")
        print("Status: BLOCKED")
        print(f"Reason: {error}")
        print("")
        print(
            "READ ONLY — NO ORDERS SUBMITTED OR MODIFIED"
        )
        return 1
    except Exception as error:
        print("WEBULL READ-ONLY ACCOUNT DIAGNOSTIC")
        print("-----------------------------------")
        print("Status: BLOCKED")
        print(
            "Reason: unexpected read-only account "
            f"lookup failure: {error}"
        )
        print("")
        print(
            "READ ONLY — NO ORDERS SUBMITTED OR MODIFIED"
        )
        return 1

    print(format_account_diagnostic(state))
    return 0


if __name__ == "__main__":
    raise SystemExit(run_diagnostic())
