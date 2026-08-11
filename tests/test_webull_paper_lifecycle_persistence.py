import json
from datetime import UTC, datetime

from trading_bot.webull_paper_order_store import (
    WebullPaperOrderRecord,
    WebullPaperOrderStore,
)


def test_lifecycle_prices_survive_restart(tmp_path):
    path = tmp_path / "paper-orders.json"
    store = WebullPaperOrderStore(path)

    now = datetime(
        2026,
        8,
        7,
        15,
        0,
        tzinfo=UTC,
    )

    store.add(
        WebullPaperOrderRecord(
            paper_order_id="paper-1",
            approval_reference="approval-1",
            idempotency_key="idem-1",
            symbol="OPEN",
            side="BUY",
            quantity=10,
            limit_price=4.25,
            proposed_exposure=42.50,
            status="PAPER SUBMITTED",
            created_at=now,
            submitted_at=now,
            safety_reason="APPROVED",
            target_price=4.60,
            stop_price=4.10,
            lifecycle_status="ENTRY PENDING",
        )
    )

    restarted = WebullPaperOrderStore(path)
    record = restarted.load()["paper-1"]

    assert record.target_price == 4.60
    assert record.stop_price == 4.10
    assert record.lifecycle_status == "ENTRY PENDING"


def test_legacy_paper_order_loads_as_entry_pending(
    tmp_path,
):
    path = tmp_path / "paper-orders.json"

    path.write_text(
        json.dumps({
            "version": 1,
            "records": [{
                "paper_order_id": "legacy-1",
                "approval_reference": "approval-1",
                "idempotency_key": "idem-1",
                "symbol": "OPEN",
                "side": "BUY",
                "quantity": 10,
                "limit_price": 4.25,
                "proposed_exposure": 42.50,
                "status": "PAPER SUBMITTED",
                "created_at": "2026-08-06T20:00:00Z",
                "submitted_at": "2026-08-06T20:00:01Z",
                "safety_reason": "APPROVED",
            }],
        }),
        encoding="utf-8",
    )

    record = WebullPaperOrderStore(
        path
    ).load()["legacy-1"]

    assert record.target_price is None
    assert record.stop_price is None
    assert record.lifecycle_status == "ENTRY PENDING"


def test_serialized_lifecycle_contains_no_secrets(
    tmp_path,
):
    path = tmp_path / "paper-orders.json"
    store = WebullPaperOrderStore(path)

    now = datetime(
        2026,
        8,
        7,
        15,
        0,
        tzinfo=UTC,
    )

    store.add(
        WebullPaperOrderRecord(
            paper_order_id="paper-1",
            approval_reference="approval-1",
            idempotency_key="idem-1",
            symbol="OPEN",
            side="BUY",
            quantity=10,
            limit_price=4.25,
            proposed_exposure=42.50,
            status="PAPER SUBMITTED",
            created_at=now,
            submitted_at=now,
            safety_reason="APPROVED",
            target_price=4.60,
            stop_price=4.10,
        )
    )

    serialized = path.read_text(
        encoding="utf-8"
    ).lower()

    assert "target_price" in serialized
    assert "stop_price" in serialized
    assert "lifecycle_status" in serialized

    assert "approval_token" not in serialized
    assert "token_hash" not in serialized
    assert "app_secret" not in serialized
    assert "account_id" not in serialized
