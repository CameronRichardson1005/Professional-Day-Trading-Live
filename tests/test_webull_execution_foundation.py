import json
import stat
from datetime import UTC, datetime
from pathlib import Path

import pytest

from trading_bot.webull_execution import (
    WebullExecutionError,
    WebullExecutionMode,
    WebullTradeIntent,
    generate_client_order_id,
    require_safe_execution_mode,
)
from trading_bot.webull_execution_ledger import (
    WebullExecutionLedger,
    WebullExecutionLedgerError,
)


NOW = datetime(
    2026,
    8,
    17,
    18,
    50,
    tzinfo=UTC,
)


def make_intent(
    client_order_id="order-1",
):
    return WebullTradeIntent(
        client_order_id=client_order_id,
        strategy_name="QUICK_FLIP",
        symbol="soun",
        side="buy",
        quantity=10,
        limit_price=6.25,
        created_at=NOW,
    )


def test_client_order_ids_are_unique():
    first = generate_client_order_id()
    second = generate_client_order_id()

    assert first != second
    assert len(first) == 32
    assert len(second) == 32


def test_live_execution_modes_are_locked():
    with pytest.raises(
        WebullExecutionError,
        match="LIVE_EXECUTION_LOCKED",
    ):
        require_safe_execution_mode(
            WebullExecutionMode.LIVE_AUTO
        )

    with pytest.raises(
        WebullExecutionError,
        match="LIVE_EXECUTION_LOCKED",
    ):
        require_safe_execution_mode(
            WebullExecutionMode.LIVE_APPROVAL
        )


def test_only_sandbox_can_submit():
    assert (
        WebullExecutionMode.SANDBOX
        .broker_submission_allowed
        is True
    )

    assert (
        WebullExecutionMode.DISABLED
        .broker_submission_allowed
        is False
    )

    assert (
        WebullExecutionMode.LIVE_AUTO
        .broker_submission_allowed
        is False
    )


def test_trade_intent_normalises_and_builds_payload():
    intent = make_intent()

    assert intent.symbol == "SOUN"
    assert intent.side == "BUY"
    assert intent.limit_price == 6.25
    assert intent.proposed_exposure == 62.50

    payload = intent.broker_payload()

    assert payload == {
        "combo_type": "NORMAL",
        "client_order_id": "order-1",
        "symbol": "SOUN",
        "instrument_type": "EQUITY",
        "market": "US",
        "order_type": "LIMIT",
        "limit_price": "6.2500",
        "quantity": "10",
        "support_trading_session": "CORE",
        "side": "BUY",
        "time_in_force": "DAY",
        "entrust_type": "QTY",
    }


def test_execution_ledger_persists_prepared_intent(
    tmp_path: Path,
):
    path = tmp_path / "execution.json"

    ledger = WebullExecutionLedger(
        path,
        clock=lambda: NOW,
    )

    record = ledger.add_intent(
        intent=make_intent(),
        execution_mode="SANDBOX",
    )

    assert record.status == "PREPARED"
    assert record.execution_mode == "SANDBOX"

    reloaded = ledger.load()

    assert reloaded["order-1"] == record

    payload = json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )

    assert payload["version"] == 1

    permissions = stat.S_IMODE(
        path.stat().st_mode
    )

    assert permissions == 0o600


def test_duplicate_client_order_id_is_rejected(
    tmp_path: Path,
):
    ledger = WebullExecutionLedger(
        tmp_path / "execution.json",
        clock=lambda: NOW,
    )

    ledger.add_intent(
        intent=make_intent(),
        execution_mode="SANDBOX",
    )

    with pytest.raises(
        WebullExecutionLedgerError,
        match="DUPLICATE_CLIENT_ORDER_ID",
    ):
        ledger.add_intent(
            intent=make_intent(),
            execution_mode="SANDBOX",
        )


def test_manual_override_prevents_silent_auto_control(
    tmp_path: Path,
):
    ledger = WebullExecutionLedger(
        tmp_path / "execution.json",
        clock=lambda: NOW,
    )

    ledger.add_intent(
        intent=make_intent(),
        execution_mode="SANDBOX",
    )

    updated = ledger.mark_manual_override(
        client_order_id="order-1",
        reason="USER_CHANGED_LIMIT_PRICE",
    )

    assert updated.manual_override is True
    assert (
        updated.manual_override_reason
        == "USER_CHANGED_LIMIT_PRICE"
    )
    assert updated.manual_override_at == NOW

    auto = ledger.return_to_auto(
        client_order_id="order-1",
    )

    assert auto.manual_override is False
    assert auto.manual_override_reason is None


def test_broker_reconciliation_state_is_durable(
    tmp_path: Path,
):
    ledger = WebullExecutionLedger(
        tmp_path / "execution.json",
        clock=lambda: NOW,
    )

    ledger.add_intent(
        intent=make_intent(),
        execution_mode="SANDBOX",
    )

    updated = ledger.record_broker_state(
        client_order_id="order-1",
        broker_order_id="broker-123",
        broker_status="PARTIAL_FILLED",
        filled_quantity=4,
        average_fill_price=6.24,
        status="PARTIALLY_FILLED",
    )

    assert updated.broker_order_id == "broker-123"
    assert updated.filled_quantity == 4
    assert updated.average_fill_price == 6.24
    assert updated.last_reconciled_at == NOW
