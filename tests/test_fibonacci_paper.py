import csv

from dataclasses import replace

from trading_bot.fibonacci_paper import (
    FibonacciPaperLedger,
    build_fibonacci_paper_record,
    qualifies_for_fibonacci_paper,
)
from trading_bot.fibonacci_retracement import (
    RetracementSetup,
)


def setup() -> RetracementSetup:
    return RetracementSetup(
        date="2026-07-30",
        symbol="RGTI",
        data_feed="iex",
        fibonacci_level="FIB_61_8",
        retracement_ratio=0.618,
        setup_found=True,
        rejection_reason="",
        atr=1.0,
        reference_price=11.0,
        atr_pct=9.09,
        impulse_start_time="09:30",
        impulse_end_time="09:48",
        impulse_start_price=10.0,
        impulse_end_price=11.0,
        impulse_size=1.0,
        impulse_atr_multiple=1.0,
        impulse_duration_minutes=18,
        impulse_average_volume=2000,
        retracement_price=10.382,
        retracement_touch_time="10:15",
        retracement_touch_low=10.37,
        retracement_depth_actual=0.63,
        pullback_duration_minutes=27,
        pullback_average_volume=1500,
        pullback_volume_ratio=0.75,
        confirmation_time="10:16",
        confirmation_open=10.40,
        confirmation_high=10.50,
        confirmation_low=10.38,
        confirmation_close=10.48,
        confirmation_body_pct=0.77,
        session_vwap_at_confirmation=10.42,
        confirmation_above_vwap=True,
        entry_price=10.51,
        entry_time="10:17",
        stop_price=10.36,
        target_price=11.0,
        reward_risk=3.2667,
        outcome="WIN",
        exit_time="11:05",
        exit_price=11.0,
        exit_reason="IMPULSE_HIGH",
        gross_return_pct=4.6622,
        net_return_pct=4.35,
        maximum_favourable_excursion_pct=4.70,
        maximum_adverse_excursion_pct=-0.10,
        detail="Previous impulse high was reached.",
    )


def test_qualifying_setup_passes():
    assert qualifies_for_fibonacci_paper(
        setup()
    )


def test_short_impulse_is_rejected():
    candidate = replace(
        setup(),
        impulse_duration_minutes=14,
    )

    assert not qualifies_for_fibonacci_paper(
        candidate
    )


def test_high_pullback_volume_is_rejected():
    candidate = replace(
        setup(),
        pullback_volume_ratio=1.0,
    )

    assert not qualifies_for_fibonacci_paper(
        candidate
    )


def test_record_is_always_not_submitted():
    record = build_fibonacci_paper_record(
        setup(),
        modeled_slippage_bps=15.0,
    )

    assert record is not None
    assert record.submitted == "NO"
    assert record.paper_status == (
        "PAPER ONLY — NOT SUBMITTED"
    )


def test_ledger_updates_instead_of_duplicating(
    tmp_path,
):
    ledger = FibonacciPaperLedger(
        tmp_path / "ledger.csv"
    )

    first = build_fibonacci_paper_record(
        replace(
            setup(),
            outcome="NO ENTRY",
            exit_time="",
            exit_price=None,
            exit_reason="",
            net_return_pct=None,
        ),
        modeled_slippage_bps=15.0,
    )

    final = build_fibonacci_paper_record(
        setup(),
        modeled_slippage_bps=15.0,
    )

    assert first is not None
    assert final is not None

    ledger.upsert([first])
    ledger.upsert([final])

    with ledger.path.open(
        newline="",
        encoding="utf-8",
    ) as file:
        rows = list(csv.DictReader(file))

    assert len(rows) == 1
    assert rows[0]["outcome"] == "WIN"
    assert rows[0]["submitted"] == "NO"


def test_status_summarises_ledger(
    tmp_path,
):
    from trading_bot.fibonacci_paper import (
        fibonacci_paper_status,
    )

    ledger = FibonacciPaperLedger(
        tmp_path / "ledger.csv"
    )

    win = build_fibonacci_paper_record(
        setup(),
        modeled_slippage_bps=15.0,
    )

    loss_setup = replace(
        setup(),
        symbol="RIVN",
        outcome="LOSS",
        net_return_pct=-0.5,
    )

    loss = build_fibonacci_paper_record(
        loss_setup,
        modeled_slippage_bps=15.0,
    )

    assert win is not None
    assert loss is not None

    ledger.upsert([win, loss])

    status = fibonacci_paper_status(
        ledger_path=ledger.path,
        logs_directory=tmp_path,
    )

    assert status["forward"]["total_setups"] == 2
    assert status["forward"]["closed_trades"] == 2
    assert status["forward"]["wins"] == 1
    assert status["forward"]["losses"] == 1
    assert status["today_completed"] is False
    assert status["safety_status"] == (
        "PAPER ONLY — NOT SUBMITTED"
    )


def test_status_detects_completion_marker(
    tmp_path,
):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from trading_bot.fibonacci_paper import (
        fibonacci_paper_status,
    )

    today = datetime.now(
        ZoneInfo("America/New_York")
    ).strftime("%Y-%m-%d")

    marker = (
        tmp_path
        / f"fibonacci-paper-complete-{today}"
    )
    marker.touch()

    status = fibonacci_paper_status(
        ledger_path=tmp_path / "missing.csv",
        logs_directory=tmp_path,
    )

    assert status["today_completed"] is True
    assert status["forward"]["total_setups"] == 0
    assert status["historical"]["total_setups"] == 0


def test_historical_records_are_separate_from_forward(
    tmp_path,
):
    from trading_bot.fibonacci_paper import (
        fibonacci_paper_status,
    )

    ledger = FibonacciPaperLedger(
        tmp_path / "ledger.csv"
    )

    forward = build_fibonacci_paper_record(
        setup(),
        modeled_slippage_bps=15.0,
        observation_type="FORWARD_PAPER",
    )

    historical = build_fibonacci_paper_record(
        replace(
            setup(),
            symbol="OPEN",
        ),
        modeled_slippage_bps=15.0,
        observation_type="HISTORICAL_VALIDATION",
    )

    assert forward is not None
    assert historical is not None

    ledger.upsert([forward, historical])

    status = fibonacci_paper_status(
        ledger_path=ledger.path,
        logs_directory=tmp_path,
    )

    assert status["forward"]["total_setups"] == 1
    assert status["forward"]["closed_trades"] == 1

    assert (
        status["historical"]["total_setups"]
        == 1
    )
    assert (
        status["historical"]["closed_trades"]
        == 1
    )


def test_invalid_observation_type_is_rejected():
    import pytest

    with pytest.raises(
        ValueError,
        match="Observation type",
    ):
        build_fibonacci_paper_record(
            setup(),
            modeled_slippage_bps=15.0,
            observation_type="LIVE_ORDER",
        )
