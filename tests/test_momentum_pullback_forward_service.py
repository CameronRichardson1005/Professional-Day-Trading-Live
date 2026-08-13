from trading_bot.momentum_pullback_forward_service import (
    MomentumPullbackForwardService,
)
from trading_bot.momentum_pullback_scanner import (
    MomentumPullbackScanner,
    MomentumStockSnapshot,
)


def snapshot(
    symbol,
    *,
    price=8.0,
    gain=15.0,
    rvol=6.0,
):
    return MomentumStockSnapshot(
        symbol=symbol,
        price=price,
        percent_gain=gain,
        relative_volume=rvol,
        current_volume=1_000_000,
        average_volume_30d=100_000,
    )


def make_service():
    return MomentumPullbackForwardService(
        scanner=MomentumPullbackScanner(),
        app_key="key",
        app_secret="secret",
        output_root="test-output",
    )


def test_selects_top_three_eligible_symbols():
    service = make_service()

    selection = service.select_symbols([
        snapshot(
            "AAA",
            gain=15,
            rvol=8,
        ),
        snapshot(
            "BBB",
            gain=30,
            rvol=6,
        ),
        snapshot(
            "CCC",
            gain=20,
            rvol=10,
        ),
        snapshot(
            "DDD",
            gain=12,
            rvol=20,
        ),
    ])

    assert (
        selection.selected_symbols
        == (
            "BBB",
            "CCC",
            "AAA",
        )
    )


def test_rejects_ineligible_names():
    service = make_service()

    selection = service.select_symbols([
        snapshot(
            "PASS",
            gain=20,
            rvol=6,
        ),
        snapshot(
            "LOW_GAIN",
            gain=9,
            rvol=10,
        ),
        snapshot(
            "LOW_RVOL",
            gain=30,
            rvol=4,
        ),
    ])

    assert (
        selection.selected_symbols
        == ("PASS",)
    )

    assert set(
        selection.rejected_symbols
    ) == {
        "LOW_GAIN",
        "LOW_RVOL",
    }


def test_build_recorder_uses_selected_symbols():
    service = make_service()

    recorder = service.build_recorder(
        snapshots=[
            snapshot(
                "AAA",
                gain=15,
                rvol=8,
            ),
            snapshot(
                "BBB",
                gain=30,
                rvol=6,
            ),
            snapshot(
                "CCC",
                gain=20,
                rvol=10,
            ),
            snapshot(
                "FAIL",
                gain=5,
                rvol=20,
            ),
        ]
    )

    assert recorder.symbols == (
        "BBB",
        "CCC",
        "AAA",
    )


def test_no_eligible_symbols_raises():
    service = make_service()

    try:
        service.build_recorder(
            snapshots=[
                snapshot(
                    "FAIL",
                    gain=5,
                    rvol=2,
                )
            ]
        )
    except ValueError as error:
        assert (
            "No Momentum Pullback symbols"
            in str(error)
        )
    else:
        raise AssertionError(
            "Expected ValueError."
        )
