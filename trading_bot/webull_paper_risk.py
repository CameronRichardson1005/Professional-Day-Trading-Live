from __future__ import annotations

import math
import os

from dataclasses import dataclass
from datetime import datetime, time
from zoneinfo import ZoneInfo

from .webull_paper_order_store import (
    WebullPaperOrderRecord,
    WebullPaperOrderStore,
)
from .webull_paper_portfolio import (
    build_webull_paper_portfolio,
    configured_paper_starting_cash,
)


DEFAULT_PAPER_MAX_DAILY_LOSS = 50.0


class WebullPaperRiskError(RuntimeError):
    pass


@dataclass(frozen=True)
class WebullPaperRiskDecision:
    allowed: bool
    reason: str

    starting_cash: float
    cash: float
    pending_reserved_cash: float
    available_for_new_orders: float

    proposed_exposure: float
    projected_available_cash: float

    daily_realized_pnl: float
    max_daily_loss: float


def configured_paper_max_daily_loss() -> float:
    raw = os.getenv(
        "WEBULL_PAPER_MAX_DAILY_LOSS",
        str(DEFAULT_PAPER_MAX_DAILY_LOSS),
    )

    try:
        value = float(raw)
    except (TypeError, ValueError) as error:
        raise WebullPaperRiskError(
            "INVALID_PAPER_MAX_DAILY_LOSS"
        ) from error

    if not math.isfinite(value) or value <= 0:
        raise WebullPaperRiskError(
            "INVALID_PAPER_MAX_DAILY_LOSS"
        )

    return round(value, 2)


def _daily_realized_pnl(
    *,
    records: list[WebullPaperOrderRecord],
    now: datetime,
) -> float:
    if now.tzinfo is None:
        raise WebullPaperRiskError(
            "PAPER_RISK_CLOCK_MUST_BE_TIMEZONE_AWARE"
        )

    eastern = ZoneInfo("America/New_York")
    trading_date = now.astimezone(eastern).date()

    realized = 0.0

    for record in records:
        submitted_date = (
            record.submitted_at
            .astimezone(eastern)
            .date()
        )

        if submitted_date != trading_date:
            continue

        if (
            record.lifecycle_status != "CLOSED"
            or record.filled_at is None
            or record.realized_pnl is None
        ):
            continue

        realized += float(record.realized_pnl)

    return round(realized, 6)


def evaluate_webull_paper_risk(
    *,
    records: list[WebullPaperOrderRecord],
    proposed_exposure: float,
    now: datetime,
    starting_cash: float | None = None,
    max_daily_loss: float | None = None,
) -> WebullPaperRiskDecision:
    """
    Evaluate LOCAL PAPER portfolio risk before consuming an
    approval ticket.

    This function is simulation-only. It does not read or mutate
    any Webull broker account, order, approval, or position.
    """
    if now.tzinfo is None:
        raise WebullPaperRiskError(
            "PAPER_RISK_CLOCK_MUST_BE_TIMEZONE_AWARE"
        )

    try:
        proposed_exposure = float(
            proposed_exposure
        )
    except (TypeError, ValueError) as error:
        raise WebullPaperRiskError(
            "INVALID_PAPER_PROPOSED_EXPOSURE"
        ) from error

    if (
        not math.isfinite(proposed_exposure)
        or proposed_exposure <= 0
    ):
        raise WebullPaperRiskError(
            "INVALID_PAPER_PROPOSED_EXPOSURE"
        )

    if starting_cash is None:
        starting_cash = (
            configured_paper_starting_cash()
        )

    if max_daily_loss is None:
        max_daily_loss = (
            configured_paper_max_daily_loss()
        )

    starting_cash = float(starting_cash)
    max_daily_loss = float(max_daily_loss)

    if (
        not math.isfinite(starting_cash)
        or starting_cash <= 0
    ):
        raise WebullPaperRiskError(
            "INVALID_PAPER_STARTING_CASH"
        )

    if (
        not math.isfinite(max_daily_loss)
        or max_daily_loss <= 0
    ):
        raise WebullPaperRiskError(
            "INVALID_PAPER_MAX_DAILY_LOSS"
        )

    portfolio = build_webull_paper_portfolio(
        records=records,
        starting_cash=starting_cash,
    )

    pending_reserved_cash = round(
        sum(
            float(record.proposed_exposure)
            for record in records
            if record.lifecycle_status
            == "ENTRY PENDING"
        ),
        6,
    )

    available_for_new_orders = round(
        max(
            portfolio.cash
            - pending_reserved_cash,
            0.0,
        ),
        6,
    )

    projected_available_cash = round(
        available_for_new_orders
        - proposed_exposure,
        6,
    )

    daily_realized_pnl = (
        _daily_realized_pnl(
            records=records,
            now=now,
        )
    )

    def decision(
        *,
        allowed: bool,
        reason: str,
    ) -> WebullPaperRiskDecision:
        return WebullPaperRiskDecision(
            allowed=allowed,
            reason=reason,
            starting_cash=round(
                starting_cash,
                2,
            ),
            cash=portfolio.cash,
            pending_reserved_cash=(
                pending_reserved_cash
            ),
            available_for_new_orders=(
                available_for_new_orders
            ),
            proposed_exposure=round(
                proposed_exposure,
                2,
            ),
            projected_available_cash=(
                projected_available_cash
            ),
            daily_realized_pnl=(
                daily_realized_pnl
            ),
            max_daily_loss=round(
                max_daily_loss,
                2,
            ),
        )

    if (
        daily_realized_pnl
        <= -max_daily_loss
    ):
        return decision(
            allowed=False,
            reason=(
                "PAPER_DAILY_LOSS_LIMIT_REACHED"
            ),
        )

    if (
        proposed_exposure
        > available_for_new_orders
    ):
        return decision(
            allowed=False,
            reason=(
                "PAPER_INSUFFICIENT_AVAILABLE_CASH"
            ),
        )

    return decision(
        allowed=True,
        reason="PAPER_RISK_APPROVED",
    )


@dataclass(frozen=True)
class WebullPaperRiskStatus:
    trading_allowed: bool
    reason: str
    starting_cash: float
    cash: float
    pending_reserved_cash: float
    available_for_new_orders: float
    daily_realized_pnl: float
    max_daily_loss: float
    remaining_daily_loss: float
    simulation_only: bool = True
    broker_submitted: bool = False


def build_webull_paper_risk_status(
    *,
    records: list[WebullPaperOrderRecord],
    now: datetime,
    starting_cash: float | None = None,
    max_daily_loss: float | None = None,
) -> WebullPaperRiskStatus:
    """
    Build a read-only LOCAL PAPER risk snapshot.

    It does not consume approvals and cannot submit broker orders.
    """
    if starting_cash is None:
        starting_cash = configured_paper_starting_cash()

    if max_daily_loss is None:
        max_daily_loss = configured_paper_max_daily_loss()

    portfolio = build_webull_paper_portfolio(
        records=records,
        starting_cash=starting_cash,
    )

    pending_reserved_cash = round(
        sum(
            float(record.proposed_exposure)
            for record in records
            if record.lifecycle_status
            == "ENTRY PENDING"
        ),
        6,
    )

    available_for_new_orders = round(
        max(
            portfolio.cash - pending_reserved_cash,
            0.0,
        ),
        6,
    )

    daily_realized_pnl = _daily_realized_pnl(
        records=records,
        now=now,
    )

    remaining_daily_loss = round(
        max(
            float(max_daily_loss)
            + daily_realized_pnl,
            0.0,
        ),
        6,
    )

    if daily_realized_pnl <= -float(max_daily_loss):
        trading_allowed = False
        reason = "PAPER_DAILY_LOSS_LIMIT_REACHED"
    elif available_for_new_orders <= 0:
        trading_allowed = False
        reason = "PAPER_NO_AVAILABLE_CASH"
    else:
        trading_allowed = True
        reason = "PAPER_TRADING_ALLOWED"

    return WebullPaperRiskStatus(
        trading_allowed=trading_allowed,
        reason=reason,
        starting_cash=round(float(starting_cash), 2),
        cash=portfolio.cash,
        pending_reserved_cash=pending_reserved_cash,
        available_for_new_orders=available_for_new_orders,
        daily_realized_pnl=daily_realized_pnl,
        max_daily_loss=round(float(max_daily_loss), 2),
        remaining_daily_loss=remaining_daily_loss,
    )



def load_webull_paper_risk_status(
    *,
    date_str: str,
    store: WebullPaperOrderStore | None = None,
    starting_cash: float | None = None,
    max_daily_loss: float | None = None,
) -> WebullPaperRiskStatus:
    """
    Reconstruct read-only LOCAL PAPER risk status for one
    New York trading date from the durable paper-order ledger.
    """
    try:
        trading_date = datetime.strptime(
            date_str,
            "%Y-%m-%d",
        ).date()
    except ValueError as error:
        raise WebullPaperRiskError(
            "INVALID_PAPER_RISK_DATE"
        ) from error

    eastern = ZoneInfo("America/New_York")

    evaluation_time = datetime.combine(
        trading_date,
        time(hour=16),
        tzinfo=eastern,
    )

    effective_store = (
        store or WebullPaperOrderStore()
    )

    records = list(
        effective_store.load().values()
    )

    return build_webull_paper_risk_status(
        records=records,
        now=evaluation_time,
        starting_cash=starting_cash,
        max_daily_loss=max_daily_loss,
    )
