from trading_bot.historical_execution_stress import (
    HistoricalExecutionStressError,
    run_historical_execution_stress,
)


def test_deterministic_stress_3000_lifecycles():
    report = (
        run_historical_execution_stress(
            scenarios=3000,
            seed=20260817,
        )
    )

    assert report.scenarios == 3000

    assert (
        report.final_flat_scenarios
        == 3000
    )

    assert (
        report.invariant_failures
        == 0
    )

    assert (
        report.duplicate_retry_rejections
        > 0
    )

    assert (
        report.restart_round_trips
        > 0
    )

    assert (
        report.partial_buy_fills
        > 0
    )

    assert (
        report.partial_close_fills
        > 0
    )

    assert (
        report.stale_close_rejections
        > 0
    )

    assert (
        report.ambiguous_buy_accepted
        > 0
    )

    assert (
        report.ambiguous_buy_rejected
        > 0
    )

    assert (
        report.ambiguous_close_accepted
        > 0
    )

    assert (
        report.ambiguous_close_rejected
        > 0
    )


def test_stress_run_is_reproducible():
    first = (
        run_historical_execution_stress(
            scenarios=250,
            seed=12345,
        )
    )

    second = (
        run_historical_execution_stress(
            scenarios=250,
            seed=12345,
        )
    )

    assert first == second


def test_invalid_stress_count_rejected():
    try:
        run_historical_execution_stress(
            scenarios=0
        )

    except HistoricalExecutionStressError as error:
        assert (
            str(error)
            == "INVALID_STRESS_SCENARIO_COUNT"
        )

    else:
        raise AssertionError(
            "Invalid scenario count was accepted."
        )
