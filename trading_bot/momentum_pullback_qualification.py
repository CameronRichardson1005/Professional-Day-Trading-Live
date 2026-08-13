from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from .momentum_pullback_catalyst_classifier import (
    CatalystAssessment,
    assess_symbol_catalysts,
)
from .momentum_pullback_scanner import (
    MomentumPullbackScanner,
    MomentumStockSnapshot,
)
from .webull_momentum_discovery import (
    WebullMomentumCandidate,
)


class MomentumQualificationStatus(
    str,
    Enum,
):
    REJECTED_MARKET_DATA = (
        "rejected_market_data"
    )

    CATALYST_UNCONFIRMED = (
        "catalyst_unconfirmed"
    )

    QUALIFIED_EXCEPT_FLOAT = (
        "qualified_except_float"
    )


@dataclass(frozen=True)
class MomentumQualification:
    candidate: WebullMomentumCandidate
    snapshot: MomentumStockSnapshot
    catalyst_assessment: CatalystAssessment
    status: MomentumQualificationStatus
    failures: tuple[str, ...]

    @property
    def symbol(self) -> str:
        return self.candidate.symbol

    @property
    def provisionally_qualified(
        self,
    ) -> bool:
        return (
            self.status
            == MomentumQualificationStatus
            .QUALIFIED_EXCEPT_FLOAT
        )


@dataclass(frozen=True)
class MomentumQualificationRun:
    results: tuple[
        MomentumQualification,
        ...
    ]

    selected_symbols: tuple[
        str,
        ...
    ]

    @property
    def discovered_count(
        self,
    ) -> int:
        return len(
            self.results
        )


class MomentumPullbackQualificationService:
    """
    Research-only Momentum Pullback qualification.

    Flow:

        Webull whole-market discovery
        -> Alpaca/Benzinga catalyst evidence
        -> deterministic catalyst classification
        -> provisional candidate ranking

    Float remains explicitly unconfirmed.

    This service does not place, preview,
    modify, or submit orders.
    """

    def __init__(
        self,
        *,
        discovery,
        catalyst_client,
        scanner: (
            MomentumPullbackScanner
            | None
        ) = None,
    ) -> None:
        self.discovery = discovery
        self.catalyst_client = (
            catalyst_client
        )

        self.scanner = (
            scanner
            or MomentumPullbackScanner()
        )

    def qualify(
        self,
        *,
        catalyst_start: datetime,
        catalyst_end: (
            datetime
            | None
        ) = None,
        news_limit: int = 50,
    ) -> MomentumQualificationRun:
        candidates = list(
            self.discovery.discover()
        )

        if not candidates:
            return (
                MomentumQualificationRun(
                    results=(),
                    selected_symbols=(),
                )
            )

        symbols = tuple(
            candidate.symbol
            for candidate in candidates
        )

        articles_by_symbol = (
            self.catalyst_client
            .get_articles_by_symbol(
                symbols=symbols,
                start=catalyst_start,
                end=catalyst_end,
                limit=news_limit,
            )
        )

        results = []

        for candidate in candidates:
            articles = (
                articles_by_symbol.get(
                    candidate.symbol,
                    [],
                )
            )

            assessment = (
                assess_symbol_catalysts(
                    symbol=(
                        candidate.symbol
                    ),
                    articles=articles,
                )
            )

            catalyst_text = None

            if assessment.catalysts:
                catalyst_text = (
                    assessment
                    .catalysts[0]
                    .headline
                )

            snapshot = (
                MomentumStockSnapshot(
                    symbol=(
                        candidate.symbol
                    ),
                    price=(
                        candidate.price
                    ),
                    percent_gain=(
                        candidate
                        .percent_gain
                    ),
                    relative_volume=(
                        candidate
                        .relative_volume_10d
                    ),
                    current_volume=(
                        candidate.volume
                    ),
                    average_volume_30d=0.0,
                    float_shares=None,
                    catalyst=(
                        catalyst_text
                    ),
                )
            )

            market_failures = (
                self.scanner
                .market_data_failures(
                    snapshot
                )
            )

            if market_failures:
                status = (
                    MomentumQualificationStatus
                    .REJECTED_MARKET_DATA
                )

                failures = tuple(
                    market_failures
                )

            elif not assessment.positive:
                status = (
                    MomentumQualificationStatus
                    .CATALYST_UNCONFIRMED
                )

                failures = (
                    "CATALYST UNCONFIRMED",
                    "FLOAT UNCONFIRMED",
                )

            else:
                status = (
                    MomentumQualificationStatus
                    .QUALIFIED_EXCEPT_FLOAT
                )

                failures = (
                    "FLOAT UNCONFIRMED",
                )

            results.append(
                MomentumQualification(
                    candidate=candidate,
                    snapshot=snapshot,
                    catalyst_assessment=(
                        assessment
                    ),
                    status=status,
                    failures=failures,
                )
            )

        results.sort(
            key=lambda result: (
                -result.candidate
                .percent_gain,
                -result.candidate
                .relative_volume_10d,
                result.symbol,
            )
        )

        provisional = [
            result
            for result in results
            if result.provisionally_qualified
        ]

        selected_symbols = tuple(
            result.symbol
            for result in provisional[
                :self.scanner.rules
                .candidate_limit
            ]
        )

        return MomentumQualificationRun(
            results=tuple(
                results
            ),
            selected_symbols=(
                selected_symbols
            ),
        )
