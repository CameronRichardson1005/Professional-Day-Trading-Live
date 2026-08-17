from types import SimpleNamespace

import main as main_module


def test_account_status_cli_is_read_only(
    monkeypatch,
    capsys,
):
    snapshot = SimpleNamespace(
        account_id="sandbox-cash",
        position_count=2,
        open_order_count=1,
        account_state=SimpleNamespace(
            account_type="CASH",
            available_cash=25000.0,
            buying_power=25000.0,
            position_exposure=500.0,
            open_buy_order_exposure=100.0,
            current_total_exposure=600.0,
        ),
    )

    monkeypatch.setattr(
        main_module,
        "setup_logging",
        lambda: "test.log",
    )

    monkeypatch.setattr(
        main_module,
        "inspect_webull_sandbox_account",
        lambda account_id: snapshot,
    )

    monkeypatch.setattr(
        main_module.sys,
        "argv",
        [
            "main.py",
            "webull-sandbox-account-status",
            "sandbox-cash",
        ],
    )

    result = main_module.main()
    output = capsys.readouterr().out

    assert result == 0
    assert "Type: CASH" in output
    assert "Available cash: $25000.00" in output
    assert "Positions: 2" in output
    assert "Open orders: 1" in output

    assert (
        "NO WEBULL ORDER WAS PLACED, "
        "MODIFIED, OR CANCELLED"
        in output
    )


def test_account_status_runs_before_trading_bot(
    monkeypatch,
):
    snapshot = SimpleNamespace(
        account_id="sandbox-cash",
        position_count=0,
        open_order_count=0,
        account_state=SimpleNamespace(
            account_type="CASH",
            available_cash=25000.0,
            buying_power=25000.0,
            position_exposure=0.0,
            open_buy_order_exposure=0.0,
            current_total_exposure=0.0,
        ),
    )

    monkeypatch.setattr(
        main_module,
        "setup_logging",
        lambda: "test.log",
    )

    monkeypatch.setattr(
        main_module,
        "inspect_webull_sandbox_account",
        lambda account_id: snapshot,
    )

    class ForbiddenTradingBot:
        def __init__(self):
            raise AssertionError(
                "TradingBot must not be constructed."
            )

    monkeypatch.setattr(
        main_module,
        "TradingBot",
        ForbiddenTradingBot,
    )

    monkeypatch.setattr(
        main_module.sys,
        "argv",
        [
            "main.py",
            "webull-sandbox-account-status",
            "sandbox-cash",
        ],
    )

    assert main_module.main() == 0
