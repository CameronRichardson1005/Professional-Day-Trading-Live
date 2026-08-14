from pathlib import Path
from types import SimpleNamespace

from trading_bot.models import Stock
from trading_bot.risk_adjusted_allocator import (
    RiskAdjustedOpportunity,
)
from trading_bot.risk_adjusted_live_shadow import (
    build_causal_dominance_equal_weight_shadow,
    current_production_allocations,
    derive_original_daily_pool,
    find_latest_realized_master_before,
)


def test_latest_master_excludes_current_day(
    tmp_path,
):
    directory = Path(tmp_path)

    old = (
        directory
        / (
            "scanner_realized_master_"
            "2026-03-02_to_2026-08-12.csv"
        )
    )

    correct = (
        directory
        / (
            "scanner_realized_master_"
            "2026-03-02_to_2026-08-13.csv"
        )
    )

    current = (
        directory
        / (
            "scanner_realized_master_"
            "2026-03-02_to_2026-08-14.csv"
        )
    )

    future = (
        directory
        / (
            "scanner_realized_master_"
            "2026-03-02_to_2026-08-15.csv"
        )
    )

    for path in (
        old,
        correct,
        current,
        future,
    ):
        path.write_text(
            "date,symbol\n",
            encoding="utf-8",
        )

    selected = (
        find_latest_realized_master_before(
            trading_date="2026-08-14",
            research_dir=directory,
        )
    )

    assert selected == correct


def test_original_pool_reconstructs_reservations():
    stock = Stock(
        symbol="OPEN"
    )

    stock.webull_preview = {
        "status": "PREVIEW READY",
        "deployableCapitalPool": 6000.0,
        "reservedCapitalBeforeBatch": 3000.0,
    }

    pool = derive_original_daily_pool(
        stocks={
            "OPEN": stock,
        },
        quick_flip_previews=[],
    )

    assert pool == 9000.0


def test_original_pool_prefers_manipulation():
    stock = Stock(
        symbol="OPEN"
    )

    stock.webull_preview = {
        "status": "PREVIEW READY",
        "deployableCapitalPool": 9000.0,
        "reservedCapitalBeforeBatch": 0.0,
    }

    pool = derive_original_daily_pool(
        stocks={
            "OPEN": stock,
        },
        quick_flip_previews=[
            {
                "status": "PREVIEW READY",
                "deployableCapitalPool": 4000.0,
                "reservedCapitalBeforeBatch": 5000.0,
            }
        ],
    )

    assert pool == 9000.0


def test_quick_flip_can_supply_pool_when_no_manipulation():
    pool = derive_original_daily_pool(
        stocks={},
        quick_flip_previews=[
            {
                "status": "PREVIEW READY",
                "deployableCapitalPool": 7200.0,
                "reservedCapitalBeforeBatch": 1800.0,
            }
        ],
    )

    assert pool == 9000.0


def test_no_preview_metadata_returns_none():
    pool = derive_original_daily_pool(
        stocks={},
        quick_flip_previews=[],
    )

    assert pool is None


def test_reads_actual_production_recommendations():
    stock = Stock(
        symbol="OPEN"
    )

    stock.webull_preview = {
        "status": "PREVIEW READY",
        "recommendedAllocation": 3000.0,
    }

    allocations = (
        current_production_allocations(
            stocks={
                "OPEN": stock,
            },
            quick_flip_previews=[
                {
                    "status": "PREVIEW READY",
                    "symbol": "SOUN",
                    "recommendedAllocation": 2500.0,
                }
            ],
        )
    )

    assert allocations[
        (
            "MANIPULATION",
            "OPEN",
        )
    ] == 3000.0

    assert allocations[
        (
            "QUICK_FLIP",
            "SOUN",
        )
    ] == 2500.0


def test_duplicate_quick_flip_previews_are_accumulated():
    allocations = (
        current_production_allocations(
            stocks={},
            quick_flip_previews=[
                {
                    "status": "PREVIEW READY",
                    "symbol": "SOUN",
                    "recommendedAllocation": 1200.0,
                },
                {
                    "status": "PREVIEW READY",
                    "symbol": "SOUN",
                    "recommendedAllocation": 800.0,
                },
            ],
        )
    )

    assert allocations[
        (
            "QUICK_FLIP",
            "SOUN",
        )
    ] == 2000.0


def test_atomic_shadow_payload_write(
    tmp_path,
):
    import json

    from trading_bot.risk_adjusted_live_shadow import (
        write_live_shadow_payload_atomic,
    )

    output = (
        Path(tmp_path)
        / "shadow"
        / "2026-08-14.json"
    )

    payload = {
        "tradingDate": "2026-08-14",
        "shadowOnly": True,
        "productionSizingChanged": False,
    }

    written = (
        write_live_shadow_payload_atomic(
            payload=payload,
            output_path=output,
        )
    )

    assert written == output
    assert output.exists()

    loaded = json.loads(
        output.read_text(
            encoding="utf-8"
        )
    )

    assert loaded == payload
    assert not output.with_suffix(
        ".json.tmp"
    ).exists()


def test_safe_bot_shadow_wrapper_isolates_failure(
    capsys,
):
    from trading_bot.bot import TradingBot

    bot = object.__new__(
        TradingBot
    )

    def fail_shadow(
        *,
        date_str,
    ):
        raise RuntimeError(
            "shadow failure"
        )

    bot.write_risk_adjusted_live_shadow = (
        fail_shadow
    )

    bot._run_risk_adjusted_live_shadow_safely(
        date_str="2026-08-14",
    )

    output = capsys.readouterr().out

    assert (
        "Risk-adjusted capital shadow "
        "report failed"
        in output
    )

    assert (
        "Live preview sizing remains unchanged"
        in output
    )


def test_safe_bot_shadow_wrapper_calls_writer():
    from trading_bot.bot import TradingBot

    bot = object.__new__(
        TradingBot
    )

    events = []

    bot.write_risk_adjusted_live_shadow = (
        lambda *,
        date_str: events.append(
            date_str
        )
    )

    bot._run_risk_adjusted_live_shadow_safely(
        date_str="2026-08-14",
    )

    assert events == [
        "2026-08-14"
    ]



def test_causal_dominance_shadow_manipulation_consumes_zero_reserve_pool():
    opportunities = [
        RiskAdjustedOpportunity(
            symbol="OPEN",
            strategy="MANIPULATION",
            expected_reward_pct=2.0,
            expected_risk_pct=1.0,
        ),
        RiskAdjustedOpportunity(
            symbol="SOUN",
            strategy="MANIPULATION",
            expected_reward_pct=1.5,
            expected_risk_pct=1.0,
        ),
        RiskAdjustedOpportunity(
            symbol="RIVN",
            strategy="QUICK_FLIP",
            expected_reward_pct=1.0,
            expected_risk_pct=1.0,
        ),
    ]

    payload = (
        build_causal_dominance_equal_weight_shadow(
            opportunities=opportunities,
            quick_flip_results={},
            quick_flip_previews=[
                {
                    "status": "PREVIEW READY",
                    "symbol": "RIVN",
                    "confirmationTime": (
                        "2026-08-14T14:00:00+00:00"
                    ),
                }
            ],
            deployable_pool=9000.0,
            production_allocations={},
        )
    )

    assert (
        payload[
            "quickFlipReserveFraction"
        ]
        == 0.0
    )

    assert len(
        payload["events"]
    ) == 1

    event = payload[
        "events"
    ][0]

    assert (
        event["eventTime"]
        == "09:45_ET"
    )

    assert (
        event["decisionReason"]
        == "EQUAL_WEIGHT_PORTFOLIO"
    )

    funded = [
        item
        for item
        in event["allocations"]
        if item["allocationWeight"]
        > 0
    ]

    assert len(funded) == 2

    assert {
        item[
            "recommendedAllocation"
        ]
        for item in funded
    } == {
        4500.0,
    }

    assert payload["allocated"] == 9000.0
    assert payload["cashRetained"] == 0.0

    assert (
        payload[
            "quickFlipCandidatesObserved"
        ]
        == ["RIVN"]
    )


def test_causal_dominance_shadow_uses_first_qf_confirmation_when_no_manipulation():
    opportunities = [
        RiskAdjustedOpportunity(
            symbol="EARLY",
            strategy="QUICK_FLIP",
            expected_reward_pct=1.0,
            expected_risk_pct=1.0,
        ),
        RiskAdjustedOpportunity(
            symbol="LATE",
            strategy="QUICK_FLIP",
            expected_reward_pct=2.0,
            expected_risk_pct=1.0,
        ),
    ]

    payload = (
        build_causal_dominance_equal_weight_shadow(
            opportunities=opportunities,
            quick_flip_results={},
            quick_flip_previews=[
                {
                    "status": "PREVIEW READY",
                    "symbol": "LATE",
                    "confirmationTime": (
                        "2026-08-14T14:15:00+00:00"
                    ),
                },
                {
                    "status": "PREVIEW READY",
                    "symbol": "EARLY",
                    "confirmationTime": (
                        "2026-08-14T14:00:00+00:00"
                    ),
                },
            ],
            deployable_pool=5000.0,
            production_allocations={},
        )
    )

    assert len(
        payload["events"]
    ) == 1

    event = payload[
        "events"
    ][0]

    assert (
        event["eventTime"]
        == "2026-08-14T14:00:00+00:00"
    )

    funded = [
        item
        for item
        in event["allocations"]
        if item["allocationWeight"]
        > 0
    ]

    assert len(funded) == 1
    assert funded[0]["symbol"] == "EARLY"

    assert (
        funded[0][
            "recommendedAllocation"
        ]
        == 5000.0
    )

    assert payload["cashRetained"] == 0.0



def test_live_payload_preserves_v2_and_adds_causal_dominance_shadow(
    monkeypatch,
):
    import trading_bot.risk_adjusted_live_shadow as live_module

    from trading_bot.risk_adjusted_live_shadow import (
        build_live_shadow_payload,
    )

    opportunities = [
        RiskAdjustedOpportunity(
            symbol="OPEN",
            strategy="MANIPULATION",
            expected_reward_pct=2.0,
            expected_risk_pct=1.0,
        ),
        RiskAdjustedOpportunity(
            symbol="SOUN",
            strategy="MANIPULATION",
            expected_reward_pct=1.5,
            expected_risk_pct=1.0,
        ),
    ]

    history = SimpleNamespace(
        source_path=Path(
            "runtime/research/"
            "scanner_realized_master_"
            "2026-03-02_to_2026-08-13.csv"
        ),
        source_start_date="2026-03-02",
        source_end_date="2026-08-13",
        performance=SimpleNamespace(
            strict=True,
            manipulation=SimpleNamespace(
                filled_trades=100,
            ),
            quick_flip=SimpleNamespace(
                filled_trades=30,
            ),
        ),
    )

    monkeypatch.setattr(
        live_module,
        "build_live_opportunities",
        lambda **kwargs: list(
            opportunities
        ),
    )

    monkeypatch.setattr(
        live_module,
        "add_previewed_quick_flip_opportunities",
        lambda **kwargs: list(
            kwargs["opportunities"]
        ),
    )

    monkeypatch.setattr(
        live_module,
        "current_production_allocations",
        lambda **kwargs: {
            (
                "MANIPULATION",
                "OPEN",
            ): 3000.0,
            (
                "MANIPULATION",
                "SOUN",
            ): 6000.0,
        },
    )

    payload = build_live_shadow_payload(
        trading_date="2026-08-14",
        history=history,
        stocks={},
        quick_flip_results={},
        quick_flip_previews=[],
        deployable_pool=9000.0,
    )

    # Existing V2 shadow output remains present.
    assert (
        "comparisons"
        in payload
    )

    assert (
        "decisionReason"
        in payload
    )

    assert (
        payload[
            "productionSizingChanged"
        ]
        is False
    )

    assert (
        payload["shadowOnly"]
        is True
    )

    # New policy is additional observation-only output.
    assert (
        "dominanceEqualWeightShadow"
        in payload
    )

    shadow = payload[
        "dominanceEqualWeightShadow"
    ]

    assert (
        shadow["method"]
        == (
            "CAUSAL_DOMINANCE_"
            "EQUAL_WEIGHT_SHADOW_V1"
        )
    )

    assert (
        shadow[
            "productionSizingChanged"
        ]
        is False
    )

    assert (
        shadow["shadowOnly"]
        is True
    )

    assert (
        shadow[
            "quickFlipReserveFraction"
        ]
        == 0.0
    )

    assert (
        shadow[
            "quickFlipAutomaticStopLoss"
        ]
        is False
    )

    assert len(
        shadow["events"]
    ) == 1

    event = shadow[
        "events"
    ][0]

    assert (
        event["eventTime"]
        == "09:45_ET"
    )

    assert (
        event["decisionReason"]
        == "EQUAL_WEIGHT_PORTFOLIO"
    )

    funded = [
        item
        for item
        in event["allocations"]
        if item[
            "allocationWeight"
        ]
        > 0
    ]

    assert len(
        funded
    ) == 2

    assert {
        item[
            "recommendedAllocation"
        ]
        for item in funded
    } == {
        4500.0,
    }

    production = {
        (
            item["strategy"],
            item["symbol"],
        ): item[
            "productionRecommendedAllocation"
        ]
        for item in funded
    }

    assert production[
        (
            "MANIPULATION",
            "OPEN",
        )
    ] == 3000.0

    assert production[
        (
            "MANIPULATION",
            "SOUN",
        )
    ] == 6000.0
