from __future__ import annotations

from typing import Any

from .models import Stock
from .quick_flip_strategy import QuickFlipSignal
from .risk_adjusted_allocator import (
    RiskAdjustedOpportunity,
)


def _optional_float(
    value: object,
) -> float | None:
    if value is None:
        return None

    return float(value)


def _historical_samples(
    performance: Any | None,
) -> int | None:
    if performance is None:
        return None

    value = getattr(
        performance,
        "filled_trades",
        None,
    )

    if value is None:
        return None

    return int(value)


def _historical_expectancy(
    performance: Any | None,
) -> float | None:
    if performance is None:
        return None

    return _optional_float(
        getattr(
            performance,
            "expectancy_per_filled_trade_pct",
            None,
        )
    )


def _historical_win_rate(
    performance: Any | None,
) -> float | None:
    if performance is None:
        return None

    return _optional_float(
        getattr(
            performance,
            "win_rate_pct",
            None,
        )
    )


def build_manipulation_opportunity(
    stock: Stock,
    *,
    performance: Any | None = None,
    setup_quality: float = 1.0,
    liquidity_quality: float = 1.0,
) -> RiskAdjustedOpportunity:
    """
    Convert a live Manipulation INVEST signal into the common
    risk-adjusted shadow-ranking format.

    Manipulation has an explicit trading stop, so downside risk is
    measured directly from entry to trading stop.
    """
    if stock.signal != "INVEST":
        raise ValueError(
            f"{stock.symbol} is not an INVEST signal."
        )

    if (
        stock.limit_buy is None
        or stock.limit_sell is None
        or stock.trading_stop_loss is None
    ):
        raise ValueError(
            f"{stock.symbol} is missing Manipulation "
            "entry, target, or trading stop."
        )

    entry = float(stock.limit_buy)
    target = float(stock.limit_sell)
    trading_stop = float(
        stock.trading_stop_loss
    )

    if entry <= 0:
        raise ValueError(
            f"{stock.symbol} has invalid entry price."
        )

    if target <= entry:
        raise ValueError(
            f"{stock.symbol} has no positive "
            "Manipulation reward."
        )

    if trading_stop >= entry:
        raise ValueError(
            f"{stock.symbol} has no positive "
            "Manipulation downside risk."
        )

    expected_reward_pct = (
        (target - entry)
        / entry
        * 100.0
    )

    expected_risk_pct = (
        (entry - trading_stop)
        / entry
        * 100.0
    )

    return RiskAdjustedOpportunity(
        symbol=stock.symbol,
        strategy="MANIPULATION",
        expected_reward_pct=round(
            expected_reward_pct,
            6,
        ),
        expected_risk_pct=round(
            expected_risk_pct,
            6,
        ),
        expectancy_pct=(
            _historical_expectancy(
                performance
            )
        ),
        win_rate_pct=(
            _historical_win_rate(
                performance
            )
        ),
        historical_samples=(
            _historical_samples(
                performance
            )
        ),
        setup_quality=setup_quality,
        liquidity_quality=(
            liquidity_quality
        ),
    )


def build_quick_flip_opportunity(
    signal: QuickFlipSignal,
    *,
    performance: Any,
    setup_quality: float = 1.0,
    liquidity_quality: float = 1.0,
) -> RiskAdjustedOpportunity:
    """
    Convert a Quick Flip INVEST signal into the common
    risk-adjusted shadow-ranking format.

    Quick Flip intentionally has no automatic stop loss.

    Risk is therefore empirical:
        historical 75th-percentile absolute MAE.

    This is a conservative ranking-risk estimate, not a stop.

    Expected reward is also empirical:
        historical average MFE, capped at today's TP2 upside.

    This does not create or imply an automatic Quick Flip stop.
    """
    if signal.signal != "INVEST":
        raise ValueError(
            f"{signal.symbol} is not a Quick Flip "
            "INVEST signal."
        )

    if (
        signal.entry_price is None
        or signal.take_profit_1 is None
        or signal.take_profit_2 is None
    ):
        raise ValueError(
            f"{signal.symbol} is missing Quick Flip "
            "entry or targets."
        )

    entry = float(signal.entry_price)
    tp1 = float(signal.take_profit_1)
    tp2 = float(signal.take_profit_2)

    if entry <= 0:
        raise ValueError(
            f"{signal.symbol} has invalid entry price."
        )

    if tp1 <= entry or tp2 <= entry:
        raise ValueError(
            f"{signal.symbol} has no positive "
            "Quick Flip target reward."
        )

    if tp2 < tp1:
        raise ValueError(
            f"{signal.symbol} has Quick Flip TP2 "
            "below TP1."
        )

    average_mfe_pct = _optional_float(
        getattr(
            performance,
            "average_mfe_pct",
            None,
        )
    )

    tail_mae_75_pct = _optional_float(
        getattr(
            performance,
            "tail_mae_75_pct",
            None,
        )
    )

    if average_mfe_pct is None:
        raise ValueError(
            f"{signal.symbol} has no historical "
            "Quick Flip MFE."
        )

    if tail_mae_75_pct is None:
        raise ValueError(
            f"{signal.symbol} has no historical "
            "Quick Flip tail MAE."
        )

    empirical_reward_pct = max(
        0.0,
        float(average_mfe_pct),
    )

    empirical_risk_pct = abs(
        float(tail_mae_75_pct)
    )

    if empirical_reward_pct <= 0:
        raise ValueError(
            f"{signal.symbol} has no positive "
            "historical Quick Flip favorable excursion."
        )

    if empirical_risk_pct <= 0:
        raise ValueError(
            f"{signal.symbol} has no measurable "
            "historical Quick Flip adverse excursion."
        )

    tp2_reward_pct = (
        (tp2 - entry)
        / entry
        * 100.0
    )

    expected_reward_pct = min(
        empirical_reward_pct,
        tp2_reward_pct,
    )

    return RiskAdjustedOpportunity(
        symbol=signal.symbol,
        strategy="QUICK_FLIP",
        expected_reward_pct=round(
            expected_reward_pct,
            6,
        ),
        expected_risk_pct=round(
            empirical_risk_pct,
            6,
        ),
        expectancy_pct=(
            _historical_expectancy(
                performance
            )
        ),
        win_rate_pct=(
            _historical_win_rate(
                performance
            )
        ),
        historical_samples=(
            _historical_samples(
                performance
            )
        ),
        setup_quality=setup_quality,
        liquidity_quality=(
            liquidity_quality
        ),
    )
