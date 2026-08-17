from trading_bot.webull_manager_stress import (
    ManagerStressError,
    run_webull_manager_stress,
)


def test_manager_stress_500_scenarios():
    report = run_webull_manager_stress(
        scenarios=500,
        seed=20260817,
    )

    assert report.entry_cases == 500
    assert report.close_cases == 500

    assert report.invariant_failures == 0

    assert (
        report.entry_safety_rejections
        > 0
    )

    assert (
        report.duplicate_entry_rejections
        > 0
    )

    assert (
        report.ambiguous_entry_recoveries
        > 0
    )

    assert (
        report.successful_replacements
        > 0
    )

    assert (
        report.pending_replacement_recoveries
        > 0
    )

    assert (
        report.ambiguous_replacement_recoveries
        > 0
    )

    assert (
        report.disarmed_replacement_rejections
        > 0
    )

    assert (
        report.ambiguous_entry_cancel_recoveries
        > 0
    )

    assert (
        report.pending_entry_cancel_recoveries
        > 0
    )

    assert (
        report.disarmed_close_rejections
        > 0
    )

    assert (
        report.stale_close_rejections
        > 0
    )

    assert (
        report.changed_position_rejections
        > 0
    )

    assert (
        report.existing_sell_rejections
        > 0
    )

    assert (
        report.margin_close_rejections
        > 0
    )

    assert (
        report.full_close_reconciliations
        > 0
    )

    assert (
        report.partial_close_reconciliations
        > 0
    )

    assert (
        report.duplicate_close_rejections
        > 0
    )

    assert (
        report.ambiguous_close_recoveries
        > 0
    )

    assert (
        report.ambiguous_close_cancel_recoveries
        > 0
    )

    assert (
        report.pending_close_cancel_recoveries
        > 0
    )

    assert (
        report.durable_restart_recoveries
        > 0
    )


def test_manager_stress_is_deterministic():
    first = run_webull_manager_stress(
        scenarios=100,
        seed=1234,
    )

    second = run_webull_manager_stress(
        scenarios=100,
        seed=1234,
    )

    assert first == second


def test_manager_stress_rejects_bad_count():
    try:
        run_webull_manager_stress(
            scenarios=0
        )

    except ManagerStressError as error:
        assert (
            str(error)
            == "INVALID_MANAGER_STRESS_SCENARIOS"
        )

    else:
        raise AssertionError(
            "Bad scenario count was accepted."
        )
