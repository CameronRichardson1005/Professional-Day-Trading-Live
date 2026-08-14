from datetime import datetime
from types import SimpleNamespace

import pytest

from trading_bot.models import Stock
from trading_bot.quick_flip_strategy import (
    QuickFlipSignal,
)
from trading_bot.risk_adjusted_allocator import (
    build_shadow_risk_adjusted_plan,
)
from trading_bot.risk_adjusted_strategy_adapters import (
    build_manipulation_opportunity,
    build_quick_flip_opportunity,
)


def history(
    *,
    expectancy=1.0,
    win_rate=60.0,
    filled=30,
    mfe=5.0,
    mae=-2.0,
    tail_mae=None,
):
    return SimpleNamespace(
        expectancy_per_filled_trade_pct=(
            expectancy
        ),
        win_rate_pct=win_rate,
        filled_trades=filled,
        average_mfe_pct=mfe,
        average_mae_pct=mae,
        tail_mae_75_pct=(
            (
                abs(float(mae))
                if mae is not None
                else None
            )
            if tail_mae is None
            else tail_mae
        ),
    )


def manipulation_stock(
    *,
    symbol="OPEN",
    entry=10.0,
    target=11.0,
    stop=9.5,
):
    return Stock(
        symbol=symbol,
        signal="INVEST",
        limit_buy=entry,
        limit_sell=target,
        trading_stop_loss=stop,
    )


def quick_flip_signal(
    *,
    symbol="SOUN",
    entry=10.0,
    tp1=10.5,
    tp2=11.0,
):
    now = datetime(
        2026,
        8,
        14,
        10,
        0,
    )

    return QuickFlipSignal(
        symbol=symbol,
        signal="INVEST",
        pattern="HAMMER",
        status="CONFIRMED",
        detail="test",
        entry_price=entry,
        take_profit_1=tp1,
        take_profit_2=tp2,
        opening_range_high=11.0,
        opening_range_low=10.5,
        opening_range_size=1.0,
        atr_14=2.0,
        liquidity_threshold=0.5,
        reversal_time=now,
        confirmation_time=now,
    )


def test_manipulation_uses_real_stop_risk():
    opportunity = (
        build_manipulation_opportunity(
            manipulation_stock(
                entry=10.0,
                target=11.0,
                stop=9.5,
            ),
            performance=history(),
        )
    )

    assert (
        opportunity.expected_reward_pct
        == 10.0
    )

    assert (
        opportunity.expected_risk_pct
        == 5.0
    )


def test_manipulation_preserves_history():
    opportunity = (
        build_manipulation_opportunity(
            manipulation_stock(),
            performance=history(
                expectancy=1.4,
                win_rate=64.0,
                filled=42,
            ),
        )
    )

    assert opportunity.expectancy_pct == 1.4
    assert opportunity.win_rate_pct == 64.0
    assert opportunity.historical_samples == 42


def test_quick_flip_uses_absolute_mae_for_risk():
    opportunity = (
        build_quick_flip_opportunity(
            quick_flip_signal(
                entry=10.0,
                tp1=10.5,
                tp2=11.0,
            ),
            performance=history(
                mfe=6.0,
                mae=-1.8,
            ),
        )
    )

    assert (
        opportunity.expected_risk_pct
        == 1.8
    )


def test_quick_flip_uses_tail_mae_instead_of_average_mae():
    opportunity = (
        build_quick_flip_opportunity(
            quick_flip_signal(
                entry=10.0,
                tp1=10.5,
                tp2=11.0,
            ),
            performance=history(
                mfe=6.0,
                mae=-1.5,
                tail_mae=3.75,
            ),
        )
    )

    assert (
        opportunity.expected_risk_pct
        == 3.75
    )


def test_quick_flip_reward_is_capped_at_tp2():
    opportunity = (
        build_quick_flip_opportunity(
            quick_flip_signal(
                entry=10.0,
                tp1=10.5,
                tp2=11.0,
            ),
            performance=history(
                mfe=15.0,
                mae=-2.0,
            ),
        )
    )

    assert (
        opportunity.expected_reward_pct
        == 10.0
    )


def test_quick_flip_uses_mfe_when_below_tp2():
    opportunity = (
        build_quick_flip_opportunity(
            quick_flip_signal(
                entry=10.0,
                tp1=10.5,
                tp2=11.0,
            ),
            performance=history(
                mfe=6.25,
                mae=-2.0,
            ),
        )
    )

    assert (
        opportunity.expected_reward_pct
        == 6.25
    )


def test_quick_flip_requires_mae_history():
    with pytest.raises(
        ValueError,
        match="no historical Quick Flip tail MAE",
    ):
        build_quick_flip_opportunity(
            quick_flip_signal(),
            performance=history(
                mae=None,
                tail_mae=None,
            ),
        )


def test_quick_flip_does_not_create_stop():
    signal = quick_flip_signal()

    build_quick_flip_opportunity(
        signal,
        performance=history(),
    )

    assert not hasattr(
        signal,
        "stop_loss",
    )


def test_best_cross_strategy_trade_can_take_pool():
    manipulation = (
        build_manipulation_opportunity(
            manipulation_stock(
                symbol="OPEN",
                entry=10.0,
                target=10.6,
                stop=9.6,
            ),
            performance=history(
                expectancy=0.2,
                win_rate=52.0,
                filled=30,
            ),
        )
    )

    quick_flip = (
        build_quick_flip_opportunity(
            quick_flip_signal(
                symbol="SOUN",
                entry=10.0,
                tp1=10.8,
                tp2=11.5,
            ),
            performance=history(
                expectancy=1.5,
                win_rate=68.0,
                filled=30,
                mfe=12.0,
                mae=-2.0,
            ),
        )
    )

    plan = build_shadow_risk_adjusted_plan(
        [
            manipulation,
            quick_flip,
        ],
        deployable_pool=9000.0,
        dominance_ratio=1.75,
    )

    by_symbol = {
        item.symbol: item
        for item in plan.allocations
    }

    assert (
        by_symbol["SOUN"]
        .recommended_allocation
        == 9000.0
    )

    assert (
        by_symbol["OPEN"]
        .recommended_allocation
        == 0.0
    )


def test_adapter_output_remains_shadow_only():
    opportunity = (
        build_manipulation_opportunity(
            manipulation_stock(),
            performance=history(),
        )
    )

    plan = build_shadow_risk_adjusted_plan(
        [opportunity],
        deployable_pool=5000.0,
    )

    assert plan.shadow_only is True
