from trading_bot.webull_safety import (
    WebullAccountState,
    WebullReplacementProposal,
    WebullSafetyGate,
)


def account(
    *,
    available_cash=1000.0,
    position_exposure=0.0,
    open_buy_order_exposure=50.0,
    data_is_current=True,
):
    return WebullAccountState(
        account_type="CASH",
        available_cash=available_cash,
        position_exposure=position_exposure,
        open_buy_order_exposure=(
            open_buy_order_exposure
        ),
        data_is_current=data_is_current,
        buying_power=available_cash,
    )


def proposal(
    *,
    current_quantity=10,
    current_limit_price=5.00,
    current_filled_quantity=0.0,
    replacement_quantity=10,
    replacement_limit_price=6.00,
):
    return WebullReplacementProposal(
        symbol="SOUN",
        side="BUY",
        current_quantity=current_quantity,
        current_limit_price=(
            current_limit_price
        ),
        current_filled_quantity=(
            current_filled_quantity
        ),
        replacement_quantity=(
            replacement_quantity
        ),
        replacement_limit_price=(
            replacement_limit_price
        ),
    )


def test_replace_does_not_double_count_existing_order():
    decision = WebullSafetyGate.evaluate_replacement(
        account=account(
            position_exposure=400.0,
            open_buy_order_exposure=50.0,
        ),
        proposal=proposal(
            replacement_quantity=10,
            replacement_limit_price=6.00,
        ),
    )

    assert decision.allowed is True

    assert decision.current_exposure == 450.0
    assert decision.current_order_exposure == 50.0
    assert decision.replacement_exposure == 60.0
    assert decision.additional_exposure == 10.0

    # 450 current
    # - 50 old order reservation
    # + 60 replacement reservation
    assert decision.projected_exposure == 460.0


def test_other_positions_and_orders_remain_counted():
    decision = WebullSafetyGate.evaluate_replacement(
        account=account(
            position_exposure=300.0,
            open_buy_order_exposure=100.0,
        ),
        proposal=proposal(
            replacement_quantity=10,
            replacement_limit_price=6.00,
        ),
    )

    assert decision.allowed is True
    assert decision.current_exposure == 400.0
    assert decision.projected_exposure == 410.0


def test_missing_old_order_reservation_fails_closed():
    decision = WebullSafetyGate.evaluate_replacement(
        account=account(
            open_buy_order_exposure=0.0,
        ),
        proposal=proposal(),
    )

    assert decision.allowed is False

    assert (
        decision.reason
        == "CURRENT_ORDER_EXPOSURE_NOT_PRESENT"
    )


def test_partial_fill_replace_is_not_supported_yet():
    decision = WebullSafetyGate.evaluate_replacement(
        account=account(
            open_buy_order_exposure=40.0,
        ),
        proposal=proposal(
            current_filled_quantity=2.0,
        ),
    )

    assert decision.allowed is False

    assert (
        decision.reason
        == "PARTIALLY_FILLED_REPLACEMENT_NOT_SUPPORTED"
    )


def test_only_incremental_cash_is_required():
    decision = WebullSafetyGate.evaluate_replacement(
        account=account(
            available_cash=9.0,
            open_buy_order_exposure=50.0,
        ),
        proposal=proposal(
            replacement_quantity=10,
            replacement_limit_price=6.00,
        ),
    )

    assert decision.allowed is False

    assert (
        decision.reason
        == "REPLACEMENT_INSUFFICIENT_AVAILABLE_CASH"
    )

    assert decision.additional_exposure == 10.0


def test_reducing_order_requires_no_extra_cash():
    decision = WebullSafetyGate.evaluate_replacement(
        account=account(
            available_cash=0.0,
            open_buy_order_exposure=50.0,
        ),
        proposal=proposal(
            replacement_quantity=5,
            replacement_limit_price=5.00,
        ),
    )

    assert decision.allowed is True
    assert decision.additional_exposure == 0.0
    assert decision.projected_exposure == 25.0


def test_replacement_operational_cap_is_enforced():
    decision = WebullSafetyGate.evaluate_replacement(
        account=account(
            position_exposure=400.0,
            open_buy_order_exposure=50.0,
        ),
        proposal=proposal(
            replacement_quantity=20,
            replacement_limit_price=5.00,
        ),
    )

    assert decision.allowed is False

    assert (
        decision.reason
        == "OPERATIONAL_EXPOSURE_CAP_EXCEEDED"
    )

    assert decision.projected_exposure == 500.0


def test_stale_account_fails_closed():
    decision = WebullSafetyGate.evaluate_replacement(
        account=account(
            data_is_current=False,
        ),
        proposal=proposal(),
    )

    assert decision.allowed is False
    assert (
        decision.reason
        == "ACCOUNT_DATA_STALE_OR_UNKNOWN"
    )
