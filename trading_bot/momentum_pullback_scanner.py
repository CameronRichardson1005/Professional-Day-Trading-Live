from dataclasses import dataclass
from typing import Iterable


MOMENTUM_PULLBACK_STRATEGY_NAME = (
    "MOMENTUM_PULLBACK"
)


@dataclass(frozen=True)
class MomentumStockSnapshot:
    symbol: str

    price: float
    percent_gain: float
    relative_volume: float

    current_volume: float = 0.0
    average_volume_30d: float = 0.0

    # These remain nullable until we have historically
    # valid data sources for float and catalysts.
    float_shares: float | None = None
    catalyst: str | None = None

    @property
    def has_catalyst(self) -> bool:
        return bool(
            self.catalyst
            and self.catalyst.strip()
        )

    @property
    def ranking_score(self) -> float:
        # Source material emphasizes leading
        # percentage gainers as the obvious stocks.
        return self.percent_gain


@dataclass(frozen=True)
class MomentumScannerRules:
    minimum_price: float = 1.0
    maximum_price: float | None = 20.0

    minimum_percent_gain: float = 10.0
    minimum_relative_volume: float = 5.0

    maximum_float_shares: float = (
        20_000_000
    )

    candidate_limit: int = 3

    # False for market-data-only historical research.
    # These can become True once trustworthy historical
    # catalyst/float data is available.
    require_catalyst: bool = False
    require_float: bool = False


class MomentumPullbackScanner:
    def __init__(
        self,
        rules: MomentumScannerRules | None = None,
    ) -> None:
        self.rules = (
            rules
            or MomentumScannerRules()
        )

    def market_data_failures(
        self,
        snapshot: MomentumStockSnapshot,
    ) -> list[str]:
        failures = []
        rules = self.rules

        if snapshot.price < rules.minimum_price:
            failures.append(
                "PRICE BELOW MINIMUM"
            )

        if (
            rules.maximum_price is not None
            and snapshot.price
            > rules.maximum_price
        ):
            failures.append(
                "PRICE ABOVE MAXIMUM"
            )

        if (
            snapshot.percent_gain
            < rules.minimum_percent_gain
        ):
            failures.append(
                "GAIN BELOW MINIMUM"
            )

        if (
            snapshot.relative_volume
            < rules.minimum_relative_volume
        ):
            failures.append(
                "RELATIVE VOLUME BELOW MINIMUM"
            )

        return failures

    def five_pillar_failures(
        self,
        snapshot: MomentumStockSnapshot,
    ) -> list[str]:
        failures = self.market_data_failures(
            snapshot
        )

        if snapshot.float_shares is None:
            failures.append(
                "FLOAT UNCONFIRMED"
            )
        elif (
            snapshot.float_shares
            > self.rules.maximum_float_shares
        ):
            failures.append(
                "FLOAT ABOVE PREFERENCE"
            )

        if not snapshot.has_catalyst:
            failures.append(
                "CATALYST UNCONFIRMED"
            )

        return failures

    def eligibility_failures(
        self,
        snapshot: MomentumStockSnapshot,
    ) -> list[str]:
        failures = self.market_data_failures(
            snapshot
        )

        if self.rules.require_float:
            if snapshot.float_shares is None:
                failures.append(
                    "FLOAT UNCONFIRMED"
                )
            elif (
                snapshot.float_shares
                > self.rules.maximum_float_shares
            ):
                failures.append(
                    "FLOAT ABOVE PREFERENCE"
                )

        if (
            self.rules.require_catalyst
            and not snapshot.has_catalyst
        ):
            failures.append(
                "CATALYST UNCONFIRMED"
            )

        return failures

    def is_market_data_eligible(
        self,
        snapshot: MomentumStockSnapshot,
    ) -> bool:
        return not self.market_data_failures(
            snapshot
        )

    def is_five_pillar_qualified(
        self,
        snapshot: MomentumStockSnapshot,
    ) -> bool:
        return not self.five_pillar_failures(
            snapshot
        )

    def select_candidates(
        self,
        snapshots: Iterable[
            MomentumStockSnapshot
        ],
    ) -> list[MomentumStockSnapshot]:
        eligible = [
            snapshot
            for snapshot in snapshots
            if not self.eligibility_failures(
                snapshot
            )
        ]

        eligible.sort(
            key=lambda snapshot: (
                -snapshot.percent_gain,
                -snapshot.relative_volume,
                snapshot.symbol,
            )
        )

        return eligible[
            :self.rules.candidate_limit
        ]
