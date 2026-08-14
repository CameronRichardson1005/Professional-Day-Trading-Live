from unittest.mock import patch

from trading_bot.quick_flip_strategy import (
    QuickFlipSignal,
)
from trading_bot.quick_flip_webull_preview import (
    build_quick_flip_preview_request,
    quick_flip_preview_payload,
)
from trading_bot.quick_flip_webull_preview_service import (
    QuickFlipWebullPreviewService,
)
from trading_bot.webull_safety import (
    WebullAccountState,
)


def signal_for(
    symbol,
    *,
    entry=10.0,
    tp1=10.5,
    tp2=11.0,
):
    return QuickFlipSignal(
        symbol=symbol,
        signal="INVEST",
        pattern="HAMMER",
        status="CONFIRMED",
        detail="test",
        entry_price=entry,
        take_profit_1=tp1,
        take_profit_2=tp2,
        opening_range_high=tp2,
        opening_range_low=tp1,
        opening_range_size=(
            tp2 - tp1
        ),
        atr_14=1.0,
        liquidity_threshold=1.25,
        reversal_time=None,
        confirmation_time=None,
    )


class Result:
    def __init__(self, signal):
        self.signal = signal


class FakeSnapshotClient:
    def __init__(self, state):
        self.state = state

    def get_account_state(self):
        return self.state


class FakePreviewClient:
    def __init__(self):
        self.requests = []

    def preview(self, request):
        self.requests.append(request)

        return quick_flip_preview_payload(
            request=request,
            webull_result={
                "estimated_cost": (
                    request
                    .estimated_position_value
                ),
                "estimated_transaction_fee": 0,
                "currency": "USD",
            },
        )


def cash_account(
    *,
    available_cash=1000.0,
    position_exposure=0.0,
    open_buy_order_exposure=0.0,
):
    return WebullAccountState(
        account_type="CASH",
        available_cash=available_cash,
        position_exposure=position_exposure,
        open_buy_order_exposure=(
            open_buy_order_exposure
        ),
        data_is_current=True,
    )


def test_quick_flip_preview_is_long_only_and_stop_free(
    tmp_path,
):
    from trading_bot.webull_preview_store import (
        WebullPreviewStore,
    )

    client = FakePreviewClient()

    service = QuickFlipWebullPreviewService(
        client=client,
        snapshot_client=FakeSnapshotClient(
            cash_account()
        ),
        preview_store=WebullPreviewStore(
            tmp_path / "previews.json"
        ),
    )

    with patch(
        "trading_bot."
        "quick_flip_webull_preview_service."
        "WEBULL_PREVIEW_ENABLED",
        True,
    ):
        preview = service.prepare_previews({
            "OPEN": Result(
                signal_for("OPEN")
            ),
        })[0]

    assert preview["status"] == (
        "PREVIEW READY"
    )
    assert preview["submitted"] is False
    assert preview["side"] == "BUY"
    assert (
        preview["automaticStopLoss"]
        is False
    )
    assert "tradingStopLoss" not in preview
    assert preview["takeProfit1"] == 10.5
    assert preview["takeProfit2"] == 11.0
    assert (
        preview["manualApprovalRequired"]
        is True
    )
    assert (
        preview["manualApprovalGranted"]
        is False
    )


def test_quick_flip_margin_account_is_rejected(
    tmp_path,
):
    from trading_bot.webull_preview_store import (
        WebullPreviewStore,
    )

    service = QuickFlipWebullPreviewService(
        client=FakePreviewClient(),
        snapshot_client=FakeSnapshotClient(
            WebullAccountState(
                account_type="MARGIN",
                available_cash=1000.0,
                position_exposure=0.0,
                open_buy_order_exposure=0.0,
            )
        ),
        preview_store=WebullPreviewStore(
            tmp_path / "previews.json"
        ),
    )

    with patch(
        "trading_bot."
        "quick_flip_webull_preview_service."
        "WEBULL_PREVIEW_ENABLED",
        True,
    ):
        preview = service.prepare_previews({
            "OPEN": Result(
                signal_for("OPEN")
            ),
        })[0]

    assert preview["status"] == (
        "PREVIEW FAILED"
    )
    assert preview["submitted"] is False
    assert preview["safetyReason"] == (
        "CASH_ACCOUNT_REQUIRED"
    )


def test_quick_flip_uses_remaining_exposure(
    tmp_path,
):
    from trading_bot.webull_preview_store import (
        WebullPreviewStore,
    )

    client = FakePreviewClient()

    service = QuickFlipWebullPreviewService(
        client=client,
        snapshot_client=FakeSnapshotClient(
            cash_account(
                position_exposure=450.0,
            )
        ),
        preview_store=WebullPreviewStore(
            tmp_path / "previews.json"
        ),
    )

    with (
        patch(
            "trading_bot."
            "quick_flip_webull_preview_service."
            "WEBULL_PREVIEW_ENABLED",
            True,
        ),
        patch(
            "trading_bot.quick_flip_webull_preview."
            "WEBULL_PREVIEW_MAX_SHARES",
            1000,
        ),
    ):
        preview = service.prepare_previews({
            "OPEN": Result(
                signal_for(
                    "OPEN",
                    entry=10.0,
                )
            ),
        })[0]

    assert preview["status"] == (
        "PREVIEW READY"
    )
    assert preview["quantity"] == 90
    assert (
        preview["estimatedPositionValue"]
        == 900.0
    )
    assert (
        preview[
            "remainingAllowanceBeforePreview"
        ]
        == 900.0
    )


def test_quick_flip_service_exposes_no_order_actions():
    service = QuickFlipWebullPreviewService(
        client=FakePreviewClient(),
        snapshot_client=FakeSnapshotClient(
            cash_account()
        ),
    )

    assert not hasattr(
        service,
        "place_order",
    )
    assert not hasattr(
        service,
        "submit_order",
    )
    assert not hasattr(
        service,
        "replace_order",
    )
    assert not hasattr(
        service,
        "cancel_order",
    )
