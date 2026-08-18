import pytest

from trading_bot.config import (
    WEBULL_EXECUTION_MAX_POSITION_EXPOSURE_DOLLARS,
)
from trading_bot.webull_account_parser import (
    ParsedWebullOpenOrder,
    ParsedWebullPosition,
)
from trading_bot.webull_account_risk import (
    WebullAccountRiskGate,
    WebullExecutionRiskLimits,
    WebullExecutionRiskState,
    build_execution_risk_state,
)
from trading_bot.webull_safety import (
    WebullAccountState,
    WebullOrderProposal,
)


def account():
    return WebullAccountState(
        account_type="CASH",
        available_cash=1000.0,
        position_exposure=0.0,
        open_buy_order_exposure=0.0,
        data_is_current=True,
        buying_power=1000.0,
    )


def limits():
    return WebullExecutionRiskLimits(
        max_daily_loss=25.0,
        max_open_positions=2,
        max_open_orders=2,
        max_position_exposure=225.0,
    )


def proposal(
    *,
    quantity=1,
    price=25.0,
):
    return WebullOrderProposal(
        symbol="SOUN",
        side="BUY",
        quantity=quantity,
        limit_price=price,
        manually_approved=False,
    )


def test_configured_position_cap_is_225():
    assert (
        WEBULL_EXECUTION_MAX_POSITION_EXPOSURE_DOLLARS
        == 225.0
    )


def test_clean_new_position_below_cap_is_allowed():
    state = build_execution_risk_state(
        positions=[],
        open_orders=[],
        daily_realized_pnl=0.0,
        kill_switch_active=False,
    )

    result = WebullAccountRiskGate.evaluate_new_buy(
        account=account(),
        proposal=proposal(
            quantity=8,
            price=25.0,
        ),
        risk_state=state,
        limits=limits(),
    )

    assert result.allowed
    assert result.projected_symbol_exposure == 200.0
    assert result.max_position_exposure == 225.0


def test_proposed_order_above_position_cap_is_rejected():
    state = build_execution_risk_state(
        positions=[],
        open_orders=[],
        daily_realized_pnl=0.0,
        kill_switch_active=False,
    )

    result = WebullAccountRiskGate.evaluate_new_buy(
        account=account(),
        proposal=proposal(
            quantity=10,
            price=25.0,
        ),
        risk_state=state,
        limits=limits(),
    )

    assert not result.allowed
    assert result.reason == (
        "MAX_POSITION_EXPOSURE_EXCEEDED"
    )
    assert result.projected_symbol_exposure == 250.0


def test_existing_position_plus_new_buy_is_capped():
    state = build_execution_risk_state(
        positions=[
            ParsedWebullPosition(
                symbol="SOUN",
                quantity=10.0,
                market_price=18.0,
                market_value=180.0,
            )
        ],
        open_orders=[],
        daily_realized_pnl=0.0,
        kill_switch_active=False,
    )

    result = WebullAccountRiskGate.evaluate_new_buy(
        account=account(),
        proposal=proposal(
            quantity=2,
            price=25.0,
        ),
        risk_state=state,
        limits=limits(),
    )

    assert not result.allowed
    assert result.current_symbol_exposure == 180.0
    assert result.projected_symbol_exposure == 230.0


def test_position_exactly_at_cap_is_allowed():
    state = build_execution_risk_state(
        positions=[
            ParsedWebullPosition(
                symbol="SOUN",
                quantity=10.0,
                market_price=17.5,
                market_value=175.0,
            )
        ],
        open_orders=[],
        daily_realized_pnl=0.0,
        kill_switch_active=False,
    )

    result = WebullAccountRiskGate.evaluate_new_buy(
        account=account(),
        proposal=proposal(
            quantity=2,
            price=25.0,
        ),
        risk_state=state,
        limits=limits(),
    )

    assert result.allowed
    assert result.projected_symbol_exposure == 225.0


def test_pending_buy_exposure_is_preserved_by_state_builder():
    state = build_execution_risk_state(
        positions=[],
        open_orders=[
            ParsedWebullOpenOrder(
                symbol="SOUN",
                side="BUY",
                remaining_quantity=5.0,
                limit_price=20.0,
                reserved_exposure=100.0,
            )
        ],
        daily_realized_pnl=0.0,
        kill_switch_active=False,
    )

    assert state.pending_buy_symbols == (
        "SOUN",
    )

    assert dict(
        state.pending_buy_exposures
    ) == {
        "SOUN": 100.0,
    }


def test_sell_order_adds_no_pending_buy_exposure():
    state = build_execution_risk_state(
        positions=[],
        open_orders=[
            ParsedWebullOpenOrder(
                symbol="SOUN",
                side="SELL",
                remaining_quantity=5.0,
                limit_price=20.0,
                reserved_exposure=0.0,
            )
        ],
        daily_realized_pnl=0.0,
        kill_switch_active=False,
    )

    assert state.pending_buy_symbols == ()
    assert state.pending_buy_exposures == ()
    assert state.open_order_symbols == (
        "SOUN",
    )


def test_existing_position_without_exposure_data_fails_closed():
    state = WebullExecutionRiskState(
        daily_realized_pnl=0.0,
        open_position_symbols=(
            "SOUN",
        ),
        open_order_symbols=(),
        kill_switch_active=False,
        pending_buy_symbols=(),
        position_exposures=(),
        pending_buy_exposures=(),
        data_is_current=True,
    )

    result = WebullAccountRiskGate.evaluate_new_buy(
        account=account(),
        proposal=proposal(
            quantity=1,
            price=20.0,
        ),
        risk_state=state,
        limits=limits(),
    )

    assert not result.allowed
    assert result.reason == (
        "POSITION_EXPOSURE_DATA_MISSING"
    )


def test_kill_switch_precedes_position_cap():
    state = build_execution_risk_state(
        positions=[],
        open_orders=[],
        daily_realized_pnl=0.0,
        kill_switch_active=True,
    )

    result = WebullAccountRiskGate.evaluate_new_buy(
        account=account(),
        proposal=proposal(
            quantity=20,
            price=25.0,
        ),
        risk_state=state,
        limits=limits(),
    )

    assert not result.allowed
    assert result.reason == (
        "TRADING_KILL_SWITCH_ACTIVE"
    )


def test_daily_loss_halt_precedes_position_cap():
    state = build_execution_risk_state(
        positions=[],
        open_orders=[],
        daily_realized_pnl=-25.0,
        kill_switch_active=False,
    )

    result = WebullAccountRiskGate.evaluate_new_buy(
        account=account(),
        proposal=proposal(
            quantity=20,
            price=25.0,
        ),
        risk_state=state,
        limits=limits(),
    )

    assert not result.allowed
    assert result.reason == (
        "DAILY_LOSS_LIMIT_REACHED"
    )
