from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from statistics import mean, pstdev
from typing import Iterable

from .models import Stock
from .quick_flip_strategy import QuickFlipSignal
from .scanner import (
    ScannerRules,
    StockScanner,
    StockStats,
)


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


@dataclass(frozen=True)
class ScannerModelSelection:
    model: str
    symbol: str
    rank: int
    selected: bool
    score: float


def rank_scanner_models(
        statistics: Iterable[StockStats],
        *,
        current_symbols: Iterable[str],
        rules: ScannerRules | None = None,
) -> dict[str, list[ScannerModelSelection]]:
    """
    Rank the same eligible universe under several research models.

    V1 is the current production control.
    V2 replaces share-volume liquidity with dollar liquidity.
    V3 uses equal-weight cross-sectional standardized factors.

    All eligible candidates are returned so downstream research can
    examine rank/return relationships and information coefficients.
    The `selected` flag indicates whether the candidate falls inside
    the scanner's normal candidate limit.
    """
    rows = list(statistics)

    scanner = StockScanner(
        current_symbols=list(current_symbols),
        rules=rules,
    )

    current_set = set(
        scanner.current_symbols
    )

    eligible = [
        row
        for row in rows
        if (
            row.symbol not in current_set
            and scanner.is_eligible(row)
        )
    ]

    factor_rows = {
        row.symbol: row
        for row in build_factor_scores(
            eligible
        )
    }

    score_functions = {
        "V1_LOG_VOLUME": (
            lambda row: log_volume_score(row)
        ),
        "V2_LOG_DOLLAR_VOLUME": (
            lambda row: log_dollar_volume_score(row)
        ),
        "V3_Z_FACTOR": (
            lambda row: (
                factor_rows[
                    row.symbol
                ].equal_weight_factor_score
            )
        ),
    }

    results: dict[
        str,
        list[ScannerModelSelection],
    ] = {}

    for model, score_function in (
        score_functions.items()
    ):
        scored = [
            (
                row,
                float(score_function(row)),
            )
            for row in eligible
        ]

        scored.sort(
            key=lambda pair: (
                -pair[1],
                pair[0].symbol,
            )
        )

        results[model] = [
            ScannerModelSelection(
                model=model,
                symbol=row.symbol,
                rank=rank,
                selected=(
                    rank
                    <= scanner.rules.candidate_limit
                ),
                score=score,
            )
            for rank, (row, score)
            in enumerate(
                scored,
                start=1,
            )
        ]

    return results



# ============================================================
# V4 WEBULL RELATIVE-FACTOR RESEARCH
# ============================================================

V4_RANGE_WEIGHT = 0.30
V4_DOLLAR_VOLUME_WEIGHT = 0.20
V4_RVOL_WEIGHT = 0.20
V4_VOLUME_ACCELERATION_WEIGHT = 0.15
V4_RANGE_ACCELERATION_WEIGHT = 0.15


@dataclass(frozen=True)
class ScannerV4Factors:
    symbol: str

    range_pct_30: float
    log_dollar_volume_30: float

    prior_volume: float
    rvol: float

    avg_volume_5: float
    avg_volume_30: float
    volume_acceleration: float

    range_pct_5: float
    range_acceleration: float

    range_percentile: float
    dollar_volume_percentile: float
    rvol_percentile: float
    volume_acceleration_percentile: float
    range_acceleration_percentile: float

    v4_score: float


def _percentile_ranks(
        values: list[float],
) -> list[float]:
    """
    Cross-sectional midrank percentiles from 0 to 1.

    Tied observations receive the same percentile.
    A one-symbol universe receives 0.5.
    """
    if not values:
        return []

    if len(values) == 1:
        return [0.5]

    denominator = (
        len(values) - 1
    )

    results = []

    for value in values:
        lower = sum(
            candidate < value
            for candidate in values
        )

        equal = sum(
            candidate == value
            for candidate in values
        )

        midpoint_rank = (
            lower
            + ((equal - 1) / 2.0)
        )

        results.append(
            midpoint_rank / denominator
        )

    return results


def build_v4_factor_scores(
        *,
        daily_history: dict[
            str,
            list[dict],
        ],
        date_str: str,
        eligible_symbols: Iterable[str],
) -> list[ScannerV4Factors]:
    """
    Build Webull V4 factors using information strictly before
    `date_str`.

    Exactly 30 valid prior daily sessions are required so the
    30-session factors mean what their names imply.

    No opening/intraday information from the evaluation date is
    used, preventing scanner look-ahead bias.
    """
    trading_date = (
        datetime.strptime(
            date_str,
            "%Y-%m-%d",
        ).date()
    )

    raw_rows = []

    for symbol in sorted(
        set(eligible_symbols)
    ):
        bars = daily_history.get(
            symbol,
            [],
        )

        prior = []

        for bar in bars:
            try:
                timestamp = (
                    datetime.fromisoformat(
                        str(
                            bar["t"]
                        ).replace(
                            "Z",
                            "+00:00",
                        )
                    )
                )

                volume = float(
                    bar["v"]
                )

                close = float(
                    bar["c"]
                )

                high = float(
                    bar["h"]
                )

                low = float(
                    bar["l"]
                )

            except (
                KeyError,
                TypeError,
                ValueError,
            ):
                continue

            if (
                timestamp.date()
                >= trading_date
            ):
                continue

            if volume < 0:
                continue

            if min(
                close,
                high,
                low,
            ) <= 0:
                continue

            if high < low:
                continue

            prior.append(
                (
                    timestamp,
                    volume,
                    close,
                    high - low,
                )
            )

        prior.sort(
            key=lambda row: row[0]
        )

        if len(prior) < 30:
            continue

        window_30 = prior[-30:]
        window_5 = prior[-5:]

        avg_volume_30 = mean(
            row[1]
            for row in window_30
        )

        avg_price_30 = mean(
            row[2]
            for row in window_30
        )

        avg_range_30 = mean(
            row[3]
            for row in window_30
        )

        avg_volume_5 = mean(
            row[1]
            for row in window_5
        )

        avg_price_5 = mean(
            row[2]
            for row in window_5
        )

        avg_range_5 = mean(
            row[3]
            for row in window_5
        )

        if (
            avg_volume_30 <= 0
            or avg_price_30 <= 0
            or avg_price_5 <= 0
        ):
            continue

        range_pct_30 = (
            avg_range_30
            / avg_price_30
            * 100.0
        )

        range_pct_5 = (
            avg_range_5
            / avg_price_5
            * 100.0
        )

        if range_pct_30 <= 0:
            continue

        prior_volume = float(
            window_30[-1][1]
        )

        average_dollar_volume = (
            avg_volume_30
            * avg_price_30
        )

        log_dollar_volume_30 = (
            math.log1p(
                average_dollar_volume
                / DOLLAR_VOLUME_SCALE
            )
        )

        rvol = (
            prior_volume
            / avg_volume_30
        )

        volume_acceleration = (
            avg_volume_5
            / avg_volume_30
        )

        range_acceleration = (
            range_pct_5
            / range_pct_30
        )

        raw_rows.append({
            "symbol": symbol,
            "range_pct_30": (
                range_pct_30
            ),
            "log_dollar_volume_30": (
                log_dollar_volume_30
            ),
            "prior_volume": (
                prior_volume
            ),
            "rvol": rvol,
            "avg_volume_5": (
                avg_volume_5
            ),
            "avg_volume_30": (
                avg_volume_30
            ),
            "volume_acceleration": (
                volume_acceleration
            ),
            "range_pct_5": (
                range_pct_5
            ),
            "range_acceleration": (
                range_acceleration
            ),
        })

    range_percentiles = _percentile_ranks([
        row["range_pct_30"]
        for row in raw_rows
    ])

    dollar_percentiles = _percentile_ranks([
        row["log_dollar_volume_30"]
        for row in raw_rows
    ])

    rvol_percentiles = _percentile_ranks([
        row["rvol"]
        for row in raw_rows
    ])

    volume_accel_percentiles = (
        _percentile_ranks([
            row[
                "volume_acceleration"
            ]
            for row in raw_rows
        ])
    )

    range_accel_percentiles = (
        _percentile_ranks([
            row[
                "range_acceleration"
            ]
            for row in raw_rows
        ])
    )

    results = []

    for (
        row,
        range_percentile,
        dollar_percentile,
        rvol_percentile,
        volume_accel_percentile,
        range_accel_percentile,
    ) in zip(
        raw_rows,
        range_percentiles,
        dollar_percentiles,
        rvol_percentiles,
        volume_accel_percentiles,
        range_accel_percentiles,
        strict=True,
    ):
        score = (
            V4_RANGE_WEIGHT
            * range_percentile

            + V4_DOLLAR_VOLUME_WEIGHT
            * dollar_percentile

            + V4_RVOL_WEIGHT
            * rvol_percentile

            + V4_VOLUME_ACCELERATION_WEIGHT
            * volume_accel_percentile

            + V4_RANGE_ACCELERATION_WEIGHT
            * range_accel_percentile
        )

        results.append(
            ScannerV4Factors(
                symbol=row["symbol"],
                range_pct_30=(
                    row["range_pct_30"]
                ),
                log_dollar_volume_30=(
                    row[
                        "log_dollar_volume_30"
                    ]
                ),
                prior_volume=(
                    row["prior_volume"]
                ),
                rvol=row["rvol"],
                avg_volume_5=(
                    row["avg_volume_5"]
                ),
                avg_volume_30=(
                    row["avg_volume_30"]
                ),
                volume_acceleration=(
                    row[
                        "volume_acceleration"
                    ]
                ),
                range_pct_5=(
                    row["range_pct_5"]
                ),
                range_acceleration=(
                    row[
                        "range_acceleration"
                    ]
                ),
                range_percentile=(
                    range_percentile
                ),
                dollar_volume_percentile=(
                    dollar_percentile
                ),
                rvol_percentile=(
                    rvol_percentile
                ),
                volume_acceleration_percentile=(
                    volume_accel_percentile
                ),
                range_acceleration_percentile=(
                    range_accel_percentile
                ),
                v4_score=score,
            )
        )

    return results


def rank_webull_v4_model(
        statistics: Iterable[StockStats],
        *,
        daily_history: dict[
            str,
            list[dict],
        ],
        date_str: str,
        current_symbols: Iterable[str],
        rules: ScannerRules | None = None,
) -> tuple[
    list[ScannerModelSelection],
    dict[str, ScannerV4Factors],
]:
    """
    Rank eligible candidates under Webull V4.

    Production scanner behavior is not modified.
    """
    rows = list(statistics)

    scanner = StockScanner(
        current_symbols=list(
            current_symbols
        ),
        rules=rules,
    )

    current_set = set(
        scanner.current_symbols
    )

    eligible_symbols = [
        row.symbol
        for row in rows
        if (
            row.symbol not in current_set
            and scanner.is_eligible(row)
        )
    ]

    factors = build_v4_factor_scores(
        daily_history=daily_history,
        date_str=date_str,
        eligible_symbols=(
            eligible_symbols
        ),
    )

    factors_by_symbol = {
        row.symbol: row
        for row in factors
    }

    scored = sorted(
        factors,
        key=lambda row: (
            -row.v4_score,
            row.symbol,
        ),
    )

    rankings = [
        ScannerModelSelection(
            model=(
                "V4_RELATIVE_FACTOR"
            ),
            symbol=row.symbol,
            rank=rank,
            selected=(
                rank
                <= scanner.rules.candidate_limit
            ),
            score=row.v4_score,
        )
        for rank, row
        in enumerate(
            scored,
            start=1,
        )
    ]

    return (
        rankings,
        factors_by_symbol,
    )
