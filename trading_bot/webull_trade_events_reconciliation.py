from __future__ import annotations

from typing import Any


class WebullTradeEventsReconciliationError(
    RuntimeError
):
    pass


class WebullTradeEventsPreflightReconciler:
    """
    Read-only broker reconciliation adapter for Trade Events.

    The underlying WebullSandboxPreflight may update the local
    execution ledger with authoritative broker state, but it
    cannot place, replace, cancel, or close broker orders.

    Trade Events may become trusted only after this callable
    returns successfully.
    """

    def __init__(
        self,
        *,
        preflight: Any,
        expected_account_id: str,
    ) -> None:
        if not hasattr(
            preflight,
            "run",
        ) or not callable(
            preflight.run
        ):
            raise WebullTradeEventsReconciliationError(
                "TRADE_EVENTS_PREFLIGHT_INVALID"
            )

        account_id = str(
            expected_account_id
        ).strip()

        if not account_id:
            raise WebullTradeEventsReconciliationError(
                "TRADE_EVENTS_ACCOUNT_ID_REQUIRED"
            )

        self.preflight = preflight
        self.expected_account_id = account_id

    def __call__(
        self,
    ) -> Any:
        try:
            report = self.preflight.run()
        except Exception as error:
            raise WebullTradeEventsReconciliationError(
                "TRADE_EVENTS_PREFLIGHT_FAILED"
            ) from error

        if report is None:
            raise WebullTradeEventsReconciliationError(
                "TRADE_EVENTS_PREFLIGHT_REPORT_INVALID"
            )

        allowed = getattr(
            report,
            "allowed",
            None,
        )

        if allowed is not True:
            reason = str(
                getattr(
                    report,
                    "reason",
                    "",
                )
            ).strip()

            if not reason:
                reason = "UNKNOWN"

            raise WebullTradeEventsReconciliationError(
                "TRADE_EVENTS_PREFLIGHT_NOT_ALLOWED:"
                f"{reason}"
            )

        account_id = str(
            getattr(
                report,
                "account_id",
                "",
            )
        ).strip()

        if (
            account_id
            != self.expected_account_id
        ):
            raise WebullTradeEventsReconciliationError(
                "TRADE_EVENTS_PREFLIGHT_ACCOUNT_MISMATCH"
            )

        active_manual_overrides = getattr(
            report,
            "active_manual_overrides",
            None,
        )

        if (
            isinstance(
                active_manual_overrides,
                bool,
            )
            or not isinstance(
                active_manual_overrides,
                int,
            )
            or active_manual_overrides < 0
        ):
            raise WebullTradeEventsReconciliationError(
                "TRADE_EVENTS_PREFLIGHT_REPORT_INVALID"
            )

        if active_manual_overrides != 0:
            raise WebullTradeEventsReconciliationError(
                "TRADE_EVENTS_ACTIVE_MANUAL_OVERRIDES"
            )

        reconciled_orders = getattr(
            report,
            "reconciled_orders",
            None,
        )

        if (
            isinstance(
                reconciled_orders,
                bool,
            )
            or not isinstance(
                reconciled_orders,
                int,
            )
            or reconciled_orders < 0
        ):
            raise WebullTradeEventsReconciliationError(
                "TRADE_EVENTS_PREFLIGHT_REPORT_INVALID"
            )

        return report
