from datetime import UTC, datetime

import pytest

from trading_bot.webull_execution import (
    WebullTradeIntent,
)
from trading_bot.webull_execution_ledger import (
    WebullExecutionLedger,
    WebullExecutionLedgerError,
)


NOW = datetime(
    2026,
    8,
    17,
    20,
    0,
    tzinfo=UTC,
)


def make_intent():
    return WebullTradeIntent(
        client_order_id="replace-ledger-1",
        strategy_name="MANUAL_SANDBOX_TEST",
        symbol="SOUN",
        side="BUY",
        quantity=1,
        limit_price=5.00,
        created_at=NOW,
    )


def make_ledger(tmp_path):
    return WebullExecutionLedger(
        tmp_path / "execution.json",
        clock=lambda: NOW,
    )


def test_replace_request_persists_round_trip(
    tmp_path,
):
    ledger = make_ledger(tmp_path)

    ledger.add_intent(
        intent=make_intent(),
        execution_mode="SANDBOX",
    )

    ledger.mark_replace_requested(
        client_order_id="replace-ledger-1",
        quantity=2,
        limit_price=5.10,
    )

    record = ledger.load()[
        "replace-ledger-1"
    ]

    assert record.status == "REPLACE_PENDING"
    assert record.replace_requested_quantity == 2
    assert record.replace_requested_limit_price == 5.10
    assert record.replace_requested_at == NOW


def test_replace_request_can_be_cleared(
    tmp_path,
):
    ledger = make_ledger(tmp_path)

    ledger.add_intent(
        intent=make_intent(),
        execution_mode="SANDBOX",
    )

    ledger.mark_replace_requested(
        client_order_id="replace-ledger-1",
        quantity=2,
        limit_price=5.10,
    )

    ledger.clear_replace_request(
        client_order_id="replace-ledger-1"
    )

    record = ledger.load()[
        "replace-ledger-1"
    ]

    assert record.replace_requested_quantity is None
    assert record.replace_requested_limit_price is None
    assert record.replace_requested_at is None


def test_incomplete_replace_request_fails_closed(
    tmp_path,
):
    ledger = make_ledger(tmp_path)

    ledger.add_intent(
        intent=make_intent(),
        execution_mode="SANDBOX",
    )

    with pytest.raises(
        WebullExecutionLedgerError,
        match="INCOMPLETE_REPLACE_REQUEST",
    ):
        ledger._replace_record(
            "replace-ledger-1",
            replace_requested_quantity=2,
        )
