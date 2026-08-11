from trading_bot.webull_preview_service import (
    WebullPreviewService,
)
from trading_bot.webull_preview_store import (
    WebullPreviewStore,
)


def ready_preview():
    return {
        "status": "PREVIEW READY",
        "symbol": "OPEN",
        "quantity": 10,
        "limitBuy": 4.25,
        "target": 4.60,
        "tradingStopLoss": 4.10,
        "proposedExposure": 42.5,
    }


def test_service_persists_only_ready_previews(
    tmp_path,
):
    store = WebullPreviewStore(
        tmp_path / "previews.json"
    )
    service = WebullPreviewService(
        preview_store=store
    )

    service._persist_ready_previews([
        ready_preview(),
        {
            "status": "PREVIEW FAILED",
            "symbol": "BBAI",
        },
    ])

    stored = store.load_preview("OPEN")

    assert stored is not None
    assert stored["quantity"] == 10
    assert stored["limitPrice"] == 4.25
    assert stored["proposedExposure"] == 42.5
    assert store.load_preview("BBAI") is None


def test_service_clears_stale_previews(
    tmp_path,
):
    store = WebullPreviewStore(
        tmp_path / "previews.json"
    )
    service = WebullPreviewService(
        preview_store=store
    )

    service._persist_ready_previews([
        ready_preview()
    ])

    assert store.load_preview("OPEN") is not None

    service._persist_ready_previews([])

    assert store.load_preview("OPEN") is None
