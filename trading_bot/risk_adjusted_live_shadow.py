from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from .risk_adjusted_allocator import (
    RiskAdjustedOpportunity,
)
from .risk_adjusted_dominance_shadow import (
    build_dominance_equal_weight_plan,
    dominance_equal_plan_to_dict,
)
from .risk_adjusted_shadow_report import (
    StrategyPerformanceContext,
    build_daily_shadow_allocation_report,
    build_strategy_performance_context,
    fractional_quantity_for_shadow_allocation,
    shadow_report_to_dict,
)
from .risk_adjusted_strategy_adapters import (
    build_manipulation_opportunity,
    build_quick_flip_opportunity,
)
from .scanner_performance_summary import (
    load_master_rows,
)


_REALIZED_MASTER_PATTERN = re.compile(
    r"^scanner_realized_master_"
    r"(?P<start>\d{4}-\d{2}-\d{2})"
    r"_to_"
    r"(?P<end>\d{4}-\d{2}-\d{2})"
    r"\.csv$"
)


@dataclass(frozen=True)
class LiveShadowHistory:
    source_path: Path
    source_start_date: str
    source_end_date: str
    performance: StrategyPerformanceContext


def _date_text(
    value: date | str,
) -> str:
    if isinstance(value, date):
        return value.isoformat()

    return date.fromisoformat(
        str(value).strip()
    ).isoformat()


def find_latest_realized_master_before(
    *,
    trading_date: date | str,
    research_dir: Path | str = (
        "runtime/research"
    ),
) -> Path | None:
    """
    Select the newest realized-master dataset whose declared end
    date is strictly before the live trading date.

    This prevents current-day or future outcomes from entering
    the V2 live shadow score.
    """
    cutoff = date.fromisoformat(
        _date_text(trading_date)
    )

    directory = Path(
        research_dir
    )

    if not directory.exists():
        return None

    candidates: list[
        tuple[
            date,
            date,
            Path,
        ]
    ] = []

    for path in directory.glob(
        "scanner_realized_master_*.csv"
    ):
        match = (
            _REALIZED_MASTER_PATTERN.match(
                path.name
            )
        )

        if match is None:
            continue

        try:
            start_date = (
                date.fromisoformat(
                    match.group("start")
                )
            )

            end_date = (
                date.fromisoformat(
                    match.group("end")
                )
            )
        except ValueError:
            continue

        if end_date >= cutoff:
            continue

        candidates.append(
            (
                end_date,
                start_date,
                path,
            )
        )

    if not candidates:
        return None

    latest_end_date = max(
        item[0]
        for item in candidates
    )

    latest_candidates = [
        item
        for item in candidates
        if item[0] == latest_end_date
    ]

    # Multiple research artifacts can legitimately end on the
    # same trading date (for example, a one-day diagnostic and
    # the full historical master). Production scoring must use
    # the longest available causal history, so prefer the
    # earliest start date for the latest valid end date.
    latest_candidates.sort(
        key=lambda item: (
            item[1],
            str(item[2]),
        )
    )

    return latest_candidates[0][2]


def load_live_shadow_history(
    *,
    trading_date: date | str,
    research_dir: Path | str = (
        "runtime/research"
    ),
    model: str = "v1",
    strict: bool = True,
) -> LiveShadowHistory:
    """
    Load the newest valid no-lookahead realized-master history.

    The default v1 model refers to the historical
    V1 scanner research/control baseline.
    """
    source_path = (
        find_latest_realized_master_before(
            trading_date=trading_date,
            research_dir=research_dir,
        )
    )

    if source_path is None:
        raise FileNotFoundError(
            "No realized scanner master dataset ends "
            "before the requested trading date."
        )

    match = _REALIZED_MASTER_PATTERN.match(
        source_path.name
    )

    if match is None:
        raise ValueError(
            "Realized master filename does not contain "
            "a valid research date range."
        )

    rows = load_master_rows(
        source_path
    )

    performance = (
        build_strategy_performance_context(
            rows=rows,
            model=model,
            trading_date=trading_date,
            strict=strict,
        )
    )

    return LiveShadowHistory(
        source_path=source_path,
        source_start_date=(
            match.group("start")
        ),
        source_end_date=(
            match.group("end")
        ),
        performance=performance,
    )


def _preview_daily_pool(
    preview: Any,
) -> float | None:
    if not isinstance(
        preview,
        dict,
    ):
        return None

    deployable = preview.get(
        "deployableCapitalPool"
    )

    reserved = preview.get(
        "reservedCapitalBeforeBatch"
    )

    if deployable is None:
        return None

    try:
        deployable_value = float(
            deployable
        )
        reserved_value = float(
            reserved or 0.0
        )
    except (
        TypeError,
        ValueError,
    ):
        return None

    return round(
        max(
            0.0,
            deployable_value
            + reserved_value,
        ),
        2,
    )


def derive_original_daily_pool(
    *,
    stocks: dict,
    quick_flip_previews: list[dict],
) -> float | None:
    """
    Recover the original daily preview pool.

    Manipulation runs before Quick Flip, so prefer its first
    available preview metadata. If there was no Manipulation
    preview, fall back to the first Quick Flip preview.

    deployableCapitalPool is AFTER prior reservations, while
    reservedCapitalBeforeBatch contains those prior reservations.
    Their sum reconstructs the original pool for that batch.
    """
    for stock in stocks.values():
        pool = _preview_daily_pool(
            getattr(
                stock,
                "webull_preview",
                None,
            )
        )

        if pool is not None:
            return pool

    for preview in quick_flip_previews:
        pool = _preview_daily_pool(
            preview
        )

        if pool is not None:
            return pool

    return None


def current_production_allocations(
    *,
    stocks: dict,
    quick_flip_previews: list[dict],
) -> dict[
    tuple[str, str],
    float,
]:
    """
    Return actual current preview recommendations by strategy and
    symbol.

    This reads preview metadata only. It does not modify sizing.
    """
    allocations: dict[
        tuple[str, str],
        float,
    ] = {}

    for stock in stocks.values():
        preview = getattr(
            stock,
            "webull_preview",
            None,
        )

        if (
            not isinstance(
                preview,
                dict,
            )
            or preview.get("status")
            != "PREVIEW READY"
        ):
            continue

        value = preview.get(
            "recommendedAllocation"
        )

        if value is None:
            continue

        key = (
            "MANIPULATION",
            str(
                stock.symbol
            ).upper(),
        )

        allocations[key] = round(
            float(value),
            2,
        )

    for preview in quick_flip_previews:
        if (
            not isinstance(
                preview,
                dict,
            )
            or preview.get("status")
            != "PREVIEW READY"
        ):
            continue

        symbol = str(
            preview.get(
                "symbol",
                "",
            )
        ).upper()

        value = preview.get(
            "recommendedAllocation"
        )

        if not symbol or value is None:
            continue

        key = (
            "QUICK_FLIP",
            symbol,
        )

        allocations[key] = round(
            allocations.get(
                key,
                0.0,
            )
            + float(value),
            2,
        )

    return allocations


def build_live_opportunities(
    *,
    stocks: dict,
    quick_flip_results: dict,
    performance: StrategyPerformanceContext,
) -> list[
    RiskAdjustedOpportunity
]:
    """
    Convert today's live strategy state into V2 shadow
    opportunities.

    Quick Flip remains stop-loss free. Its downside ranking input
    comes from historical 75th-percentile absolute MAE in the
    supplied performance context.
    """
    opportunities: list[
        RiskAdjustedOpportunity
    ] = []

    for stock in stocks.values():
        if getattr(
            stock,
            "signal",
            None,
        ) != "INVEST":
            continue

        opportunities.append(
            build_manipulation_opportunity(
                stock,
                performance=(
                    performance.manipulation
                ),
            )
        )

    for symbol, result in (
        quick_flip_results.items()
    ):
        if result is None:
            continue

        signal = getattr(
            result,
            "signal",
            None,
        )

        if (
            signal is None
            or getattr(
                signal,
                "signal",
                None,
            )
            != "INVEST"
        ):
            continue

        opportunities.append(
            build_quick_flip_opportunity(
                signal,
                performance=(
                    performance.quick_flip
                ),
            )
        )

    return opportunities


def _quick_flip_preview_opportunity(
    *,
    preview: dict,
    performance: Any,
) -> RiskAdjustedOpportunity | None:
    """
    Reconstruct a Quick Flip opportunity from a stored preview.

    This allows the end-of-monitor report to retain an earlier
    PREVIEW READY setup even if self.quick_flip_results has since
    moved to a different non-INVEST state.
    """
    if (
        preview.get("status")
        != "PREVIEW READY"
    ):
        return None

    symbol = str(
        preview.get(
            "symbol",
            "",
        )
    ).upper()

    entry = preview.get(
        "limitBuy"
    )
    tp1 = preview.get(
        "takeProfit1"
    )
    tp2 = preview.get(
        "takeProfit2"
    )

    if (
        not symbol
        or entry is None
        or tp1 is None
        or tp2 is None
    ):
        return None

    proxy = SimpleNamespace(
        symbol=symbol,
        signal="INVEST",
        entry_price=float(entry),
        take_profit_1=float(tp1),
        take_profit_2=float(tp2),
    )

    return build_quick_flip_opportunity(
        proxy,
        performance=performance,
    )


def add_previewed_quick_flip_opportunities(
    *,
    opportunities: list[
        RiskAdjustedOpportunity
    ],
    quick_flip_previews: list[dict],
    performance: StrategyPerformanceContext,
) -> list[
    RiskAdjustedOpportunity
]:
    """
    Add any PREVIEW READY Quick Flip setup not already represented
    by today's current Quick Flip result.

    Strategy + symbol is the first live-shadow identity.
    """
    result = list(
        opportunities
    )

    existing = {
        (
            item.strategy,
            item.symbol,
        )
        for item in result
    }

    for preview in quick_flip_previews:
        opportunity = (
            _quick_flip_preview_opportunity(
                preview=preview,
                performance=(
                    performance.quick_flip
                ),
            )
        )

        if opportunity is None:
            continue

        key = (
            opportunity.strategy,
            opportunity.symbol,
        )

        if key in existing:
            continue

        result.append(
            opportunity
        )
        existing.add(
            key
        )

    return result


def _quick_flip_confirmation_times(
    *,
    quick_flip_results: dict,
    quick_flip_previews: list[dict],
) -> dict[str, str]:
    """
    Recover causal Quick Flip confirmation times by symbol.

    Prefer the live strategy result. Fall back to PREVIEW READY
    metadata so an earlier confirmed setup remains sequenced even
    if the final in-memory result has changed.
    """
    result: dict[
        str,
        str,
    ] = {}

    for symbol, item in (
        quick_flip_results.items()
    ):
        if item is None:
            continue

        signal = getattr(
            item,
            "signal",
            None,
        )

        if signal is None:
            continue

        confirmation = getattr(
            signal,
            "confirmation_time",
            None,
        )

        if confirmation is None:
            continue

        if hasattr(
            confirmation,
            "isoformat",
        ):
            confirmation = (
                confirmation.isoformat()
            )

        result[
            str(symbol).upper()
        ] = str(
            confirmation
        )

    for preview in (
        quick_flip_previews
    ):
        if (
            not isinstance(
                preview,
                dict,
            )
            or preview.get(
                "status"
            )
            != "PREVIEW READY"
        ):
            continue

        symbol = str(
            preview.get(
                "symbol",
                "",
            )
        ).upper()

        confirmation = preview.get(
            "confirmationTime"
        )

        if (
            not symbol
            or not confirmation
        ):
            continue

        result.setdefault(
            symbol,
            str(
                confirmation
            ),
        )

    return result


def build_causal_dominance_equal_weight_shadow(
    *,
    opportunities: list[
        RiskAdjustedOpportunity
    ],
    quick_flip_results: dict,
    quick_flip_previews: list[dict],
    deployable_pool: float,
    production_allocations: dict[
        tuple[str, str],
        float,
    ] | None = None,
) -> dict:
    """
    Replay the researched live decision sequence.

    Sequence:
      1. Manipulation decision at 09:45 ET.
      2. Zero capital is pre-reserved for Quick Flip.
      3. Only genuinely retained cash can reach later Quick Flip
         confirmation events.
      4. Each event uses dominance selection; otherwise equal
         weighting.

    This is observation only. It cannot alter production sizing.
    """
    original_pool = round(
        max(
            0.0,
            float(
                deployable_pool
            ),
        ),
        2,
    )

    remaining = original_pool

    production = (
        production_allocations
        or {}
    )

    events = []

    manipulation = [
        item
        for item in opportunities
        if item.strategy
        == "MANIPULATION"
    ]

    quick_flip = [
        item
        for item in opportunities
        if item.strategy
        == "QUICK_FLIP"
    ]

    confirmation_times = (
        _quick_flip_confirmation_times(
            quick_flip_results=(
                quick_flip_results
            ),
            quick_flip_previews=(
                quick_flip_previews
            ),
        )
    )

    opportunity_by_key = {
        (
            item.strategy,
            item.symbol,
        ): item
        for item in opportunities
    }

    def event_payload(
        event_time,
        plan,
    ):
        payload = (
            dominance_equal_plan_to_dict(
                plan
            )
        )

        payload[
            "eventTime"
        ] = event_time

        for allocation in payload[
            "allocations"
        ]:
            key = (
                allocation[
                    "strategy"
                ],
                allocation[
                    "symbol"
                ],
            )

            allocation[
                "productionRecommendedAllocation"
            ] = round(
                float(
                    production.get(
                        key,
                        0.0,
                    )
                ),
                2,
            )

            opportunity = (
                opportunity_by_key.get(
                    key
                )
            )

            entry_price = (
                None
                if opportunity is None
                else opportunity.entry_price
            )

            allocation[
                "entryPrice"
            ] = entry_price

            allocation[
                "fractionalQuantity"
            ] = (
                fractional_quantity_for_shadow_allocation(
                    allocation=(
                        allocation[
                            "recommendedAllocation"
                        ]
                    ),
                    entry_price=entry_price,
                )
            )

        return payload

    if (
        manipulation
        and remaining > 0
    ):
        plan = (
            build_dominance_equal_weight_plan(
                manipulation,
                deployable_pool=(
                    remaining
                ),
            )
        )

        events.append(
            event_payload(
                "09:45_ET",
                plan,
            )
        )

        funded = any(
            item.allocation_weight > 0
            for item
            in plan.allocations
        )

        if funded:
            # Zero-reserve research policy:
            # a funded 09:45 decision consumes the available pool.
            remaining = 0.0

    groups: dict[
        str,
        list[
            RiskAdjustedOpportunity
        ],
    ] = {}

    unsequenced = []

    for item in quick_flip:
        confirmation = (
            confirmation_times.get(
                item.symbol
            )
        )

        if not confirmation:
            unsequenced.append(
                item.symbol
            )
            continue

        groups.setdefault(
            confirmation,
            [],
        ).append(
            item
        )

    if remaining > 0:
        for event_time in sorted(
            groups
        ):
            plan = (
                build_dominance_equal_weight_plan(
                    groups[
                        event_time
                    ],
                    deployable_pool=(
                        remaining
                    ),
                )
            )

            events.append(
                event_payload(
                    event_time,
                    plan,
                )
            )

            funded = any(
                item.allocation_weight
                > 0
                for item
                in plan.allocations
            )

            if funded:
                remaining = 0.0
                break

    return {
        "method": (
            "CAUSAL_DOMINANCE_EQUAL_WEIGHT_SHADOW_V1"
        ),
        "shadowOnly": True,
        "fractionalSizingResearch": True,
        "fractionalExecutionAssumption": (
            "ALLOCATION_DIVIDED_BY_LIMIT_ENTRY"
        ),
        "productionSizingChanged": False,
        "sequence": (
            "MANIPULATION_09:45_THEN_"
            "QUICK_FLIP_CONFIRMATION"
        ),
        "quickFlipReserveFraction": 0.0,
        "quickFlipAutomaticStopLoss": False,
        "deployablePool": (
            original_pool
        ),
        "allocated": round(
            original_pool
            - remaining,
            2,
        ),
        "cashRetained": round(
            remaining,
            2,
        ),
        "quickFlipCandidatesObserved": sorted({
            item.symbol
            for item in quick_flip
        }),
        "unsequencedQuickFlipSymbols": (
            sorted(
                set(
                    unsequenced
                )
            )
        ),
        "events": events,
    }


def build_live_shadow_payload(
    *,
    trading_date: date | str,
    history: LiveShadowHistory,
    stocks: dict,
    quick_flip_results: dict,
    quick_flip_previews: list[dict],
    deployable_pool: float,
) -> dict:
    """
    Build a JSON-ready live V2 comparison.

    This is observation only and never feeds values back into
    either Webull preview service.
    """
    opportunities = (
        build_live_opportunities(
            stocks=stocks,
            quick_flip_results=(
                quick_flip_results
            ),
            performance=(
                history.performance
            ),
        )
    )

    opportunities = (
        add_previewed_quick_flip_opportunities(
            opportunities=opportunities,
            quick_flip_previews=(
                quick_flip_previews
            ),
            performance=(
                history.performance
            ),
        )
    )

    production = (
        current_production_allocations(
            stocks=stocks,
            quick_flip_previews=(
                quick_flip_previews
            ),
        )
    )

    dominance_equal_shadow = (
        build_causal_dominance_equal_weight_shadow(
            opportunities=opportunities,
            quick_flip_results=(
                quick_flip_results
            ),
            quick_flip_previews=(
                quick_flip_previews
            ),
            deployable_pool=(
                deployable_pool
            ),
            production_allocations=(
                production
            ),
        )
    )

    report = (
        build_daily_shadow_allocation_report(
            trading_date=trading_date,
            model="v1",
            opportunities=opportunities,
            deployable_pool=(
                deployable_pool
            ),
        )
    )

    payload = shadow_report_to_dict(
        report
    )

    opportunity_by_key = {
        (
            item.strategy,
            item.symbol,
        ): item
        for item in opportunities
    }

    comparisons = []

    for item in payload[
        "comparisons"
    ]:
        key = (
            item["strategy"],
            item["symbol"],
        )

        opportunity = (
            opportunity_by_key[key]
        )

        enriched = dict(
            item
        )

        enriched.update({
            "expectedRewardPct": (
                opportunity
                .expected_reward_pct
            ),
            "expectedRiskPct": (
                opportunity
                .expected_risk_pct
            ),
            "historicalExpectancyPct": (
                opportunity
                .expectancy_pct
            ),
            "historicalWinRatePct": (
                opportunity
                .win_rate_pct
            ),
            "historicalSamples": (
                opportunity
                .historical_samples
            ),
            "productionRecommendedAllocation": (
                production.get(
                    key,
                    0.0,
                )
            ),
        })

        comparisons.append(
            enriched
        )

    payload["comparisons"] = (
        comparisons
    )

    payload.update({
        "historySource": str(
            history.source_path
        ),
        "historyStartDate": (
            history.source_start_date
        ),
        "historyEndDate": (
            history.source_end_date
        ),
        "historyStrict": (
            history.performance.strict
        ),
        "manipulationHistoricalSamples": (
            history.performance
            .manipulation
            .filled_trades
        ),
        "quickFlipHistoricalSamples": (
            history.performance
            .quick_flip
            .filled_trades
        ),
        "dominanceEqualWeightShadow": (
            dominance_equal_shadow
        ),
        "productionSizingChanged": False,
        "shadowOnly": True,
    })

    return payload


def write_live_shadow_payload_atomic(
    *,
    payload: dict,
    output_path: Path | str,
) -> Path:
    """
    Atomically persist one live risk-adjusted shadow snapshot.

    This file is research/observation output only.
    """
    path = Path(output_path)

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary = path.with_suffix(
        path.suffix + ".tmp"
    )

    encoded = (
        json.dumps(
            payload,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )

    temporary.write_text(
        encoded,
        encoding="utf-8",
    )

    temporary.replace(path)

    return path


def write_live_shadow_snapshot(
    *,
    trading_date: date | str,
    stocks: dict,
    quick_flip_results: dict,
    quick_flip_previews: list[dict],
    research_dir: Path | str = "runtime/research",
    output_dir: Path | str = (
        "runtime/risk_adjusted_shadow"
    ),
) -> tuple[Path, dict]:
    """
    Build and persist the end-of-live-session V2 shadow snapshot.

    Historical data must end before trading_date.

    Current production preview allocations are observed only.
    V2 allocations are never fed back into preview sizing.
    """
    trading_date_text = _date_text(
        trading_date
    )

    history = load_live_shadow_history(
        trading_date=trading_date_text,
        research_dir=research_dir,
        model="v1",
        strict=True,
    )

    deployable_pool = (
        derive_original_daily_pool(
            stocks=stocks,
            quick_flip_previews=(
                quick_flip_previews
            ),
        )
    )

    output_path = (
        Path(output_dir)
        / f"{trading_date_text}.json"
    )

    if deployable_pool is None:
        payload = {
            "tradingDate": trading_date_text,
            "model": "V1",
            "status": (
                "SKIPPED_NO_CAPITAL_METADATA"
            ),
            "shadowOnly": True,
            "productionSizingChanged": False,
            "historySource": str(
                history.source_path
            ),
            "historyStartDate": (
                history.source_start_date
            ),
            "historyEndDate": (
                history.source_end_date
            ),
            "historyStrict": (
                history.performance.strict
            ),
            "manipulationHistoricalSamples": (
                history.performance
                .manipulation
                .filled_trades
            ),
            "quickFlipHistoricalSamples": (
                history.performance
                .quick_flip
                .filled_trades
            ),
            "comparisons": [],
        }

    else:
        payload = build_live_shadow_payload(
            trading_date=trading_date_text,
            history=history,
            stocks=stocks,
            quick_flip_results=(
                quick_flip_results
            ),
            quick_flip_previews=(
                quick_flip_previews
            ),
            deployable_pool=(
                deployable_pool
            ),
        )

        payload["status"] = "READY"

    written_path = (
        write_live_shadow_payload_atomic(
            payload=payload,
            output_path=output_path,
        )
    )

    return written_path, payload

