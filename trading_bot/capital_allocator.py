from __future__ import annotations

from dataclasses import dataclass

from .webull_safety import WebullAccountState


@dataclass(frozen=True)
class CapitalAllocationPlan:
    candidate_count: int
    available_cash: float
    buying_power: float | None
    safe_capital_base: float
    deployment_fraction: float
    deployable_cash: float
    remaining_exposure_capacity: float
    deployable_pool_before_reservations: float
    reserved_recommendation_exposure: float
    deployable_pool: float
    per_candidate_budget: float
    allocation_weight: float
    method: str = "EQUAL_WEIGHT_CASH_SAFE"


def build_preview_exposure_ceiling(
    account: WebullAccountState,
    *,
    deployment_fraction: float,
) -> float:
    """
    Return the absolute exposure ceiling used only for preview
    recommendations.

    New preview capital is limited to the configured fraction of
    the smaller of verified available cash and reported buying
    power. Existing real account exposure is added back to the
    absolute ceiling so it is not deducted twice.

    Real-order safety limits are separate.
    """
    if not 0 < deployment_fraction <= 1:
        raise ValueError(
            "Deployment fraction must be greater than 0 "
            "and at most 1."
        )

    available_cash = max(
        0.0,
        float(account.available_cash),
    )

    if account.buying_power is None:
        safe_available_capital = available_cash
    else:
        safe_available_capital = min(
            available_cash,
            max(
                0.0,
                float(account.buying_power),
            ),
        )

    new_capital_allowance = (
        safe_available_capital
        * float(deployment_fraction)
    )

    return round(
        account.current_total_exposure
        + new_capital_allowance,
        2,
    )


def build_equal_weight_capital_plan(
    account: WebullAccountState,
    candidate_count: int,
    *,
    deployment_fraction: float,
    operational_cap: float,
    hard_cap: float,
    reserved_recommendation_exposure: float = 0.0,
) -> CapitalAllocationPlan:
    """
    Build an equal-weight preview allocation from verified
    cash-safe account capacity.

    Buying power may reduce the capital base but can never
    increase it beyond verified available cash.

    This function recommends preview sizing only. It does not
    place, modify, replace, or cancel broker orders.
    """
    if candidate_count <= 0:
        raise ValueError(
            "Capital allocation requires at least one candidate."
        )

    if not 0 < deployment_fraction <= 1:
        raise ValueError(
            "Deployment fraction must be greater than 0 "
            "and at most 1."
        )

    available_cash = max(
        0.0,
        float(account.available_cash),
    )

    buying_power = account.buying_power

    if buying_power is None:
        safe_capital_base = available_cash
    else:
        buying_power = max(
            0.0,
            float(buying_power),
        )
        safe_capital_base = min(
            available_cash,
            buying_power,
        )

    current_exposure = max(
        0.0,
        float(account.current_total_exposure),
    )

    operational_remaining = max(
        0.0,
        float(operational_cap) - current_exposure,
    )

    hard_remaining = max(
        0.0,
        float(hard_cap) - current_exposure,
    )

    remaining_exposure_capacity = min(
        operational_remaining,
        hard_remaining,
    )

    deployable_cash = (
        safe_capital_base
        * float(deployment_fraction)
    )

    reserved_recommendation_exposure = max(
        0.0,
        float(reserved_recommendation_exposure),
    )

    deployable_pool_before_reservations = min(
        deployable_cash,
        remaining_exposure_capacity,
    )

    # Earlier PREVIEW READY recommendations remain reserved for
    # the rest of this trading day. This is intentionally
    # conservative: a later strategy may use only what remains.
    deployable_pool = max(
        0.0,
        deployable_pool_before_reservations
        - reserved_recommendation_exposure,
    )

    per_candidate_budget = (
        deployable_pool / candidate_count
    )

    return CapitalAllocationPlan(
        candidate_count=candidate_count,
        available_cash=round(
            available_cash,
            2,
        ),
        buying_power=(
            None
            if buying_power is None
            else round(buying_power, 2)
        ),
        safe_capital_base=round(
            safe_capital_base,
            2,
        ),
        deployment_fraction=round(
            float(deployment_fraction),
            6,
        ),
        deployable_cash=round(
            deployable_cash,
            2,
        ),
        remaining_exposure_capacity=round(
            remaining_exposure_capacity,
            2,
        ),
        deployable_pool_before_reservations=round(
            deployable_pool_before_reservations,
            2,
        ),
        reserved_recommendation_exposure=round(
            reserved_recommendation_exposure,
            2,
        ),
        deployable_pool=round(
            deployable_pool,
            2,
        ),
        per_candidate_budget=round(
            per_candidate_budget,
            2,
        ),
        allocation_weight=round(
            1.0 / candidate_count,
            6,
        ),
    )
