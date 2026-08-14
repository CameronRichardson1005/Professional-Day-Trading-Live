from unittest.mock import patch

from trading_bot.capital_allocator import (
    build_preview_exposure_ceiling,
)
from trading_bot.models import Stock
from trading_bot.quick_flip_webull_preview_service import (
    QuickFlipWebullPreviewService,
)
from trading_bot.webull_preview_service import (
    WebullPreviewService,
)
from trading_bot.webull_preview_client import (
    WebullPreviewClient,
)
from trading_bot.webull_safety import (
    WebullAccountState,
    WebullOrderProposal,
    WebullSafetyGate,
)


def account(
    *,
    cash=5000.0,
    buying_power=5000.0,
    exposure=0.0,
):
    return WebullAccountState(
        account_type="CASH",
        available_cash=cash,
        position_exposure=exposure,
        open_buy_order_exposure=0.0,
        buying_power=buying_power,
    )


def test_preview_ceiling_uses_ninety_percent_new_capacity():
    state = account(
        cash=5000.0,
        buying_power=5000.0,
        exposure=500.0,
    )

    ceiling = build_preview_exposure_ceiling(
        state,
        deployment_fraction=0.90,
    )

    assert ceiling == 5000.0


def test_real_order_safety_defaults_remain_fixed():
    proposal = WebullOrderProposal(
        symbol="TEST",
        side="BUY",
        quantity=100,
        limit_price=10.0,
    )

    decision = WebullSafetyGate.evaluate(
        account=account(),
        proposal=proposal,
        require_manual_approval=False,
    )

    assert decision.allowed is False
    assert (
        decision.reason
        == "HARD_EXPOSURE_CAP_EXCEEDED"
    )


def test_preview_can_use_dynamic_cap_override():
    proposal = WebullOrderProposal(
        symbol="TEST",
        side="BUY",
        quantity=100,
        limit_price=10.0,
    )

    decision = WebullSafetyGate.evaluate(
        account=account(),
        proposal=proposal,
        require_manual_approval=False,
        operational_cap_override=4500.0,
        hard_cap_override=4500.0,
    )

    assert decision.allowed is True
    assert decision.operational_cap == 4500.0
    assert decision.hard_cap == 4500.0


def test_explicit_allocation_can_exceed_legacy_fallback():
    stock = Stock(symbol="TEST")
    stock.signal = "INVEST"
    stock.limit_buy = 10.0
    stock.limit_sell = 12.0
    stock.trading_stop_loss = 9.0

    with (
        patch(
            "trading_bot.webull_preview_client."
            "WEBULL_PREVIEW_RISK_DOLLARS",
            1000.0,
        ),
        patch(
            "trading_bot.webull_preview_client."
            "WEBULL_PREVIEW_MAX_SHARES",
            100000,
        ),
        patch(
            "trading_bot.webull_preview_client."
            "WEBULL_PREVIEW_MAX_POSITION_VALUE",
            500.0,
        ),
    ):
        request = WebullPreviewClient.build_request(
            stock,
            max_position_value=900.0,
        )

    assert request.quantity == 90
    assert request.estimated_position_value == 900.0
    assert request.max_position_value == 900.0



def test_prior_day_preview_reservations_reduce_capacity():
    state = account(
        cash=5000.0,
        buying_power=5000.0,
        exposure=500.0,
    )

    manipulation_remaining = (
        WebullPreviewService._remaining_allowance(
            state,
            preview_exposure_ceiling=5000.0,
            reserved_before_batch=700.0,
        )
    )

    quick_flip_remaining = (
        QuickFlipWebullPreviewService
        ._remaining_allowance(
            state,
            preview_exposure_ceiling=5000.0,
            reserved_before_batch=700.0,
        )
    )

    assert manipulation_remaining == 3800.0
    assert quick_flip_remaining == 3800.0
