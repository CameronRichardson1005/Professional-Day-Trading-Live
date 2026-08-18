import pytest

from trading_bot.webull_account_risk import (
    WebullAccountRiskError,
    WebullAccountRiskGate,
    WebullExecutionRiskLimits,
    WebullExecutionRiskState,
)
from trading_bot.webull_safety import (
    WebullAccountState,
    WebullOrderProposal,
)


def account(
    *,
    cash=1000.0,
    buying_power=1000.0,
    current=True,
):
    return WebullAccountState(
        account_type="CASH",
        available_cash=cash,
        position_exposure=0.0,
        open_buy_order_exposure=0.0,
        data_is_current=current,
        buying_power=buying_power,
    )


def proposal(
    *,
    symbol="SOUN",
    quantity=5,
    price=20.0,
):
    return WebullOrderProposal(
        symbol=symbol,
        side="BUY",
        quantity=quantity,
        limit_price=price,
        manually_approved=True,
    )


def limits():
    return WebullExecutionRiskLimits(
        max_daily_loss=50.0,
        max_open_positions=2,
        max_open_orders=2,
        max_position_exposure=225.0,
    )


def state(
    *,
    pnl=0.0,
    positions=(),
    orders=(),
    pending_buys=(),
    position_exposures=None,
    pending_buy_exposures=None,
    kill=False,
    current=True,
):
    if position_exposures is None:
        position_exposures = tuple(
            (
                symbol,
                0.0,
            )
            for symbol
            in positions
        )

    if pending_buy_exposures is None:
        pending_buy_exposures = tuple(
            (
                symbol,
                0.0,
            )
            for symbol
            in pending_buys
        )

    return WebullExecutionRiskState(
        daily_realized_pnl=pnl,
        open_position_symbols=positions,
        open_order_symbols=orders,
        kill_switch_active=kill,
        pending_buy_symbols=pending_buys,
        position_exposures=(
            position_exposures
        ),
        pending_buy_exposures=(
            pending_buy_exposures
        ),
        data_is_current=current,
    )


def evaluate(**kwargs):
    return WebullAccountRiskGate.evaluate_new_buy(
        account=kwargs.get(
            "account_value",
            account(),
        ),
        proposal=kwargs.get(
            "proposal_value",
            proposal(),
        ),
        risk_state=kwargs.get(
            "state_value",
            state(),
        ),
        limits=kwargs.get(
            "limits_value",
            limits(),
        ),
    )


def test_account_risk_approves_clean_state():
    result = evaluate()

    assert result.allowed
    assert (
        result.reason
        == "ACCOUNT_RISK_APPROVED"
    )


@pytest.mark.parametrize(
    ("risk_state", "reason"),
    [
        (
            state(kill=True),
            "TRADING_KILL_SWITCH_ACTIVE",
        ),
        (
            state(pnl=-50.0),
            "DAILY_LOSS_LIMIT_REACHED",
        ),
        (
            state(orders=("SOUN",)),
            "OPEN_ORDER_ALREADY_EXISTS_FOR_SYMBOL",
        ),
        (
            state(orders=("OPEN", "BBAI")),
            "MAX_OPEN_ORDERS_EXCEEDED",
        ),
        (
            state(
                positions=("OPEN", "BBAI"),
            ),
            "MAX_OPEN_POSITIONS_EXCEEDED",
        ),
        (
            state(current=False),
            "ACCOUNT_RISK_DATA_STALE_OR_UNKNOWN",
        ),
    ],
)
def test_account_risk_fails_closed(
    risk_state,
    reason,
):
    result = evaluate(
        state_value=risk_state
    )

    assert not result.allowed
    assert result.reason == reason


def test_existing_position_does_not_add_position_count():
    result = evaluate(
        state_value=state(
            positions=(
                "SOUN",
                "OPEN",
            ),
        )
    )

    assert result.allowed
    assert (
        result.current_open_positions
        == 2
    )
    assert (
        result.projected_open_positions
        == 2
    )


def test_lower_buying_power_limits_execution_capital():
    result = evaluate(
        account_value=account(
            cash=1000.0,
            buying_power=75.0,
        )
    )

    assert not result.allowed

    assert result.reason == (
        "INSUFFICIENT_SAFE_EXECUTION_CAPITAL"
    )

    assert (
        result.safe_execution_capital
        == 75.0
    )


def test_buying_power_never_increases_cash():
    result = evaluate(
        account_value=account(
            cash=80.0,
            buying_power=1000.0,
        )
    )

    assert not result.allowed

    assert (
        result.safe_execution_capital
        == 80.0
    )


def test_stale_account_fails_closed():
    result = evaluate(
        account_value=account(
            current=False
        )
    )

    assert not result.allowed
    assert result.reason == (
        "ACCOUNT_DATA_STALE_OR_UNKNOWN"
    )


@pytest.mark.parametrize(
    "value",
    [
        0,
        -1,
        float("nan"),
        float("inf"),
    ],
)
def test_invalid_daily_loss_limit_rejected(
    value,
):
    with pytest.raises(
        WebullAccountRiskError,
        match="INVALID_MAX_DAILY_LOSS",
    ):
        WebullExecutionRiskLimits(
            max_daily_loss=value,
            max_open_positions=2,
            max_open_orders=2,
            max_position_exposure=225.0,
        )


def test_pending_buy_reserves_future_position_slot():
    result = evaluate(
        proposal_value=proposal(
            symbol="NVDA",
        ),
        state_value=state(
            positions=("AAPL",),
            orders=("MSFT",),
            pending_buys=("MSFT",),
        ),
    )

    assert not result.allowed
    assert result.reason == (
        "MAX_OPEN_POSITIONS_EXCEEDED"
    )
    assert result.current_open_positions == 1
    assert result.projected_open_positions == 3


def test_pending_buy_for_existing_position_does_not_double_count():
    result = evaluate(
        proposal_value=proposal(
            symbol="NVDA",
        ),
        state_value=state(
            positions=("AAPL",),
            orders=("AAPL",),
            pending_buys=("AAPL",),
        ),
    )

    assert result.allowed
    assert result.current_open_positions == 1
    assert result.projected_open_positions == 2


def test_pending_buy_must_correspond_to_open_order():
    with pytest.raises(
        WebullAccountRiskError,
        match="PENDING_BUY_NOT_OPEN_ORDER",
    ):
        state(
            orders=(),
            pending_buys=("MSFT",),
        )
