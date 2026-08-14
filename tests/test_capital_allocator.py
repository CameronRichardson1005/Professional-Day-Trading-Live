from trading_bot.capital_allocator import (
    build_equal_weight_capital_plan,
)
from trading_bot.webull_account_parser import (
    parse_account_balance,
)
from trading_bot.webull_safety import (
    WebullAccountState,
)


def account(
    *,
    cash=1000.0,
    buying_power=1000.0,
    exposure=0.0,
):
    return WebullAccountState(
        account_type="CASH",
        available_cash=cash,
        position_exposure=exposure,
        open_buy_order_exposure=0.0,
        buying_power=buying_power,
    )


def plan(state, candidates, fraction=1.0):
    return build_equal_weight_capital_plan(
        state,
        candidates,
        deployment_fraction=fraction,
        operational_cap=475.0,
        hard_cap=500.0,
    )


def test_equal_weights_operational_cap():
    result = plan(
        account(),
        2,
    )

    assert result.safe_capital_base == 1000.0
    assert result.deployable_pool == 475.0
    assert result.per_candidate_budget == 237.5
    assert result.allocation_weight == 0.5


def test_buying_power_can_reduce_cash_safe_base():
    result = plan(
        account(
            cash=1000.0,
            buying_power=300.0,
        ),
        2,
    )

    assert result.safe_capital_base == 300.0
    assert result.deployable_pool == 300.0
    assert result.per_candidate_budget == 150.0


def test_buying_power_never_increases_available_cash():
    result = plan(
        account(
            cash=200.0,
            buying_power=1000.0,
        ),
        2,
    )

    assert result.safe_capital_base == 200.0
    assert result.deployable_pool == 200.0
    assert result.per_candidate_budget == 100.0


def test_existing_exposure_reduces_pool():
    result = plan(
        account(
            exposure=400.0,
        ),
        2,
    )

    assert result.remaining_exposure_capacity == 75.0
    assert result.deployable_pool == 75.0
    assert result.per_candidate_budget == 37.5


def test_deployment_fraction_is_applied():
    result = plan(
        account(
            cash=400.0,
            buying_power=400.0,
        ),
        2,
        fraction=0.5,
    )

    assert result.deployable_cash == 200.0
    assert result.deployable_pool == 200.0
    assert result.per_candidate_budget == 100.0


def test_missing_buying_power_falls_back_to_cash():
    result = plan(
        account(
            cash=300.0,
            buying_power=None,
        ),
        3,
    )

    assert result.safe_capital_base == 300.0
    assert result.per_candidate_budget == 100.0


def test_parser_preserves_buying_power_separately():
    result = parse_account_balance({
        "total_asset_currency": "USD",
        "total_cash_balance": "1000.00",
        "account_currency_assets": [
            {
                "currency": "USD",
                "settled_cash": "900.00",
                "cash_balance": "1000.00",
                "buying_power": "850.00",
            },
        ],
    })

    assert result.available_cash == 900.0
    assert result.buying_power == 850.0


def test_prior_daily_reservations_reduce_pool():
    result = build_equal_weight_capital_plan(
        account(
            cash=1000.0,
            buying_power=1000.0,
        ),
        2,
        deployment_fraction=1.0,
        operational_cap=475.0,
        hard_cap=500.0,
        reserved_recommendation_exposure=230.0,
    )

    assert (
        result.deployable_pool_before_reservations
        == 475.0
    )
    assert (
        result.reserved_recommendation_exposure
        == 230.0
    )
    assert result.deployable_pool == 245.0
    assert result.per_candidate_budget == 122.5


def test_ninety_percent_daily_deployment_limit():
    result = build_equal_weight_capital_plan(
        account(
            cash=400.0,
            buying_power=400.0,
        ),
        2,
        deployment_fraction=0.90,
        operational_cap=1000.0,
        hard_cap=1000.0,
    )

    assert result.safe_capital_base == 400.0
    assert result.deployable_cash == 360.0
    assert result.deployable_pool == 360.0
    assert result.per_candidate_budget == 180.0
