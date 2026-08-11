from trading_bot.webull_account_diagnostic import (
    format_account_diagnostic,
    run_diagnostic,
)
from trading_bot.webull_account_snapshot import (
    WebullAccountSnapshotError,
)
from trading_bot.webull_safety import (
    WebullAccountState,
)


class FakeSnapshotClient:
    def __init__(self, state):
        self.state = state
        self.calls = 0

    def get_account_state(self):
        self.calls += 1
        return self.state


class FailingSnapshotClient:
    def get_account_state(self):
        raise WebullAccountSnapshotError(
            "strict validation failed"
        )


def cash_state(
    *,
    available_cash=1000.0,
    position_exposure=0.0,
    open_buy_order_exposure=0.0,
):
    return WebullAccountState(
        account_type="CASH",
        available_cash=available_cash,
        position_exposure=position_exposure,
        open_buy_order_exposure=(
            open_buy_order_exposure
        ),
        data_is_current=True,
    )


def test_formats_redacted_cash_account_summary():
    output = format_account_diagnostic(
        cash_state(
            available_cash=1000.0,
            position_exposure=100.0,
            open_buy_order_exposure=50.0,
        )
    )

    assert "Account type: CASH" in output
    assert "Available cash: $1,000.00" in output
    assert "Position exposure: $100.00" in output
    assert "Open-buy exposure: $50.00" in output
    assert "Current total exposure: $150.00" in output
    assert (
        "Remaining operational allowance: $325.00"
        in output
    )
    assert "Real order submission enabled: NO" in output
    assert "Preview safety status: ELIGIBLE" in output
    assert "NO ORDERS SUBMITTED OR MODIFIED" in output


def test_margin_account_is_reported_as_blocked():
    output = format_account_diagnostic(
        WebullAccountState(
            account_type="MARGIN",
            available_cash=1000.0,
            position_exposure=0.0,
            open_buy_order_exposure=0.0,
            data_is_current=True,
        )
    )

    assert "Cash account confirmed: NO" in output
    assert "Preview safety status: BLOCKED" in output


def test_operational_cap_blocks_preview_status():
    output = format_account_diagnostic(
        cash_state(
            position_exposure=475.0,
        )
    )

    assert (
        "Remaining operational allowance: $0.00"
        in output
    )
    assert "Preview safety status: BLOCKED" in output


def test_diagnostic_reads_snapshot_once(capsys):
    client = FakeSnapshotClient(
        cash_state()
    )

    result = run_diagnostic(client)
    output = capsys.readouterr().out

    assert result == 0
    assert client.calls == 1
    assert "Account type: CASH" in output
    assert "Real order submission enabled: NO" in output


def test_diagnostic_failure_is_fail_closed(capsys):
    result = run_diagnostic(
        FailingSnapshotClient()
    )
    output = capsys.readouterr().out

    assert result == 1
    assert "Status: BLOCKED" in output
    assert "strict validation failed" in output
    assert "NO ORDERS SUBMITTED OR MODIFIED" in output


def test_output_does_not_include_account_identifier():
    output = format_account_diagnostic(
        cash_state()
    )

    assert "account_id" not in output.lower()
    assert "account-1" not in output.lower()
