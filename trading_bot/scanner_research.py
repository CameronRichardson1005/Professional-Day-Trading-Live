from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import mean, pstdev
from typing import Iterable

from .models import Stock
from .quick_flip_strategy import QuickFlipSignal
from .scanner import StockStats


DOLLAR_VOLUME_SCALE = 1_000_000.0


@dataclass(frozen=True)
class ScannerFactorScores:
    symbol: str
    log_volume_score: float
    log_dollar_volume_score: float
    range_z: float
    log_dollar_volume_z: float
    equal_weight_factor_score: float


@dataclass(frozen=True)
class ManipulationOpportunity:
    potential_reward: float
    potential_risk: float
    reward_risk: float
    reward_pct: float
    reward_atr: float | None


@dataclass(frozen=True)
class QuickFlipOpportunity:
    tp1_reward: float
    tp2_reward: float
    tp1_reward_pct: float
    tp2_reward_pct: float
    tp1_reward_atr: float
    tp2_reward_atr: float


def log_volume_score(stats: StockStats) -> float:
    """
    Production-control formula.

    This intentionally matches StockStats.ranking_score.
    """
    return (
        stats.avg_range_pct
        * math.log1p(
            stats.avg_volume / 500_000.0
        )
    )


def log_dollar_volume(stats: StockStats) -> float:
    dollar_volume = (
        stats.avg_price
        * stats.avg_volume
    )

    return math.log1p(
        dollar_volume / DOLLAR_VOLUME_SCALE
    )


def log_dollar_volume_score(
        stats: StockStats,
) -> float:
    """
    Research V2.

    Preserve percentage movement as the primary factor while
    replacing raw-share liquidity with dollar liquidity.
    """
    return (
        stats.avg_range_pct
        * log_dollar_volume(stats)
    )


def _z_scores(
        values: list[float],
) -> list[float]:
    if not values:
        return []

    centre = mean(values)
    dispersion = pstdev(values)

    if dispersion == 0:
        return [
            0.0
            for _ in values
        ]

    return [
        (value - centre) / dispersion
        for value in values
    ]


def build_factor_scores(
        statistics: Iterable[StockStats],
) -> list[ScannerFactorScores]:
    """
    Research V3.

    Equal-weight cross-sectional factor model:
      50% range-percent z-score
      50% log-dollar-volume z-score

    Equal weights are only a neutral research baseline.
    They are not production-optimized weights.
    """
    rows = list(statistics)

    range_values = [
        row.avg_range_pct
        for row in rows
    ]

    dollar_values = [
        log_dollar_volume(row)
        for row in rows
    ]

    range_z = _z_scores(
        range_values
    )

    dollar_z = _z_scores(
        dollar_values
    )

    return [
        ScannerFactorScores(
            symbol=row.symbol,
            log_volume_score=(
                log_volume_score(row)
            ),
            log_dollar_volume_score=(
                log_dollar_volume_score(row)
            ),
            range_z=range_score,
            log_dollar_volume_z=dollar_score,
            equal_weight_factor_score=(
                0.5 * range_score
                + 0.5 * dollar_score
            ),
        )
        for row, range_score, dollar_score
        in zip(
            rows,
            range_z,
            dollar_z,
            strict=True,
        )
    ]


def manipulation_opportunity(
        stock: Stock,
) -> ManipulationOpportunity | None:
    """
    Prospective setup geometry only.

    Uses values known when the Manipulation setup is created.
    No future prices or realized outcomes are used.
    """
    if (
        stock.limit_buy is None
        or stock.limit_sell is None
        or stock.trading_stop_loss is None
    ):
        return None

    entry = float(
        stock.limit_buy
    )

    target = float(
        stock.limit_sell
    )

    stop = float(
        stock.trading_stop_loss
    )

    if entry <= 0:
        return None

    reward = target - entry
    risk = entry - stop

    if reward < 0 or risk <= 0:
        return None

    reward_atr = None

    if (
        stock.atr is not None
        and float(stock.atr) > 0
    ):
        reward_atr = (
            reward / float(stock.atr)
        )

    return ManipulationOpportunity(
        potential_reward=reward,
        potential_risk=risk,
        reward_risk=reward / risk,
        reward_pct=(
            reward / entry
        ) * 100.0,
        reward_atr=reward_atr,
    )


def quick_flip_opportunity(
        signal: QuickFlipSignal,
) -> QuickFlipOpportunity | None:
    """
    Prospective Quick Flip reward geometry.

    Quick Flip intentionally has no automatic stop, so this
    function does NOT manufacture a reward/risk ratio.
    """
    if (
        signal.entry_price is None
        or signal.take_profit_1 is None
        or signal.take_profit_2 is None
        or signal.atr_14 <= 0
    ):
        return None

    entry = float(
        signal.entry_price
    )

    if entry <= 0:
        return None

    tp1_reward = (
        float(signal.take_profit_1)
        - entry
    )

    tp2_reward = (
        float(signal.take_profit_2)
        - entry
    )

    if (
        tp1_reward < 0
        or tp2_reward < 0
    ):
        return None

    atr = float(
        signal.atr_14
    )

    return QuickFlipOpportunity(
        tp1_reward=tp1_reward,
        tp2_reward=tp2_reward,
        tp1_reward_pct=(
            tp1_reward / entry
        ) * 100.0,
        tp2_reward_pct=(
            tp2_reward / entry
        ) * 100.0,
        tp1_reward_atr=(
            tp1_reward / atr
        ),
        tp2_reward_atr=(
            tp2_reward / atr
        ),
    )
