import math

from dataclasses import dataclass
from typing import Iterable, Sequence


@dataclass(frozen=True)
class StockStats:
    symbol: str
    valid_bars: int
    avg_volume: float
    avg_price: float
    avg_range: float
    avg_range_pct: float

    @property
    def ranking_score(self) -> float:
        """
        Rank eligible stocks by percentage movement while
        rewarding liquidity without allowing extremely large
        share volume to dominate the score.

        Long-history research from 2025-01-02 through
        2026-08-11 found this log-volume ranking materially
        more robust than the previous linear-volume ranking.
        """
        return (
            self.avg_range_pct
            * math.log1p(
                self.avg_volume / 500_000
            )
        )


@dataclass(frozen=True)
class OpeningReliability:
    symbol: str
    usable_days: int
    total_bars: int
    expected_bars: int

    @property
    def completeness(self) -> float:
        if self.expected_bars <= 0:
            return 0.0
        return self.total_bars / self.expected_bars


@dataclass(frozen=True)
class ScannerRules:
    minimum_valid_bars: int = 20
    minimum_price: float = 2.0
    maximum_price: float | None = None
    minimum_average_volume: float = 500_000
    minimum_average_range: float = 0.20
    minimum_average_range_pct: float = 4.0
    candidate_limit: int = 3
    minimum_reliability_days: int = 5
    minimum_opening_completeness: float = 0.90


class StockScanner:
    def __init__(
            self,
            current_symbols: Sequence[str],
            rules: ScannerRules | None = None,
    ) -> None:
        self.current_symbols = list(
            dict.fromkeys(current_symbols)
        )
        self.rules = rules or ScannerRules()

    def is_eligible(self, stats: StockStats) -> bool:
        return not self.eligibility_failures(stats)

    def eligibility_failures(
            self,
            stats: StockStats,
    ) -> list[str]:
        rules = self.rules
        failures = []

        if stats.valid_bars < rules.minimum_valid_bars:
            failures.append("INSUFFICIENT BARS")

        if stats.avg_price < rules.minimum_price:
            failures.append("PRICE BELOW MINIMUM")
        elif (
            rules.maximum_price is not None
            and stats.avg_price > rules.maximum_price
        ):
            failures.append("PRICE ABOVE MAXIMUM")

        if (
            stats.avg_volume
            < rules.minimum_average_volume
        ):
            failures.append("VOLUME BELOW MINIMUM")

        if stats.avg_range < rules.minimum_average_range:
            failures.append("RANGE BELOW MINIMUM")

        if (
            stats.avg_range_pct
            < rules.minimum_average_range_pct
        ):
            failures.append("RANGE % BELOW MINIMUM")

        return failures

    def select_candidates(
            self,
            statistics: Iterable[StockStats],
    ) -> list[StockStats]:
        current_set = set(self.current_symbols)

        eligible = [
            stats
            for stats in statistics
            if stats.symbol not in current_set
            and self.is_eligible(stats)
        ]

        eligible.sort(
            key=lambda stats: (
                -stats.ranking_score,
                stats.symbol,
            )
        )

        return eligible[
            :self.rules.candidate_limit
        ]

    def reliable_symbol_set(
            self,
            reliability: Iterable[OpeningReliability] | None,
    ) -> set[str] | None:
        if reliability is None:
            return None

        records = list(reliability)

        usable_records = [
            record
            for record in records
            if (
                record.usable_days
                >= self.rules.minimum_reliability_days
            )
        ]

        if not usable_records:
            return None

        return {
            record.symbol
            for record in usable_records
            if (
                record.completeness
                >= self.rules.minimum_opening_completeness
            )
        }

    def select_symbols(
            self,
            statistics: Iterable[StockStats],
            reliability: Iterable[OpeningReliability] | None = None,
    ) -> list[str]:
        selected_candidates = self.select_candidates(
            statistics
        )

        selected = self.current_symbols + [
            stats.symbol
            for stats in selected_candidates
        ]

        reliable_symbols = self.reliable_symbol_set(
            reliability
        )

        if reliable_symbols is None:
            return selected

        filtered = [
            symbol
            for symbol in selected
            if symbol in reliable_symbols
        ]

        # Fail safe: never return an empty universe because
        # reliability history may be temporarily incomplete.
        return filtered or selected
