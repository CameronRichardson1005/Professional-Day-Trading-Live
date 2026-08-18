from types import SimpleNamespace

import pytest

from trading_bot.webull_trade_events_reconciliation import (
    WebullTradeEventsPreflightReconciler,
    WebullTradeEventsReconciliationError,
)


class FakePreflight:
    def __init__(
        self,
        *,
        report=None,
        error=None,
    ):
        self.report = report
        self.error = error
        self.run_calls = 0

    def run(self):
        self.run_calls += 1

        if self.error is not None:
            raise self.error

        return self.report


def allowed_report(
    *,
    account_id="sandbox-account",
    active_manual_overrides=0,
    reconciled_orders=0,
):
    return SimpleNamespace(
        allowed=True,
        reason="OK",
        account_id=account_id,
        available_cash=500.0,
        current_exposure=0.0,
        reconciled_orders=(
            reconciled_orders
        ),
        active_manual_overrides=(
            active_manual_overrides
        ),
        open_orders=0,
    )


def test_construction_does_not_run_preflight():
    preflight = FakePreflight(
        report=allowed_report()
    )

    WebullTradeEventsPreflightReconciler(
        preflight=preflight,
        expected_account_id=(
            "sandbox-account"
        ),
    )

    assert preflight.run_calls == 0


def test_allowed_preflight_returns_report():
    report = allowed_report(
        reconciled_orders=2
    )

    preflight = FakePreflight(
        report=report
    )

    reconciler = (
        WebullTradeEventsPreflightReconciler(
            preflight=preflight,
            expected_account_id=(
                "sandbox-account"
            ),
        )
    )

    result = reconciler()

    assert result is report
    assert preflight.run_calls == 1
    assert result.reconciled_orders == 2


def test_preflight_exception_fails_closed():
    preflight = FakePreflight(
        error=RuntimeError(
            "broker unavailable"
        )
    )

    reconciler = (
        WebullTradeEventsPreflightReconciler(
            preflight=preflight,
            expected_account_id=(
                "sandbox-account"
            ),
        )
    )

    with pytest.raises(
        WebullTradeEventsReconciliationError,
        match=(
            "TRADE_EVENTS_PREFLIGHT_FAILED"
        ),
    ):
        reconciler()


def test_not_allowed_report_fails_closed():
    report = allowed_report()

    report.allowed = False
    report.reason = "RISK_BLOCKED"

    preflight = FakePreflight(
        report=report
    )

    reconciler = (
        WebullTradeEventsPreflightReconciler(
            preflight=preflight,
            expected_account_id=(
                "sandbox-account"
            ),
        )
    )

    with pytest.raises(
        WebullTradeEventsReconciliationError,
        match=(
            "TRADE_EVENTS_PREFLIGHT_NOT_ALLOWED:"
            "RISK_BLOCKED"
        ),
    ):
        reconciler()


def test_account_mismatch_fails_closed():
    preflight = FakePreflight(
        report=allowed_report(
            account_id="wrong-account"
        )
    )

    reconciler = (
        WebullTradeEventsPreflightReconciler(
            preflight=preflight,
            expected_account_id=(
                "sandbox-account"
            ),
        )
    )

    with pytest.raises(
        WebullTradeEventsReconciliationError,
        match=(
            "TRADE_EVENTS_PREFLIGHT_ACCOUNT_MISMATCH"
        ),
    ):
        reconciler()


def test_active_manual_override_fails_closed():
    preflight = FakePreflight(
        report=allowed_report(
            active_manual_overrides=1
        )
    )

    reconciler = (
        WebullTradeEventsPreflightReconciler(
            preflight=preflight,
            expected_account_id=(
                "sandbox-account"
            ),
        )
    )

    with pytest.raises(
        WebullTradeEventsReconciliationError,
        match=(
            "TRADE_EVENTS_ACTIVE_MANUAL_OVERRIDES"
        ),
    ):
        reconciler()


def test_invalid_report_fails_closed():
    preflight = FakePreflight(
        report=SimpleNamespace(
            allowed=True,
            reason="OK",
            account_id=(
                "sandbox-account"
            ),
            active_manual_overrides=0,
            reconciled_orders=None,
        )
    )

    reconciler = (
        WebullTradeEventsPreflightReconciler(
            preflight=preflight,
            expected_account_id=(
                "sandbox-account"
            ),
        )
    )

    with pytest.raises(
        WebullTradeEventsReconciliationError,
        match=(
            "TRADE_EVENTS_PREFLIGHT_REPORT_INVALID"
        ),
    ):
        reconciler()
