import json
import stat
from datetime import UTC, datetime, timedelta

import pytest

from trading_bot.webull_paper_order_store import (
    WebullPaperOrderRecord,
    WebullPaperOrderStore,
    WebullPaperOrderStoreError,
)


def record(
    *,
    paper_order_id: str = "paper-1",
    approval_reference: str = "approval-1",
    idempotency_key: str = "idem-1",
) -> WebullPaperOrderRecord:
    created_at = datetime(
        2026,
        8,
        6,
        20,
        0,
        tzinfo=UTC,
    )

    return WebullPaperOrderRecord(
        paper_order_id=paper_order_id,
        approval_reference=approval_reference,
        idempotency_key=idempotency_key,
        symbol="open",
        side="buy",
        quantity=10,
        limit_price=4.25,
        proposed_exposure=42.50,
        status="paper submitted",
        created_at=created_at,
        submitted_at=created_at + timedelta(seconds=1),
        safety_reason="APPROVED_BY_SAFETY_GATE",
    )


def test_paper_order_survives_restart(tmp_path):
    path = tmp_path / "paper-orders.json"

    WebullPaperOrderStore(path).add(record())

    restarted = WebullPaperOrderStore(path)
    stored = restarted.load()["paper-1"]

    assert stored.symbol == "OPEN"
    assert stored.side == "BUY"
    assert stored.quantity == 10
    assert stored.limit_price == 4.25
    assert stored.proposed_exposure == 42.50
    assert stored.status == "PAPER SUBMITTED"


def test_store_uses_private_permissions(tmp_path):
    path = tmp_path / "paper-orders.json"

    WebullPaperOrderStore(path).add(record())

    permissions = stat.S_IMODE(
        path.stat().st_mode
    )

    assert permissions == 0o600


def test_duplicate_idempotency_key_is_rejected(
    tmp_path,
):
    store = WebullPaperOrderStore(
        tmp_path / "paper-orders.json"
    )

    store.add(record())

    with pytest.raises(
        WebullPaperOrderStoreError,
        match="DUPLICATE_PAPER_SUBMISSION",
    ):
        store.add(
            record(
                paper_order_id="paper-2",
                approval_reference="approval-2",
            )
        )


def test_duplicate_paper_order_id_is_rejected(
    tmp_path,
):
    store = WebullPaperOrderStore(
        tmp_path / "paper-orders.json"
    )

    store.add(record())

    with pytest.raises(
        WebullPaperOrderStoreError,
        match="DUPLICATE_PAPER_ORDER_ID",
    ):
        store.add(
            record(
                idempotency_key="idem-2",
            )
        )


def test_exposure_mismatch_is_rejected(tmp_path):
    invalid = record()

    invalid = WebullPaperOrderRecord(
        **{
            **invalid.__dict__,
            "proposed_exposure": 50.0,
        }
    )

    with pytest.raises(
        WebullPaperOrderStoreError,
        match="exposure does not match",
    ):
        WebullPaperOrderStore(
            tmp_path / "paper-orders.json"
        ).add(invalid)


def test_secret_fields_in_file_fail_closed(tmp_path):
    path = tmp_path / "paper-orders.json"
    store = WebullPaperOrderStore(path)

    store.add(record())

    payload = json.loads(
        path.read_text(encoding="utf-8")
    )

    payload["records"][0][
        "approval_token"
    ] = "must-not-be-stored"

    path.write_text(
        json.dumps(payload),
        encoding="utf-8",
    )

    with pytest.raises(
        WebullPaperOrderStoreError,
        match="unsupported fields",
    ):
        store.load()


def test_serialized_file_contains_no_secrets(
    tmp_path,
):
    path = tmp_path / "paper-orders.json"

    WebullPaperOrderStore(path).add(record())

    serialized = path.read_text(
        encoding="utf-8"
    ).lower()

    assert "approval_token" not in serialized
    assert "token_hash" not in serialized
    assert "app_secret" not in serialized
    assert "account_id" not in serialized
    assert "broker_response" not in serialized


def test_submitted_time_cannot_precede_creation(
    tmp_path,
):
    invalid = record()

    invalid = WebullPaperOrderRecord(
        **{
            **invalid.__dict__,
            "submitted_at": (
                invalid.created_at
                - timedelta(seconds=1)
            ),
        }
    )

    with pytest.raises(
        WebullPaperOrderStoreError,
        match="cannot precede",
    ):
        WebullPaperOrderStore(
            tmp_path / "paper-orders.json"
        ).add(invalid)


def test_strategy_metadata_survives_restart(
    tmp_path,
):
    path = tmp_path / "paper-orders.json"

    enriched = record()

    enriched = WebullPaperOrderRecord(
        **{
            **enriched.__dict__,
            "strategy_name": "FIBONACCI_61_8",
            "reward_risk": 2.25,
            "confirmation_time": "10:07",
            "retracement_price": 4.24,
            "impulse_atr_multiple": 0.82,
            "pullback_volume_ratio": 0.61,
        }
    )

    WebullPaperOrderStore(path).add(enriched)

    stored = WebullPaperOrderStore(
        path
    ).load()["paper-1"]

    assert stored.strategy_name == "FIBONACCI_61_8"
    assert stored.reward_risk == 2.25
    assert stored.confirmation_time == "10:07"
    assert stored.retracement_price == 4.24
    assert stored.impulse_atr_multiple == 0.82
    assert stored.pullback_volume_ratio == 0.61


def test_legacy_paper_order_has_empty_strategy_metadata(
    tmp_path,
):
    path = tmp_path / "paper-orders.json"

    WebullPaperOrderStore(path).add(record())

    stored = WebullPaperOrderStore(
        path
    ).load()["paper-1"]

    assert stored.strategy_name is None
    assert stored.reward_risk is None
    assert stored.confirmation_time is None
    assert stored.retracement_price is None
    assert stored.impulse_atr_multiple is None
    assert stored.pullback_volume_ratio is None
