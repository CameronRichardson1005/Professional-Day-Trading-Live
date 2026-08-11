from trading_bot.webull_safety import (
    WebullAccountState,
    WebullOrderProposal,
    WebullSafetyGate,
)


def account(
    *,
    account_type: str = "CASH",
    available_cash: float = 1000.0,
    position_exposure: float = 0.0,
    open_buy_order_exposure: float = 0.0,
    data_is_current: bool = True,
) -> WebullAccountState:
    return WebullAccountState(
        account_type=account_type,
        available_cash=available_cash,
        position_exposure=position_exposure,
        open_buy_order_exposure=open_buy_order_exposure,
        data_is_current=data_is_current,
    )


def proposal(
    *,
    side: str = "BUY",
    quantity: int = 10,
    limit_price: float = 25.0,
    manually_approved: bool = True,
) -> WebullOrderProposal:
    return WebullOrderProposal(
        symbol="TEST",
        side=side,
        quantity=quantity,
        limit_price=limit_price,
        manually_approved=manually_approved,
    )


def test_approved_cash_order_below_operational_cap():
    decision = WebullSafetyGate.evaluate(
        account=account(),
        proposal=proposal(
            quantity=10,
            limit_price=25.0,
        ),
    )

    assert decision.allowed
    assert decision.reason == (
        "APPROVED_BY_SAFETY_GATE"
    )
    assert decision.projected_exposure == 250.0


def test_manual_approval_is_required():
    decision = WebullSafetyGate.evaluate(
        account=account(),
        proposal=proposal(
            manually_approved=False,
        ),
    )

    assert not decision.allowed
    assert decision.reason == (
        "MANUAL_APPROVAL_REQUIRED"
    )


def test_margin_account_is_rejected():
    decision = WebullSafetyGate.evaluate(
        account=account(account_type="MARGIN"),
        proposal=proposal(),
    )

    assert not decision.allowed
    assert decision.reason == (
        "CASH_ACCOUNT_REQUIRED"
    )


def test_unknown_account_type_is_rejected():
    decision = WebullSafetyGate.evaluate(
        account=account(account_type=""),
        proposal=proposal(),
    )

    assert not decision.allowed
    assert decision.reason == (
        "ACCOUNT_TYPE_UNKNOWN"
    )


def test_stale_account_data_is_rejected():
    decision = WebullSafetyGate.evaluate(
        account=account(data_is_current=False),
        proposal=proposal(),
    )

    assert not decision.allowed
    assert decision.reason == (
        "ACCOUNT_DATA_STALE_OR_UNKNOWN"
    )


def test_available_cash_is_enforced():
    decision = WebullSafetyGate.evaluate(
        account=account(available_cash=200.0),
        proposal=proposal(
            quantity=10,
            limit_price=25.0,
        ),
    )

    assert not decision.allowed
    assert decision.reason == (
        "INSUFFICIENT_AVAILABLE_CASH"
    )


def test_open_orders_count_toward_exposure():
    decision = WebullSafetyGate.evaluate(
        account=account(
            open_buy_order_exposure=300.0,
        ),
        proposal=proposal(
            quantity=8,
            limit_price=25.0,
        ),
    )

    assert not decision.allowed
    assert decision.current_exposure == 300.0
    assert decision.projected_exposure == 500.0
    assert decision.reason == (
        "OPERATIONAL_EXPOSURE_CAP_EXCEEDED"
    )


def test_positions_count_toward_exposure():
    decision = WebullSafetyGate.evaluate(
        account=account(
            position_exposure=400.0,
        ),
        proposal=proposal(
            quantity=4,
            limit_price=25.0,
        ),
    )

    assert not decision.allowed
    assert decision.projected_exposure == 500.0
    assert decision.reason == (
        "OPERATIONAL_EXPOSURE_CAP_EXCEEDED"
    )


def test_hard_cap_can_never_be_exceeded():
    decision = WebullSafetyGate.evaluate(
        account=account(
            position_exposure=450.0,
        ),
        proposal=proposal(
            quantity=3,
            limit_price=25.0,
        ),
        enforce_operational_cap=False,
    )

    assert not decision.allowed
    assert decision.projected_exposure == 525.0
    assert decision.reason == (
        "HARD_EXPOSURE_CAP_EXCEEDED"
    )


def test_sell_and_short_orders_are_rejected():
    decision = WebullSafetyGate.evaluate(
        account=account(),
        proposal=proposal(side="SELL"),
    )

    assert not decision.allowed
    assert decision.reason == (
        "ONLY_LONG_BUY_ORDERS_ALLOWED"
    )


def test_invalid_quantity_is_rejected():
    decision = WebullSafetyGate.evaluate(
        account=account(),
        proposal=proposal(quantity=0),
    )

    assert not decision.allowed
    assert decision.reason == "INVALID_QUANTITY"


def test_real_submission_remains_disabled():
    assert not WebullSafetyGate.real_submission_available()
