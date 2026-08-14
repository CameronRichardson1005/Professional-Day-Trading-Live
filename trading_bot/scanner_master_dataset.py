from __future__ import annotations

import csv
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .manipulation_selling_pressure_dataset import (
    build_atr_by_date,
)
from .scanner_realized_performance import (
    evaluate_realized_strategy_observation,
)


EASTERN = ZoneInfo("America/New_York")


SCANNER_MODELS = (
    "V1_LOG_VOLUME",
    "V2_LOG_DOLLAR_VOLUME",
    "V3_Z_FACTOR",
    "V4_RELATIVE_FACTOR",
)

MODEL_PREFIX = {
    "V1_LOG_VOLUME": "v1",
    "V2_LOG_DOLLAR_VOLUME": "v2",
    "V3_Z_FACTOR": "v3",
    "V4_RELATIVE_FACTOR": "v4",
}


@dataclass(frozen=True)
class ScannerResearchPoint:
    model: str
    rank: int
    selected: bool
    score: float


MASTER_FIELDNAMES = [
    "date",
    "symbol",
    "evaluation_status",

    "v1_rank",
    "v1_score",
    "v1_selected",

    "v2_rank",
    "v2_score",
    "v2_selected",

    "v3_rank",
    "v3_score",
    "v3_selected",

    "v4_rank",
    "v4_score",
    "v4_selected",

    "atr_14",

    "opening_open",
    "opening_high",
    "opening_low",
    "opening_close",

    "minute_bars",
    "missing_minutes",
    "missing_opening_minutes",
    "missing_quick_flip_minutes",
    "missing_post_1100_minutes",

    "quick_flip_signal_clean",
    "post_opening_outcome_clean",

    "manipulation_signal",
    "manipulation_entry",
    "manipulation_target",
    "manipulation_trading_stop",
    "manipulation_filled",
    "manipulation_outcome",
    "manipulation_return_pct",

    "quick_flip_status",
    "quick_flip_signal",
    "quick_flip_pattern",
    "quick_flip_entry",
    "quick_flip_tp1",
    "quick_flip_tp2",
    "quick_flip_reversal_time",
    "quick_flip_confirmation_time",
    "quick_flip_filled",
    "quick_flip_fill_time",
    "quick_flip_tp1_hit",
    "quick_flip_tp2_hit",
    "quick_flip_mfe_pct",
    "quick_flip_mae_pct",
    "quick_flip_endpoint_price",
    "quick_flip_endpoint_return_pct",
]


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


def _opening_date_et(
    bar: dict,
) -> str:
    text = str(
        bar["t"]
    ).strip()

    if text.endswith("Z"):
        text = (
            text[:-1]
            + "+00:00"
        )

    return (
        datetime
        .fromisoformat(text)
        .astimezone(EASTERN)
        .date()
        .isoformat()
    )


def load_webull_scanner_index(
    path: Path,
) -> dict[
    tuple[str, str],
    dict[str, ScannerResearchPoint],
]:
    """
    Load only Webull scanner research rows.

    The scanner CSV contains one row per eligible
    date/model/symbol. Missing model rows therefore mean the
    symbol was not ranked as an eligible candidate by that model's
    shared eligibility universe.
    """
    result: dict[
        tuple[str, str],
        dict[str, ScannerResearchPoint],
    ] = {}

    with path.open(
        newline="",
        encoding="utf-8",
    ) as handle:
        reader = csv.DictReader(
            handle
        )

        for row in reader:
            if (
                row.get("source")
                != "WEBULL"
            ):
                continue

            model = str(
                row.get(
                    "model",
                    "",
                )
            )

            if model not in SCANNER_MODELS:
                continue

            date_str = str(
                row["date"]
            )

            symbol = str(
                row["symbol"]
            ).upper()

            key = (
                date_str,
                symbol,
            )

            model_rows = (
                result.setdefault(
                    key,
                    {},
                )
            )

            if model in model_rows:
                raise ValueError(
                    "Duplicate scanner research "
                    f"row for {date_str} "
                    f"{symbol} {model}."
                )

            model_rows[
                model
            ] = ScannerResearchPoint(
                model=model,
                rank=int(
                    row["rank"]
                ),
                selected=(
                    str(
                        row["selected"]
                    ).upper()
                    == "YES"
                ),
                score=float(
                    row["score"]
                ),
            )

    return result


def index_opening_history(
    opening_history: dict[
        str,
        list[dict],
    ],
) -> dict[
    tuple[str, str],
    dict,
]:
    result = {}

    for symbol, bars in (
        opening_history.items()
    ):
        normalized_symbol = (
            symbol.upper()
        )

        for bar in bars:
            date_str = (
                _opening_date_et(
                    bar
                )
            )

            key = (
                date_str,
                normalized_symbol,
            )

            if key in result:
                raise ValueError(
                    "Duplicate native opening "
                    f"bar for {date_str} "
                    f"{normalized_symbol}."
                )

            result[key] = bar

    return result


def build_atr_history(
    *,
    daily_history: dict[
        str,
        list[dict],
    ],
    trading_dates: list[date],
    symbols: list[str],
) -> dict[
    str,
    dict[str, float],
]:
    test_dates = [
        trading_day.isoformat()
        for trading_day
        in trading_dates
    ]

    return {
        symbol.upper(): (
            build_atr_by_date(
                daily_bars=(
                    daily_history.get(
                        symbol,
                        daily_history.get(
                            symbol.upper(),
                            [],
                        ),
                    )
                ),
                test_dates=test_dates,
                period=14,
            )
        )
        for symbol in symbols
    }


def _scanner_fields(
    *,
    date_str: str,
    symbol: str,
    scanner_index: dict[
        tuple[str, str],
        dict[
            str,
            ScannerResearchPoint,
        ],
    ],
) -> dict[str, object]:
    result: dict[
        str,
        object,
    ] = {}

    model_rows = (
        scanner_index.get(
            (
                date_str,
                symbol,
            ),
            {},
        )
    )

    for model in SCANNER_MODELS:
        prefix = MODEL_PREFIX[
            model
        ]

        point = model_rows.get(
            model
        )

        result[
            f"{prefix}_rank"
        ] = (
            point.rank
            if point is not None
            else ""
        )

        result[
            f"{prefix}_score"
        ] = (
            point.score
            if point is not None
            else ""
        )

        result[
            f"{prefix}_selected"
        ] = (
            _yes_no(
                point.selected
            )
            if point is not None
            else ""
        )

    return result


def _blank_realized_fields() -> dict[
    str,
    object,
]:
    return {
        field: ""
        for field in MASTER_FIELDNAMES
        if field not in {
            "date",
            "symbol",
            "evaluation_status",
            "v1_rank",
            "v1_score",
            "v1_selected",
            "v2_rank",
            "v2_score",
            "v2_selected",
            "v3_rank",
            "v3_score",
            "v3_selected",
            "v4_rank",
            "v4_score",
            "v4_selected",
        }
    }


def build_master_rows(
    *,
    trading_dates: list[date],
    symbols: list[str],
    scanner_index: dict[
        tuple[str, str],
        dict[
            str,
            ScannerResearchPoint,
        ],
    ],
    opening_history: dict[
        str,
        list[dict],
    ],
    atr_history: dict[
        str,
        dict[str, float],
    ],
    minute_loader: Callable[
        [str, str],
        list[dict] | None,
    ],
) -> list[dict[str, object]]:
    """
    Build one deterministic row for every date × research symbol.

    Scanner models share the same realized strategy observation.
    This prevents execution assumptions from drifting between
    V1/V2/V3/V4 comparisons.
    """
    opening_index = (
        index_opening_history(
            opening_history
        )
    )

    rows = []

    for trading_day in sorted(
        trading_dates
    ):
        date_str = (
            trading_day.isoformat()
        )

        for raw_symbol in sorted(
            symbols
        ):
            symbol = (
                raw_symbol.upper()
            )

            row: dict[
                str,
                object,
            ] = {
                "date": date_str,
                "symbol": symbol,
                "evaluation_status": "",
            }

            row.update(
                _scanner_fields(
                    date_str=date_str,
                    symbol=symbol,
                    scanner_index=(
                        scanner_index
                    ),
                )
            )

            row.update(
                _blank_realized_fields()
            )

            opening_bar = (
                opening_index.get(
                    (
                        date_str,
                        symbol,
                    )
                )
            )

            if opening_bar is None:
                row[
                    "evaluation_status"
                ] = "MISSING_OPENING_BAR"

                rows.append(
                    row
                )

                continue

            atr = (
                atr_history
                .get(
                    symbol,
                    {},
                )
                .get(
                    date_str
                )
            )

            if atr is None:
                row[
                    "evaluation_status"
                ] = "MISSING_ATR"

                rows.append(
                    row
                )

                continue

            minute_bars = (
                minute_loader(
                    symbol,
                    date_str,
                )
            )

            if minute_bars is None:
                row[
                    "evaluation_status"
                ] = "MISSING_MINUTE_CACHE"

                rows.append(
                    row
                )

                continue

            observation = (
                evaluate_realized_strategy_observation(
                    session=trading_day,
                    symbol=symbol,
                    opening_bar=opening_bar,
                    atr_14=float(
                        atr
                    ),
                    minute_bars=minute_bars,
                )
            )

            row.update({
                "evaluation_status": "OK",

                "atr_14": observation.atr_14,

                "opening_open": (
                    observation.opening_open
                ),
                "opening_high": (
                    observation.opening_high
                ),
                "opening_low": (
                    observation.opening_low
                ),
                "opening_close": (
                    observation.opening_close
                ),

                "minute_bars": (
                    observation.minute_bars
                ),
                "missing_minutes": (
                    observation.missing_minutes
                ),
                "missing_opening_minutes": (
                    observation
                    .missing_opening_minutes
                ),
                "missing_quick_flip_minutes": (
                    observation
                    .missing_quick_flip_minutes
                ),
                "missing_post_1100_minutes": (
                    observation
                    .missing_post_1100_minutes
                ),

                "quick_flip_signal_clean": (
                    _yes_no(
                        observation
                        .quick_flip_signal_clean
                    )
                ),
                "post_opening_outcome_clean": (
                    _yes_no(
                        observation
                        .post_opening_outcome_clean
                    )
                ),

                "manipulation_signal": (
                    observation
                    .manipulation_signal
                ),
                "manipulation_entry": (
                    observation
                    .manipulation_entry
                    if observation
                    .manipulation_entry
                    is not None
                    else ""
                ),
                "manipulation_target": (
                    observation
                    .manipulation_target
                    if observation
                    .manipulation_target
                    is not None
                    else ""
                ),
                "manipulation_trading_stop": (
                    observation
                    .manipulation_trading_stop
                    if observation
                    .manipulation_trading_stop
                    is not None
                    else ""
                ),
                "manipulation_filled": (
                    _yes_no(
                        observation
                        .manipulation_filled
                    )
                ),
                "manipulation_outcome": (
                    observation
                    .manipulation_outcome
                    or ""
                ),
                "manipulation_return_pct": (
                    observation
                    .manipulation_return_pct
                    if observation
                    .manipulation_return_pct
                    is not None
                    else ""
                ),

                "quick_flip_status": (
                    observation
                    .quick_flip_status
                ),
                "quick_flip_signal": (
                    observation
                    .quick_flip_signal
                ),
                "quick_flip_pattern": (
                    observation
                    .quick_flip_pattern
                    or ""
                ),
                "quick_flip_entry": (
                    observation
                    .quick_flip_entry
                    if observation
                    .quick_flip_entry
                    is not None
                    else ""
                ),
                "quick_flip_tp1": (
                    observation
                    .quick_flip_tp1
                    if observation
                    .quick_flip_tp1
                    is not None
                    else ""
                ),
                "quick_flip_tp2": (
                    observation
                    .quick_flip_tp2
                    if observation
                    .quick_flip_tp2
                    is not None
                    else ""
                ),
                "quick_flip_reversal_time": (
                    observation
                    .quick_flip_reversal_time
                    .isoformat()
                    if observation
                    .quick_flip_reversal_time
                    is not None
                    else ""
                ),
                "quick_flip_confirmation_time": (
                    observation
                    .quick_flip_confirmation_time
                    .isoformat()
                    if observation
                    .quick_flip_confirmation_time
                    is not None
                    else ""
                ),
                "quick_flip_filled": (
                    _yes_no(
                        observation
                        .quick_flip_filled
                    )
                ),
                "quick_flip_fill_time": (
                    observation
                    .quick_flip_fill_time
                    .isoformat()
                    if observation
                    .quick_flip_fill_time
                    is not None
                    else ""
                ),
                "quick_flip_tp1_hit": (
                    _yes_no(
                        observation
                        .quick_flip_tp1_hit
                    )
                ),
                "quick_flip_tp2_hit": (
                    _yes_no(
                        observation
                        .quick_flip_tp2_hit
                    )
                ),
                "quick_flip_mfe_pct": (
                    observation
                    .quick_flip_mfe_pct
                    if observation
                    .quick_flip_mfe_pct
                    is not None
                    else ""
                ),
                "quick_flip_mae_pct": (
                    observation
                    .quick_flip_mae_pct
                    if observation
                    .quick_flip_mae_pct
                    is not None
                    else ""
                ),
                "quick_flip_endpoint_price": (
                    observation
                    .quick_flip_endpoint_price
                    if observation
                    .quick_flip_endpoint_price
                    is not None
                    else ""
                ),
                "quick_flip_endpoint_return_pct": (
                    observation
                    .quick_flip_endpoint_return_pct
                    if observation
                    .quick_flip_endpoint_return_pct
                    is not None
                    else ""
                ),
            })

            rows.append(
                row
            )

    return rows


def write_master_csv(
    *,
    rows: list[
        dict[str, object]
    ],
    output_path: Path,
) -> None:
    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with output_path.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=(
                MASTER_FIELDNAMES
            ),
        )

        writer.writeheader()

        writer.writerows(
            rows
        )
