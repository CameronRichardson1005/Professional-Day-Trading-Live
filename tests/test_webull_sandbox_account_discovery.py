from types import SimpleNamespace

import pytest

import main as main_module

from trading_bot.webull_sandbox_preflight import (
    WebullSandboxPreflightError,
    list_sandbox_accounts,
)


def test_lists_multiple_sandbox_accounts():
    accounts = list_sandbox_accounts([
        {
            "account_id": "sandbox-1",
            "account_type": "CASH",
        },
        {
            "account_id": "sandbox-2",
            "account_type": "MARGIN",
        },
    ])

    assert len(accounts) == 2

    assert (
        accounts[0].account_id
        == "sandbox-1"
    )

    assert (
        accounts[0].account_type
        == "CASH"
    )

    assert (
        accounts[1].account_id
        == "sandbox-2"
    )


def test_duplicate_account_id_fails_closed():
    with pytest.raises(
        WebullSandboxPreflightError,
        match="DUPLICATE_SANDBOX_ACCOUNT_ID",
    ):
        list_sandbox_accounts([
            {
                "account_id": "same",
                "account_type": "CASH",
            },
            {
                "account_id": "same",
                "account_type": "CASH",
            },
        ])


def test_account_discovery_cli_succeeds(
    monkeypatch,
    capsys,
):
    monkeypatch.setattr(
        main_module,
        "setup_logging",
        lambda: "test.log",
    )

    monkeypatch.setattr(
        main_module,
        "discover_webull_sandbox_accounts",
        lambda: (
            SimpleNamespace(
                account_id="sandbox-1",
                account_type="CASH",
            ),
            SimpleNamespace(
                account_id="sandbox-2",
                account_type="MARGIN",
            ),
        ),
    )

    monkeypatch.setattr(
        main_module.sys,
        "argv",
        [
            "main.py",
            "webull-sandbox-accounts",
        ],
    )

    result = main_module.main()

    output = capsys.readouterr().out

    assert result == 0

    assert (
        "WEBULL SANDBOX ACCOUNTS"
        in output
    )

    assert (
        "sandbox-1 (CASH)"
        in output
    )

    assert (
        "sandbox-2 (MARGIN)"
        in output
    )

    assert (
        "NO WEBULL ORDER WAS PLACED, "
        "MODIFIED, OR CANCELLED"
        in output
    )


def test_account_discovery_runs_before_bot(
    monkeypatch,
):
    monkeypatch.setattr(
        main_module,
        "setup_logging",
        lambda: "test.log",
    )

    monkeypatch.setattr(
        main_module,
        "discover_webull_sandbox_accounts",
        lambda: (
            SimpleNamespace(
                account_id="sandbox-1",
                account_type="CASH",
            ),
        ),
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
            "webull-sandbox-accounts",
        ],
    )

    assert main_module.main() == 0
