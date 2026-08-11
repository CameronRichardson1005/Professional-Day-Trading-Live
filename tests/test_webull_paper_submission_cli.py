import sys
from dataclasses import dataclass
from unittest.mock import patch

import main


@dataclass(frozen=True)
class FakePaperOrder:
    paper_order_id: str = "paper-1"
    symbol: str = "OPEN"
    side: str = "BUY"
    quantity: int = 10
    limit_price: float = 4.25
    proposed_exposure: float = 42.50
    status: str = "PAPER SUBMITTED"
    safety_reason: str = "APPROVED_BY_SAFETY_GATE"


class FakeBot:
    def __init__(self):
        self.calls = []

    def submit_webull_paper_order(
        self,
        *,
        symbol,
        approval_id,
        approval_token,
    ):
        self.calls.append({
            "symbol": symbol,
            "approval_id": approval_id,
            "approval_token": approval_token,
        })

        return FakePaperOrder()


def printed_text(mock_print):
    return "\n".join(
        " ".join(str(value) for value in call.args)
        for call in mock_print.call_args_list
    )


def test_cli_records_local_paper_order():
    bot = FakeBot()

    with (
        patch.object(
            sys,
            "argv",
            [
                "main.py",
                "webull-paper-submit",
                "OPEN",
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
        "symbol": "OPEN",
        "approval_id": "approval-1",
        "approval_token": "secret-token",
    }]
    assert "WEBULL PAPER ORDER RECORDED" in output
    assert "LOCAL PAPER LEDGER ONLY" in output
    assert (
        "NO WEBULL BROKER ORDER WAS SUBMITTED"
        in output
    )
    assert "secret-token" not in output


def test_cli_requires_all_arguments():
    with (
        patch.object(
            sys,
            "argv",
            [
                "main.py",
                "webull-paper-submit",
                "OPEN",
            ],
        ),
        patch("builtins.print") as mock_print,
    ):
        result = main.main()

    output = printed_text(mock_print)

    assert result == 2
    assert (
        "Usage: python main.py webull-paper-submit "
        "SYMBOL APPROVAL_ID"
        in output
    )
