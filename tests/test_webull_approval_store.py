import json
import stat
from datetime import UTC, datetime

import pytest

from trading_bot.webull_approval_store import (
    StoredApprovalRecord,
    WebullApprovalStore,
    WebullApprovalStoreError,
)


def record(
    approval_id="approval-1",
):
    return StoredApprovalRecord(
        approval_id=approval_id,
        token_hash="hashed-token",
        proposal_fingerprint="fingerprint",
        symbol="OPEN",
        quantity=10,
        limit_price=4.0,
        proposed_exposure=40.0,
        created_at=datetime(
            2026,
            8,
            6,
            14,
            0,
            tzinfo=UTC,
        ),
        expires_at=datetime(
            2026,
            8,
            6,
            14,
            5,
            tzinfo=UTC,
        ),
        status="PENDING",
    )


def test_missing_store_loads_empty(tmp_path):
    store = WebullApprovalStore(
        tmp_path / "approvals.json"
    )

    assert store.load() == {}


def test_round_trip_preserves_record(tmp_path):
    store = WebullApprovalStore(
        tmp_path / "approvals.json"
    )

    original = record()

    store.save({
        original.approval_id: original
    })

    loaded = store.load()

    assert loaded == {
        original.approval_id: original
    }


def test_plain_token_is_never_written(tmp_path):
    path = tmp_path / "approvals.json"
    store = WebullApprovalStore(path)

    stored = record()

    store.save({
        stored.approval_id: stored
    })

    text = path.read_text(
        encoding="utf-8"
    )

    assert "hashed-token" in text
    assert "approval_token" not in text
    assert "plain-secret-token" not in text


def test_store_permissions_are_owner_only(tmp_path):
    path = tmp_path / "approvals.json"
    store = WebullApprovalStore(path)

    stored = record()

    store.save({
        stored.approval_id: stored
    })

    mode = stat.S_IMODE(
        path.stat().st_mode
    )

    assert mode == 0o600


def test_atomic_temp_file_is_removed(tmp_path):
    path = tmp_path / "approvals.json"
    store = WebullApprovalStore(path)

    stored = record()

    store.save({
        stored.approval_id: stored
    })

    assert not (
        tmp_path / "approvals.json.tmp"
    ).exists()


def test_corrupt_json_fails_closed(tmp_path):
    path = tmp_path / "approvals.json"
    path.write_text(
        "{not-json",
        encoding="utf-8",
    )

    store = WebullApprovalStore(path)

    with pytest.raises(
        WebullApprovalStoreError,
        match="could not be read",
    ):
        store.load()


def test_unknown_version_fails_closed(tmp_path):
    path = tmp_path / "approvals.json"
    path.write_text(
        json.dumps({
            "version": 999,
            "records": [],
        }),
        encoding="utf-8",
    )

    store = WebullApprovalStore(path)

    with pytest.raises(
        WebullApprovalStoreError,
        match="Unsupported",
    ):
        store.load()


def test_duplicate_ids_fail_closed(tmp_path):
    path = tmp_path / "approvals.json"
    raw = WebullApprovalStore._serialize_record(
        record()
    )

    path.write_text(
        json.dumps({
            "version": 1,
            "records": [
                raw,
                raw,
            ],
        }),
        encoding="utf-8",
    )

    store = WebullApprovalStore(path)

    with pytest.raises(
        WebullApprovalStoreError,
        match="Duplicate approval ID",
    ):
        store.load()


def test_invalid_quantity_fails_closed(tmp_path):
    path = tmp_path / "approvals.json"
    raw = WebullApprovalStore._serialize_record(
        record()
    )
    raw["quantity"] = 0

    path.write_text(
        json.dumps({
            "version": 1,
            "records": [raw],
        }),
        encoding="utf-8",
    )

    store = WebullApprovalStore(path)

    with pytest.raises(
        WebullApprovalStoreError,
        match="quantity must be positive",
    ):
        store.load()
