import math

import pytest

from trading_bot.models import Stock
from trading_bot.quick_flip_strategy import (
    QuickFlipSignal,
)
from trading_bot.scanner import StockStats
from trading_bot.scanner_research import (
    build_factor_scores,
    log_dollar_volume_score,
    log_volume_score,
    manipulation_opportunity,
    quick_flip_opportunity,
)


def stats(
        symbol,
        *,
        volume,
        price,
        range_pct,
):
    return StockStats(
        symbol=symbol,
        valid_bars=30,
        avg_volume=volume,
        avg_price=price,
        avg_range=(
            price
            * range_pct
            / 100.0
        ),
        avg_range_pct=range_pct,
    )


def test_log_volume_control_matches_production_score():
    candidate = stats(
        "TEST",
        volume=1_500_000,
        price=10,
        range_pct=6,
    )

    assert log_volume_score(
        candidate
    ) == pytest.approx(
        candidate.ranking_score
    )


def test_log_dollar_volume_rewards_more_dollar_liquidity():
    low_price = stats(
        "LOW",
        volume=1_000_000,
        price=3,
        range_pct=6,
    )

    high_price = stats(
        "HIGH",
        volume=1_000_000,
        price=30,
        range_pct=6,
    )

    assert (
        log_dollar_volume_score(
            high_price
        )
        >
        log_dollar_volume_score(
            low_price
        )
    )


def test_factor_scores_are_cross_sectionally_standardised():
    rows = [
        stats(
            "A",
            volume=700_000,
            price=5,
            range_pct=4,
        ),
        stats(
            "B",
            volume=1_500_000,
            price=12,
            range_pct=6,
        ),
        stats(
            "C",
            volume=4_000_000,
            price=25,
            range_pct=8,
        ),
    ]

    scores = build_factor_scores(
        rows
    )

    assert sum(
        score.range_z
        for score in scores
    ) == pytest.approx(
        0.0,
        abs=1e-12,
    )

    assert sum(
        score.log_dollar_volume_z
        for score in scores
    ) == pytest.approx(
        0.0,
        abs=1e-12,
    )

    assert max(
        scores,
        key=lambda row: (
            row.equal_weight_factor_score
        ),
    ).symbol == "C"


def test_factor_scores_handle_constant_factor():
    rows = [
        stats(
            "A",
            volume=1_000_000,
            price=10,
            range_pct=5,
        ),
        stats(
            "B",
            volume=1_000_000,
            price=10,
            range_pct=5,
        ),
    ]

    scores = build_factor_scores(
        rows
    )

    assert all(
        score.equal_weight_factor_score
        == pytest.approx(0.0)
        for score in scores
    )


def test_manipulation_opportunity_uses_trading_stop():
    stock = Stock(
        symbol="TEST"
    )

    stock.limit_buy = 10.00
    stock.limit_sell = 10.60
    stock.trading_stop_loss = 9.80
    stock.atr = 1.20

    opportunity = (
        manipulation_opportunity(
            stock
        )
    )

    assert opportunity is not None
    assert (
        opportunity.potential_reward
        == pytest.approx(0.60)
    )
    assert (
        opportunity.potential_risk
        == pytest.approx(0.20)
    )
    assert (
        opportunity.reward_risk
        == pytest.approx(3.0)
    )
    assert (
        opportunity.reward_pct
        == pytest.approx(6.0)
    )
    assert (
        opportunity.reward_atr
        == pytest.approx(0.5)
    )


def test_manipulation_opportunity_rejects_invalid_risk():
    stock = Stock(
        symbol="TEST"
    )

    stock.limit_buy = 10.00
    stock.limit_sell = 10.50
    stock.trading_stop_loss = 10.10

    assert (
        manipulation_opportunity(stock)
        is None
    )


def test_quick_flip_opportunity_uses_targets_and_atr():
    signal = QuickFlipSignal(
        symbol="TEST",
        signal="INVEST",
        pattern="HAMMER",
        status="CONFIRMED",
        detail="test",
        entry_price=9.50,
        take_profit_1=10.00,
        take_profit_2=11.00,
        opening_range_high=11.00,
        opening_range_low=10.00,
        opening_range_size=1.00,
        atr_14=2.00,
        liquidity_threshold=0.50,
    )

    opportunity = (
        quick_flip_opportunity(
            signal
        )
    )

    assert opportunity is not None

    assert (
        opportunity.tp1_reward
        == pytest.approx(0.50)
    )

    assert (
        opportunity.tp2_reward
        == pytest.approx(1.50)
    )

    assert (
        opportunity.tp1_reward_atr
        == pytest.approx(0.25)
    )

    assert (
        opportunity.tp2_reward_atr
        == pytest.approx(0.75)
    )


def test_quick_flip_does_not_require_fake_stop_loss():
    signal = QuickFlipSignal(
        symbol="TEST",
        signal="INVEST",
        pattern="HAMMER",
        status="CONFIRMED",
        detail="test",
        entry_price=5.00,
        take_profit_1=5.25,
        take_profit_2=5.75,
        opening_range_high=5.75,
        opening_range_low=5.25,
        opening_range_size=0.50,
        atr_14=1.00,
        liquidity_threshold=0.25,
    )

    opportunity = (
        quick_flip_opportunity(
            signal
        )
    )

    assert opportunity is not None
    assert not hasattr(
        opportunity,
        "reward_risk",
    )
