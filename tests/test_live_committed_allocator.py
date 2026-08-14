from types import SimpleNamespace

import trading_bot.live_committed_allocator as module

from trading_bot.risk_adjusted_allocator import (
    RiskAdjustedOpportunity,
)


def history():
    return SimpleNamespace(
        manipulation=object(),
        quick_flip=object(),
    )


def test_live_manipulation_uses_committed_dominance_policy(
    monkeypatch,
):
    seen = {}

    def load_history(**kwargs):
        seen.update(kwargs)
        return history()

    monkeypatch.setattr(
        module,
        "load_live_committed_history",
        load_history,
    )

    def opportunity(stock, *, performance):
        reward = (
            3.0
            if stock.symbol == "BEST"
            else 1.0
        )

        return RiskAdjustedOpportunity(
            symbol=stock.symbol,
            strategy="MANIPULATION",
            expected_reward_pct=reward,
            expected_risk_pct=1.0,
        )

    monkeypatch.setattr(
        module,
        "build_manipulation_opportunity",
        opportunity,
    )

    stocks = {
        "BEST": SimpleNamespace(
            symbol="BEST",
            signal="INVEST",
        ),
        "OTHER": SimpleNamespace(
            symbol="OTHER",
            signal="INVEST",
        ),
    }

    plan = (
        module
        .build_live_manipulation_allocation_plan(
            stocks=stocks,
            trading_date="2026-08-17",
            deployable_pool=9000.0,
        )
    )

    assert seen["trading_date"] == (
        "2026-08-17"
    )

    assert seen["research_dir"] == "runtime/research"

    assert (
        plan.decision_reason
        == "DOMINANT_OPPORTUNITY"
    )

    funded = [
        item
        for item in plan.allocations
        if item.allocation_weight > 0
    ]

    assert len(funded) == 1
    assert funded[0].symbol == "BEST"
    assert (
        funded[0].recommended_allocation
        == 9000.0
    )


def test_live_manipulation_equal_weights_when_not_dominant(
    monkeypatch,
):
    monkeypatch.setattr(
        module,
        "load_live_committed_history",
        lambda **kwargs: history(),
    )

    rewards = {
        "A": 1.4,
        "B": 1.2,
    }

    monkeypatch.setattr(
        module,
        "build_manipulation_opportunity",
        lambda stock, *, performance: (
            RiskAdjustedOpportunity(
                symbol=stock.symbol,
                strategy="MANIPULATION",
                expected_reward_pct=(
                    rewards[stock.symbol]
                ),
                expected_risk_pct=1.0,
            )
        ),
    )

    plan = (
        module
        .build_live_manipulation_allocation_plan(
            stocks={
                symbol: SimpleNamespace(
                    symbol=symbol,
                    signal="INVEST",
                )
                for symbol in ("A", "B")
            },
            trading_date="2026-08-17",
            deployable_pool=9000.0,
        )
    )

    assert (
        plan.decision_reason
        == "EQUAL_WEIGHT_PORTFOLIO"
    )

    assert {
        item.recommended_allocation
        for item in plan.allocations
    } == {
        4500.0,
    }


def test_live_quick_flip_group_uses_same_committed_policy(
    monkeypatch,
):
    monkeypatch.setattr(
        module,
        "load_live_committed_history",
        lambda **kwargs: history(),
    )

    monkeypatch.setattr(
        module,
        "build_quick_flip_opportunity",
        lambda signal, *, performance: (
            RiskAdjustedOpportunity(
                symbol=signal.symbol,
                strategy="QUICK_FLIP",
                expected_reward_pct=(
                    3.0
                    if signal.symbol == "BEST"
                    else 1.0
                ),
                expected_risk_pct=1.0,
            )
        ),
    )

    results = {
        symbol: SimpleNamespace(
            signal=SimpleNamespace(
                symbol=symbol,
                signal="INVEST",
                confirmation_time=(
                    "2026-08-17T14:00:00+00:00"
                ),
            )
        )
        for symbol in (
            "BEST",
            "OTHER",
        )
    }

    plan = (
        module
        .build_live_quick_flip_allocation_plan(
            results=results,
            trading_date="2026-08-17",
            deployable_pool=6000.0,
        )
    )

    assert (
        plan.decision_reason
        == "DOMINANT_OPPORTUNITY"
    )

    funded = [
        item
        for item in plan.allocations
        if item.allocation_weight > 0
    ]

    assert len(funded) == 1
    assert funded[0].symbol == "BEST"
    assert (
        funded[0].recommended_allocation
        == 6000.0
    )

def test_live_quick_flip_uses_earliest_confirmation_group_only(
    monkeypatch,
):
    monkeypatch.setattr(
        module,
        "load_live_committed_history",
        lambda **kwargs: history(),
    )

    monkeypatch.setattr(
        module,
        "build_quick_flip_opportunity",
        lambda signal, *, performance: (
            RiskAdjustedOpportunity(
                symbol=signal.symbol,
                strategy="QUICK_FLIP",
                expected_reward_pct=(
                    10.0
                    if signal.symbol == "LATE"
                    else 2.0
                ),
                expected_risk_pct=1.0,
            )
        ),
    )

    results = {
        "EARLY": SimpleNamespace(
            signal=SimpleNamespace(
                symbol="EARLY",
                signal="INVEST",
                confirmation_time=(
                    "2026-08-17T14:00:00+00:00"
                ),
            )
        ),
        "LATE": SimpleNamespace(
            signal=SimpleNamespace(
                symbol="LATE",
                signal="INVEST",
                confirmation_time=(
                    "2026-08-17T14:20:00+00:00"
                ),
            )
        ),
    }

    plan = (
        module
        .build_live_quick_flip_allocation_plan(
            results=results,
            trading_date="2026-08-17",
            deployable_pool=5000.0,
        )
    )

    assert {
        item.symbol
        for item in plan.allocations
    } == {
        "EARLY",
    }

    assert (
        plan.allocations[0]
        .recommended_allocation
        == 5000.0
    )


def test_live_quick_flip_ranks_same_confirmation_group_together(
    monkeypatch,
):
    monkeypatch.setattr(
        module,
        "load_live_committed_history",
        lambda **kwargs: history(),
    )

    rewards = {
        "A": 3.0,
        "B": 1.0,
        "LATER": 100.0,
    }

    monkeypatch.setattr(
        module,
        "build_quick_flip_opportunity",
        lambda signal, *, performance: (
            RiskAdjustedOpportunity(
                symbol=signal.symbol,
                strategy="QUICK_FLIP",
                expected_reward_pct=(
                    rewards[signal.symbol]
                ),
                expected_risk_pct=1.0,
            )
        ),
    )

    first_time = (
        "2026-08-17T14:00:00+00:00"
    )

    results = {
        "A": SimpleNamespace(
            signal=SimpleNamespace(
                symbol="A",
                signal="INVEST",
                confirmation_time=first_time,
            )
        ),
        "B": SimpleNamespace(
            signal=SimpleNamespace(
                symbol="B",
                signal="INVEST",
                confirmation_time=first_time,
            )
        ),
        "LATER": SimpleNamespace(
            signal=SimpleNamespace(
                symbol="LATER",
                signal="INVEST",
                confirmation_time=(
                    "2026-08-17T14:30:00+00:00"
                ),
            )
        ),
    }

    plan = (
        module
        .build_live_quick_flip_allocation_plan(
            results=results,
            trading_date="2026-08-17",
            deployable_pool=6000.0,
        )
    )

    assert {
        item.symbol
        for item in plan.allocations
    } == {
        "A",
        "B",
    }

    assert (
        plan.decision_reason
        == "DOMINANT_OPPORTUNITY"
    )

    funded = [
        item
        for item in plan.allocations
        if item.allocation_weight > 0
    ]

    assert len(funded) == 1
    assert funded[0].symbol == "A"
    assert (
        funded[0].recommended_allocation
        == 6000.0
    )


def test_live_quick_flip_missing_confirmation_is_not_sequenced(
    monkeypatch,
):
    monkeypatch.setattr(
        module,
        "load_live_committed_history",
        lambda **kwargs: history(),
    )

    monkeypatch.setattr(
        module,
        "build_quick_flip_opportunity",
        lambda signal, *, performance: (
            RiskAdjustedOpportunity(
                symbol=signal.symbol,
                strategy="QUICK_FLIP",
                expected_reward_pct=2.0,
                expected_risk_pct=1.0,
            )
        ),
    )

    results = {
        "NO_TIME": SimpleNamespace(
            signal=SimpleNamespace(
                symbol="NO_TIME",
                signal="INVEST",
                confirmation_time=None,
            )
        )
    }

    plan = (
        module
        .build_live_quick_flip_allocation_plan(
            results=results,
            trading_date="2026-08-17",
            deployable_pool=5000.0,
        )
    )

    assert (
        plan.decision_reason
        == "NO_CANDIDATES"
    )

    assert plan.cash_retained == 5000.0


def test_live_history_uses_walk_forward_production_context(
    monkeypatch,
    tmp_path,
):
    source = (
        tmp_path
        / "scanner_realized_master_"
        "2026-03-02_to_2026-08-13.csv"
    )

    source.write_text(
        "date,symbol\n",
        encoding="utf-8",
    )

    raw_rows = [
        {
            "date": "2026-08-13",
            "symbol": "BBAI",
        },
    ]

    expected_production_history = [
        {
            "date": "2026-08-13",
            "symbol": "BBAI",
            "v1_selected": "YES",
        },
    ]

    manipulation = object()
    quick_flip = object()

    seen = []

    monkeypatch.setattr(
        module,
        "find_latest_realized_master_before",
        lambda **kwargs: source,
    )

    monkeypatch.setattr(
        module,
        "load_master_rows",
        lambda source_path: raw_rows,
    )

    def fake_production_rows(
        rows,
        *,
        permanent_symbols,
    ):
        assert rows is raw_rows

        assert permanent_symbols == {
            str(symbol).upper()
            for symbol in module.TICKERS
        }

        return (
            expected_production_history
        )

    monkeypatch.setattr(
        module,
        "production_rows",
        fake_production_rows,
    )

    def fake_performance_before_date(
        *,
        production_history,
        trading_date,
        strategy,
    ):
        assert (
            production_history
            is expected_production_history
        )

        assert (
            trading_date
            == "2026-08-14"
        )

        seen.append(
            strategy
        )

        if strategy == "MANIPULATION":
            return manipulation

        if strategy == "QUICK_FLIP":
            return quick_flip

        raise AssertionError(
            "Unexpected strategy."
        )

    monkeypatch.setattr(
        module,
        "performance_before_date",
        fake_performance_before_date,
    )

    result = (
        module
        .load_live_committed_history(
            trading_date="2026-08-14",
            research_dir=tmp_path,
        )
    )

    assert result.source_path == source

    assert (
        result.production_history
        is expected_production_history
    )

    assert (
        result.manipulation
        is manipulation
    )

    assert (
        result.quick_flip
        is quick_flip
    )

    assert seen == [
        "MANIPULATION",
        "QUICK_FLIP",
    ]
