import json
import os
from datetime import UTC, datetime

import pytest

from trading_bot.webull_preview_store import (
    WebullPreviewStore,
    WebullPreviewStoreError,
)


def preview():
    return {
        "symbol": "OPEN",
        "quantity": 10,
        "limitPrice": 4.25,
        "targetPrice": 4.60,
        "tradingStopPrice": 4.10,
        "proposedExposure": 42.5,
        "status": "PREVIEW READY",
        "createdAt": datetime(
            2026,
            8,
            6,
            18,
            30,
            tzinfo=UTC,
        ).isoformat(),
    }


def test_preview_survives_restart(tmp_path):
    path = tmp_path / "previews.json"

    WebullPreviewStore(path).save_previews([
        preview()
    ])

    restarted = WebullPreviewStore(path)

    stored = restarted.load_preview("open")

    assert stored is not None
    assert stored["symbol"] == "OPEN"
    assert stored["quantity"] == 10
    assert stored["limitPrice"] == 4.25
    assert stored["proposedExposure"] == 42.5


def test_store_file_is_private(tmp_path):
    path = tmp_path / "previews.json"

    WebullPreviewStore(path).save_previews([
        preview()
    ])

    assert os.stat(path).st_mode & 0o777 == 0o600


def test_rejects_sensitive_fields(tmp_path):
    unsafe = preview()
    unsafe["approvalToken"] = "secret"

    with pytest.raises(
        WebullPreviewStoreError,
        match="unsupported fields",
    ):
        WebullPreviewStore(
            tmp_path / "previews.json"
        ).save_previews([unsafe])


def test_rejects_exposure_mismatch(tmp_path):
    invalid = preview()
    invalid["proposedExposure"] = 99.0

    with pytest.raises(
        WebullPreviewStoreError,
        match="does not match",
    ):
        WebullPreviewStore(
            tmp_path / "previews.json"
        ).save_previews([invalid])


def test_file_contains_only_redacted_fields(
    tmp_path,
):
    path = tmp_path / "previews.json"

    WebullPreviewStore(path).save_previews([
        preview()
    ])

    payload = json.loads(
        path.read_text(encoding="utf-8")
    )
    record = payload["previews"][0]

    assert set(record) == {
        "symbol",
        "quantity",
        "limitPrice",
        "targetPrice",
        "tradingStopPrice",
        "proposedExposure",
        "status",
        "createdAt",
    }

    serialized = json.dumps(payload)

    assert "approvalToken" not in serialized
    assert "accountId" not in serialized
    assert "token_hash" not in serialized
    assert "proposalFingerprint" not in serialized


def test_fibonacci_metadata_survives_restart(
    tmp_path,
):
    path = tmp_path / "previews.json"

    enriched = preview()
    enriched.update({
        "strategyName": "FIBONACCI_61_8",
        "rewardRisk": 2.25,
        "confirmationTime": "10:07",
        "retracementPrice": 4.24,
        "impulseAtrMultiple": 0.82,
        "pullbackVolumeRatio": 0.61,
    })

    WebullPreviewStore(path).save_previews([
        enriched
    ])

    stored = WebullPreviewStore(
        path
    ).load_preview("OPEN")

    assert stored is not None
    assert stored["strategyName"] == (
        "FIBONACCI_61_8"
    )
    assert stored["rewardRisk"] == 2.25
    assert stored["confirmationTime"] == "10:07"
    assert stored["retracementPrice"] == 4.24
    assert stored["impulseAtrMultiple"] == 0.82
    assert stored["pullbackVolumeRatio"] == 0.61


def test_legacy_preview_without_strategy_metadata_loads(
    tmp_path,
):
    path = tmp_path / "previews.json"

    WebullPreviewStore(path).save_previews([
        preview()
    ])

    stored = WebullPreviewStore(
        path
    ).load_preview("OPEN")

    assert stored is not None
    assert "strategyName" not in stored
    assert "rewardRisk" not in stored
    assert "confirmationTime" not in stored
    assert "retracementPrice" not in stored
    assert "impulseAtrMultiple" not in stored
    assert "pullbackVolumeRatio" not in stored


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("rewardRisk", -1),
        ("retracementPrice", 0),
        ("impulseAtrMultiple", -0.1),
        ("pullbackVolumeRatio", -0.1),
        ("rewardRisk", float("nan")),
        ("rewardRisk", float("inf")),
    ],
)
def test_rejects_invalid_strategy_metadata(
    tmp_path,
    field,
    value,
):
    invalid = preview()
    invalid[field] = value

    with pytest.raises(
        WebullPreviewStoreError,
    ):
        WebullPreviewStore(
            tmp_path / "previews.json"
        ).save_previews([invalid])


def test_store_accepts_quick_flip_take_profits(
    tmp_path,
):
    path = (
        tmp_path
        / "quick_flip_previews.json"
    )

    store = WebullPreviewStore(path)

    store.save_previews([
        {
            "symbol": "OPEN",
            "quantity": 10,
            "limitPrice": 9.50,
            "takeProfit1": 10.00,
            "takeProfit2": 10.50,
            "proposedExposure": 95.00,
            "strategyName": "QUICK_FLIP",
            "status": "PREVIEW READY",
            "createdAt": (
                "2026-08-11T18:45:00Z"
            ),
        }
    ])

    preview = store.load_preview("OPEN")

    assert preview["strategyName"] == (
        "QUICK_FLIP"
    )
    assert preview["takeProfit1"] == 10.00
    assert preview["takeProfit2"] == 10.50
    assert "tradingStopPrice" not in preview


def test_store_rejects_partial_quick_flip_targets(
    tmp_path,
):
    path = (
        tmp_path
        / "quick_flip_previews.json"
    )

    store = WebullPreviewStore(path)

    with pytest.raises(
        WebullPreviewStoreError,
        match="take-profit levels",
    ):
        store.save_previews([
            {
                "symbol": "OPEN",
                "quantity": 10,
                "limitPrice": 9.50,
                "takeProfit1": 10.00,
                "proposedExposure": 95.00,
                "strategyName": "QUICK_FLIP",
                "status": "PREVIEW READY",
                "createdAt": (
                    "2026-08-11T18:45:00Z"
                ),
            }
        ])
