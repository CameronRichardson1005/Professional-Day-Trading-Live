from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from .risk_adjusted_dominance_shadow import (
    DominanceEqualPlan,
    build_dominance_equal_weight_plan,
)
from .config import TICKERS
from .risk_adjusted_live_shadow import (
    find_latest_realized_master_before,
)
from .risk_adjusted_walk_forward import (
    performance_before_date,
    production_rows,
)
from .scanner_performance_summary import (
    load_master_rows,
)
from .risk_adjusted_strategy_adapters import (
    build_manipulation_opportunity,
    build_quick_flip_opportunity,
)


LIVE_COMMITTED_POLICY_METHOD = (
    "CAUSAL_DOMINANCE_EQUAL_WEIGHT_LIVE_V1"
)



def load_live_committed_history(
    *,
    trading_date: str,
    research_dir: Path | str = "runtime/research",
):
    """
    Load the exact causal history used by the committed
    walk-forward production policy.

    Production history is:
      - every permanent/core ticker, plus
      - candidates selected by scanner V1 on that historical day.

    performance_before_date() applies the strict anti-lookahead
    boundary and converts those production-eligible rows into the
    same historical summaries used during walk-forward research.
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
            "before the requested live trading date."
        )

    rows = load_master_rows(
        source_path
    )

    production_history = production_rows(
        rows,
        permanent_symbols={
            str(symbol).upper()
            for symbol in TICKERS
        },
    )

    manipulation = performance_before_date(
        production_history=production_history,
        trading_date=trading_date,
        strategy="MANIPULATION",
    )

    quick_flip = performance_before_date(
        production_history=production_history,
        trading_date=trading_date,
        strategy="QUICK_FLIP",
    )

    return SimpleNamespace(
        source_path=source_path,
        production_history=production_history,
        manipulation=manipulation,
        quick_flip=quick_flip,
    )

def build_live_manipulation_allocation_plan(
    *,
    stocks: dict[str, Any],
    trading_date: str,
    deployable_pool: float,
    research_dir: Path | str = "runtime/research",
) -> DominanceEqualPlan:
    """
    Build the committed 09:45 Manipulation capital decision.

    Historical performance is loaded strictly from a realized
    master whose end date is BEFORE trading_date.

    This function does not submit broker orders.
    """
    history = load_live_committed_history(
        trading_date=trading_date,
        research_dir=research_dir,
    )

    opportunities = []

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
                    history.manipulation
                ),
            )
        )

    return build_dominance_equal_weight_plan(
        opportunities,
        deployable_pool=deployable_pool,
    )


def build_live_quick_flip_allocation_plan(
    *,
    results: dict[str, Any],
    trading_date: str,
    deployable_pool: float,
    research_dir: Path | str = "runtime/research",
) -> DominanceEqualPlan:
    """
    Build one causal Quick Flip confirmation-group decision.

    The caller supplies only the newly confirmed group for the
    current monitoring event.

    Quick Flip downside uses the committed historical
    75th-percentile absolute MAE estimate. It remains a ranking
    input only and is NOT an automatic stop loss.

    This function does not submit broker orders.
    """
    history = load_live_committed_history(
        trading_date=trading_date,
        research_dir=research_dir,
    )

    confirmed = []

    for result in results.values():
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

        confirmation = getattr(
            signal,
            "confirmation_time",
            None,
        )

        if confirmation is None:
            # Match the causal shadow policy:
            # an unsequenced Quick Flip opportunity cannot
            # receive capital.
            continue

        if hasattr(
            confirmation,
            "isoformat",
        ):
            confirmation_text = (
                confirmation.isoformat()
            )
        else:
            confirmation_text = str(
                confirmation
            ).strip()

        if not confirmation_text:
            continue

        confirmed.append(
            (
                confirmation_text,
                signal,
            )
        )

    if confirmed:
        earliest_confirmation = min(
            confirmation
            for confirmation, _
            in confirmed
        )

        signals = [
            signal
            for confirmation, signal
            in confirmed
            if confirmation
            == earliest_confirmation
        ]
    else:
        signals = []

    opportunities = [
        build_quick_flip_opportunity(
            signal,
            performance=(
                history.quick_flip
            ),
        )
        for signal in signals
    ]

    return build_dominance_equal_weight_plan(
        opportunities,
        deployable_pool=deployable_pool,
    )


def rank_committed_allocations(plan):
    """
    Return committed-policy allocations in the canonical order
    used when finite execution capacity forces candidates to
    compete.

    Highest causal allocation score is attempted first.
    Symbol and strategy provide deterministic tie-breaks.

    This changes no allocation weights or dollar recommendations.
    """
    return tuple(
        sorted(
            plan.allocations,
            key=lambda item: (
                -float(item.score),
                item.symbol,
                item.strategy,
            ),
        )
    )
