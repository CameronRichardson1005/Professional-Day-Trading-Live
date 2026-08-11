import sys
from unittest.mock import patch

import main


class FakeBot:
    def __init__(self):
        self.calls = []

    def confirm_webull_approval(
        self,
        *,
        approval_id,
        approval_token,
    ):
        self.calls.append({
            "approval_id": approval_id,
            "approval_token": approval_token,
        })

        return "APPROVED"


def printed_text(mock_print):
    return "\n".join(
        " ".join(str(value) for value in call.args)
        for call in mock_print.call_args_list
    )


def test_cli_confirms_approval_without_printing_token():
    bot = FakeBot()

    with (
        patch.object(
            sys,
            "argv",
            [
                "main.py",
                "webull-approval-confirm",
                "approval-1",
            ],
        ),
        patch.object(
            main,
            "TradingBot",
            return_value=bot,
        ),
        patch.object(
            main.getpass,
            "getpass",
            return_value="secret-token",
        ),
        patch("builtins.print") as mock_print,
    ):
        result = main.main()

    output = printed_text(mock_print)

    assert result == 0
    assert bot.calls == [{
        "approval_id": "approval-1",
        "approval_token": "secret-token",
    }]
    assert "WEBULL APPROVAL CONFIRMED" in output
    assert "Status: APPROVED" in output
    assert (
        "NO WEBULL BROKER ORDER WAS SUBMITTED"
        in output
    )
    assert "secret-token" not in output


def test_cli_confirmation_requires_approval_id():
    with (
        patch.object(
            sys,
            "argv",
            [
                "main.py",
                "webull-approval-confirm",
            ],
        ),
        patch("builtins.print") as mock_print,
    ):
        result = main.main()

    output = printed_text(mock_print)

    assert result == 2
    assert (
        "Usage: python main.py "
        "webull-approval-confirm APPROVAL_ID"
        in output
    )
