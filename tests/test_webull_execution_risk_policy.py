from trading_bot.config import (
    WEBULL_EXECUTION_MAX_DAILY_LOSS_DOLLARS,
    WEBULL_EXECUTION_MAX_OPEN_ORDERS,
    WEBULL_EXECUTION_MAX_OPEN_POSITIONS,
    WEBULL_MAX_TOTAL_EXPOSURE_DOLLARS,
    WEBULL_OPERATIONAL_EXPOSURE_CAP_DOLLARS,
    WEBULL_ORDER_SUBMISSION_ENABLED,
    WEBULL_TRADING_KILL_SWITCH,
)
from trading_bot.webull_account_risk import (
    configured_execution_risk_limits,
)


def test_initial_execution_risk_policy():
    limits = configured_execution_risk_limits()

    assert limits.max_daily_loss == 25.0
    assert limits.max_open_positions == 2
    assert limits.max_open_orders == 2


def test_execution_policy_matches_config():
    limits = configured_execution_risk_limits()

    assert (
        limits.max_daily_loss
        == WEBULL_EXECUTION_MAX_DAILY_LOSS_DOLLARS
    )

    assert (
        limits.max_open_positions
        == WEBULL_EXECUTION_MAX_OPEN_POSITIONS
    )

    assert (
        limits.max_open_orders
        == WEBULL_EXECUTION_MAX_OPEN_ORDERS
    )


def test_existing_exposure_caps_remain_unchanged():
    assert (
        WEBULL_OPERATIONAL_EXPOSURE_CAP_DOLLARS
        == 475.0
    )

    assert (
        WEBULL_MAX_TOTAL_EXPOSURE_DOLLARS
        == 500.0
    )


def test_policy_does_not_enable_trading():
    assert WEBULL_ORDER_SUBMISSION_ENABLED is False
    assert WEBULL_TRADING_KILL_SWITCH is True


def test_configured_execution_position_cap_is_225():
    from trading_bot.config import (
        WEBULL_EXECUTION_MAX_POSITION_EXPOSURE_DOLLARS,
    )

    assert (
        WEBULL_EXECUTION_MAX_POSITION_EXPOSURE_DOLLARS
        == 225.0
    )
