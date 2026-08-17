from trading_bot.webull_account_risk_stress import (
    run_webull_account_risk_stress,
)


def test_account_risk_stress_5000():
    report = (
        run_webull_account_risk_stress(
            scenarios=5000,
            seed=20260817,
        )
    )

    assert report.scenarios == 5000
    assert report.allowed > 0
    assert report.rejected > 0

    assert (
        report.stale_account_rejections
        > 0
    )

    assert (
        report.stale_risk_rejections
        > 0
    )

    assert (
        report.kill_switch_rejections
        > 0
    )

    assert (
        report.daily_loss_rejections
        > 0
    )

    assert (
        report.duplicate_symbol_order_rejections
        > 0
    )

    assert (
        report.max_order_rejections
        > 0
    )

    assert (
        report.max_position_rejections
        > 0
    )

    assert (
        report.capital_rejections
        > 0
    )

    assert (
        report.invariant_failures
        == 0
    )


def test_account_risk_stress_is_deterministic():
    first = (
        run_webull_account_risk_stress(
            scenarios=500,
            seed=12345,
        )
    )

    second = (
        run_webull_account_risk_stress(
            scenarios=500,
            seed=12345,
        )
    )

    assert first == second
