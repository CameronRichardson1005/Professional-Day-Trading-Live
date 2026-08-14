from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable, Mapping

from .scanner import (
    OpeningReliability,
    StockScanner,
    StockStats,
)
from .scanner_realized_performance import (
    RealizedStrategyObservation,
)


HYPOTHESIS_FREEZE_DATE = date(
    2026,
    8,
    13,
)


FORWARD_FIELDNAMES = [
    "date",
    "rank",
    "symbol",
    "v1_score",
    "top2_challenger",
    "top3_baseline",
    "manipulation_signal",
    "filled",
    "outcome",
    "return_pct",
    "strict_outcome_clean",
]


@dataclass(frozen=True)
class ForwardValidationRow:
    date: str
    rank: int
    symbol: str
    v1_score: float

    top2_challenger: bool
    top3_baseline: bool

    manipulation_signal: str
    filled: bool | None
    outcome: str | None
    return_pct: float | None

    strict_outcome_clean: bool


@dataclass(frozen=True)
class ForwardSummary:
    max_rank: int
    strict: bool

    selections: int
    signals: int
    filled_trades: int

    total_return_pct: float
    expectancy_per_selection_pct: float
    expectancy_per_signal_pct: float
    expectancy_per_filled_trade_pct: (
        float | None
    )


@dataclass(frozen=True)
class ForwardComparison:
    top2: ForwardSummary
    top3: ForwardSummary

    expectancy_difference_pct: float


def _yes_no(
    value: bool | None,
) -> str:
    if value is None:
        return ""

    return (
        "YES"
        if value
        else "NO"
    )


def _parse_optional_bool(
    value: object,
) -> bool | None:
    text = str(
        value
    ).strip().upper()

    if not text:
        return None

    if text == "YES":
        return True

    if text == "NO":
        return False

    raise ValueError(
        f"Invalid boolean value: {value}"
    )


def _parse_optional_float(
    value: object,
) -> float | None:
    text = str(
        value
    ).strip()

    if not text:
        return None

    return float(
        text
    )


def build_forward_rows(
    *,
    session: date,
    scanner: StockScanner,
    statistics: Iterable[
        StockStats
    ],
    realized_by_symbol: Mapping[
        str,
        RealizedStrategyObservation,
    ],
    reliability: Iterable[
        OpeningReliability
    ] | None = None,
) -> list[ForwardValidationRow]:
    """
    Build frozen V1 Manipulation shadow observations.

    Important:
    - only dates AFTER 2026-08-13 are accepted;
    - ranking comes directly from the existing StockScanner;
    - production candidate_limit remains unchanged;
    - this function does not modify scanner rules;
    - this function does not route trades.
    """
    if (
        session
        <= HYPOTHESIS_FREEZE_DATE
    ):
        raise ValueError(
            "Forward validation requires "
            "a trading date after "
            "2026-08-13."
        )

    statistics = list(
        statistics
    )

    ranked_candidates = (
        scanner.select_candidates(
            statistics
        )
    )

    # Preserve the production reliability filter when one is
    # supplied. Rank numbers remain their original V1 ranks so
    # the challenger definition cannot drift.
    if reliability is not None:
        production_symbols = set(
            scanner.select_symbols(
                statistics,
                reliability=(
                    reliability
                ),
            )
        )

        ranked_candidates = [
            stats
            for stats in ranked_candidates
            if (
                stats.symbol
                in production_symbols
            )
        ]

    rows = []

    for rank, stats in enumerate(
        scanner.select_candidates(
            statistics
        ),
        start=1,
    ):
        if stats not in ranked_candidates:
            continue

        symbol = stats.symbol

        observation = (
            realized_by_symbol.get(
                symbol
            )
        )

        if observation is None:
            raise ValueError(
                "Missing realized "
                "Manipulation observation "
                f"for {session.isoformat()} "
                f"{symbol}."
            )

        if (
            observation.date
            != session.isoformat()
        ):
            raise ValueError(
                "Realized observation date "
                f"mismatch for {symbol}: "
                f"{observation.date}."
            )

        if (
            observation.symbol
            != symbol
        ):
            raise ValueError(
                "Realized observation symbol "
                f"mismatch for {symbol}: "
                f"{observation.symbol}."
            )

        rows.append(
            ForwardValidationRow(
                date=(
                    session.isoformat()
                ),
                rank=rank,
                symbol=symbol,
                v1_score=(
                    stats.ranking_score
                ),
                top2_challenger=(
                    rank <= 2
                ),
                top3_baseline=True,
                manipulation_signal=(
                    observation
                    .manipulation_signal
                ),
                filled=(
                    observation
                    .manipulation_filled
                ),
                outcome=(
                    observation
                    .manipulation_outcome
                ),
                return_pct=(
                    observation
                    .manipulation_return_pct
                ),
                strict_outcome_clean=(
                    observation
                    .post_opening_outcome_clean
                ),
            )
        )

    return rows


def row_to_dict(
    row: ForwardValidationRow,
) -> dict[str, object]:
    return {
        "date": row.date,
        "rank": row.rank,
        "symbol": row.symbol,
        "v1_score": row.v1_score,
        "top2_challenger": (
            _yes_no(
                row.top2_challenger
            )
        ),
        "top3_baseline": (
            _yes_no(
                row.top3_baseline
            )
        ),
        "manipulation_signal": (
            row.manipulation_signal
        ),
        "filled": (
            _yes_no(
                row.filled
            )
        ),
        "outcome": (
            row.outcome
            or ""
        ),
        "return_pct": (
            row.return_pct
            if row.return_pct
            is not None
            else ""
        ),
        "strict_outcome_clean": (
            _yes_no(
                row.strict_outcome_clean
            )
        ),
    }


def dict_to_row(
    raw: dict[str, str],
) -> ForwardValidationRow:
    return ForwardValidationRow(
        date=raw["date"],
        rank=int(
            raw["rank"]
        ),
        symbol=raw["symbol"],
        v1_score=float(
            raw["v1_score"]
        ),
        top2_challenger=bool(
            _parse_optional_bool(
                raw[
                    "top2_challenger"
                ]
            )
        ),
        top3_baseline=bool(
            _parse_optional_bool(
                raw[
                    "top3_baseline"
                ]
            )
        ),
        manipulation_signal=(
            raw[
                "manipulation_signal"
            ]
        ),
        filled=(
            _parse_optional_bool(
                raw["filled"]
            )
        ),
        outcome=(
            raw["outcome"]
            or None
        ),
        return_pct=(
            _parse_optional_float(
                raw["return_pct"]
            )
        ),
        strict_outcome_clean=bool(
            _parse_optional_bool(
                raw[
                    "strict_outcome_clean"
                ]
            )
        ),
    )


def load_forward_rows(
    path: Path,
) -> list[ForwardValidationRow]:
    if not path.exists():
        return []

    with path.open(
        newline="",
        encoding="utf-8",
    ) as handle:
        reader = csv.DictReader(
            handle
        )

        return [
            dict_to_row(
                row
            )
            for row in reader
        ]


def write_forward_rows(
    *,
    path: Path,
    rows: Iterable[
        ForwardValidationRow
    ],
) -> None:
    """
    Idempotently persist the forward ledger.

    Re-running an identical day is safe.
    A conflicting attempt to rewrite an existing
    date/rank/symbol observation raises instead of silently
    changing frozen forward evidence.
    """
    incoming = list(
        rows
    )

    for row in incoming:
        row_date = (
            date.fromisoformat(
                row.date
            )
        )

        if (
            row_date
            <= HYPOTHESIS_FREEZE_DATE
        ):
            raise ValueError(
                "Forward ledger cannot "
                "contain observations on "
                "or before 2026-08-13."
            )

    existing = (
        load_forward_rows(
            path
        )
    )

    by_key = {
        (
            row.date,
            row.rank,
            row.symbol,
        ): row
        for row in existing
    }

    for row in incoming:
        key = (
            row.date,
            row.rank,
            row.symbol,
        )

        previous = (
            by_key.get(
                key
            )
        )

        if (
            previous is not None
            and previous != row
        ):
            raise ValueError(
                "Refusing to rewrite "
                "existing frozen forward "
                "observation: "
                f"{key}."
            )

        by_key[
            key
        ] = row

    combined = sorted(
        by_key.values(),
        key=lambda row: (
            row.date,
            row.rank,
            row.symbol,
        ),
    )

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary = (
        path.with_suffix(
            path.suffix + ".tmp"
        )
    )

    with temporary.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=(
                FORWARD_FIELDNAMES
            ),
        )

        writer.writeheader()

        writer.writerows(
            row_to_dict(
                row
            )
            for row in combined
        )

    temporary.replace(
        path
    )


def summarize_forward(
    *,
    rows: Iterable[
        ForwardValidationRow
    ],
    max_rank: int,
    strict: bool = False,
) -> ForwardSummary:
    if max_rank not in {
        1,
        2,
        3,
    }:
        raise ValueError(
            "max_rank must be "
            "1, 2, or 3."
        )

    sample = [
        row
        for row in rows
        if (
            row.rank <= max_rank
            and (
                not strict
                or row.strict_outcome_clean
            )
        )
    ]

    signals = [
        row
        for row in sample
        if (
            row.manipulation_signal
            == "INVEST"
        )
    ]

    filled = [
        row
        for row in signals
        if row.filled is True
    ]

    returns = [
        (
            row.return_pct
            if row.return_pct
            is not None
            else 0.0
        )
        for row in sample
    ]

    total_return = sum(
        returns
    )

    selections = len(
        sample
    )

    signal_count = len(
        signals
    )

    filled_count = len(
        filled
    )

    return ForwardSummary(
        max_rank=max_rank,
        strict=strict,
        selections=selections,
        signals=signal_count,
        filled_trades=filled_count,
        total_return_pct=(
            total_return
        ),
        expectancy_per_selection_pct=(
            total_return
            / selections
            if selections
            else 0.0
        ),
        expectancy_per_signal_pct=(
            total_return
            / signal_count
            if signal_count
            else 0.0
        ),
        expectancy_per_filled_trade_pct=(
            total_return
            / filled_count
            if filled_count
            else None
        ),
    )


def compare_top2_top3(
    *,
    rows: Iterable[
        ForwardValidationRow
    ],
    strict: bool = False,
) -> ForwardComparison:
    rows = list(
        rows
    )

    top2 = summarize_forward(
        rows=rows,
        max_rank=2,
        strict=strict,
    )

    top3 = summarize_forward(
        rows=rows,
        max_rank=3,
        strict=strict,
    )

    return ForwardComparison(
        top2=top2,
        top3=top3,
        expectancy_difference_pct=(
            top2
            .expectancy_per_selection_pct
            -
            top3
            .expectancy_per_selection_pct
        ),
    )
