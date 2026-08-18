import random

from trading_bot.webull_account_parser import (
    ParsedWebullOpenOrder,
    ParsedWebullPosition,
)
from trading_bot.webull_account_risk import (
    WebullAccountRiskGate,
    WebullExecutionRiskLimits,
    build_execution_risk_state,
)
from trading_bot.webull_safety import (
    WebullAccountState,
    WebullOrderProposal,
)


CAP = 225.0


def account():
    return WebullAccountState(
        account_type="CASH",
        available_cash=10000.0,
        position_exposure=0.0,
        open_buy_order_exposure=0.0,
        data_is_current=True,
        buying_power=10000.0,
    )


def limits():
    return WebullExecutionRiskLimits(
        max_daily_loss=25.0,
        max_open_positions=4,
        max_open_orders=4,
        max_position_exposure=CAP,
    )


def evaluate(
    *,
    held_exposure,
    proposed_quantity,
    proposed_price,
):
    positions = []

    if held_exposure > 0:
        positions.append(
            ParsedWebullPosition(
                symbol="SOUN",
                quantity=1.0,
                market_price=held_exposure,
                market_value=held_exposure,
            )
        )

    state = build_execution_risk_state(
        positions=positions,
        open_orders=[],
        daily_realized_pnl=0.0,
        kill_switch_active=False,
    )

    proposal = WebullOrderProposal(
        symbol="SOUN",
        side="BUY",
        quantity=proposed_quantity,
        limit_price=proposed_price,
        manually_approved=False,
    )

    return (
        WebullAccountRiskGate
        .evaluate_new_buy(
            account=account(),
            proposal=proposal,
            risk_state=state,
            limits=limits(),
        )
    )


def test_25000_randomized_position_cap_scenarios():
    rng = random.Random(
        20260818
    )

    allowed = 0
    cap_rejected = 0

    for _ in range(25000):
        held_exposure = round(
            rng.uniform(
                0.0,
                300.0,
            ),
            2,
        )

        quantity = rng.randint(
            1,
            25,
        )

        price = round(
            rng.uniform(
                1.0,
                50.0,
            ),
            2,
        )

        result = evaluate(
            held_exposure=held_exposure,
            proposed_quantity=quantity,
            proposed_price=price,
        )

        expected_projected = round(
            held_exposure
            + quantity * price,
            2,
        )

        assert (
            result.projected_symbol_exposure
            == expected_projected
        )

        if expected_projected <= CAP:
            assert result.allowed
            assert (
                result.reason
                == "ACCOUNT_RISK_APPROVED"
            )

            assert (
                result.projected_symbol_exposure
                <= CAP
            )

            allowed += 1

        else:
            assert not result.allowed
            assert (
                result.reason
                == "MAX_POSITION_EXPOSURE_EXCEEDED"
            )

            cap_rejected += 1

    assert allowed > 0
    assert cap_rejected > 0


def test_225_boundary_is_inclusive():
    exactly_at_cap = evaluate(
        held_exposure=175.0,
        proposed_quantity=2,
        proposed_price=25.0,
    )

    assert exactly_at_cap.allowed

    assert (
        exactly_at_cap
        .projected_symbol_exposure
        == 225.0
    )

    one_cent_above = evaluate(
        held_exposure=175.01,
        proposed_quantity=2,
        proposed_price=25.0,
    )

    assert not one_cent_above.allowed

    assert (
        one_cent_above.reason
        == "MAX_POSITION_EXPOSURE_EXCEEDED"
    )

    assert (
        one_cent_above
        .projected_symbol_exposure
        == 225.01
    )


def test_pending_same_symbol_buy_cannot_stack():
    rng = random.Random(
        20260819
    )

    for _ in range(5000):
        held_exposure = round(
            rng.uniform(
                0.0,
                200.0,
            ),
            2,
        )

        reserved_exposure = round(
            rng.uniform(
                1.0,
                225.0,
            ),
            2,
        )

        positions = []

        if held_exposure > 0:
            positions.append(
                ParsedWebullPosition(
                    symbol="SOUN",
                    quantity=1.0,
                    market_price=held_exposure,
                    market_value=held_exposure,
                )
            )

        state = build_execution_risk_state(
            positions=positions,
            open_orders=[
                ParsedWebullOpenOrder(
                    symbol="SOUN",
                    side="BUY",
                    remaining_quantity=1.0,
                    limit_price=reserved_exposure,
                    reserved_exposure=(
                        reserved_exposure
                    ),
                )
            ],
            daily_realized_pnl=0.0,
            kill_switch_active=False,
        )

        result = (
            WebullAccountRiskGate
            .evaluate_new_buy(
                account=account(),
                proposal=(
                    WebullOrderProposal(
                        symbol="SOUN",
                        side="BUY",
                        quantity=1,
                        limit_price=1.0,
                        manually_approved=False,
                    )
                ),
                risk_state=state,
                limits=limits(),
            )
        )

        assert not result.allowed

        assert (
            result.reason
            == "OPEN_ORDER_ALREADY_EXISTS_FOR_SYMBOL"
        )
