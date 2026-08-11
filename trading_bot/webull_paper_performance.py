from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from .webull_paper_order_store import (
    WebullPaperOrderRecord,
    WebullPaperOrderStore,
)


@dataclass(frozen=True)
class WebullPaperDailyPerformance:
    date: str

    orders_approved: int
    trades_entered: int
    open_trades: int
    closed_trades: int
    no_entry: int

    target_exits: int
    stop_exits: int
    time_exits: int

    profitable_trades: int
    losing_trades: int
    breakeven_trades: int

    win_rate_pct: float | None

    realized_pnl: float
    average_pnl_per_trade: float | None
    average_return_pct: float | None
    average_winner: float | None
    average_loser: float | None
    expectancy_per_trade: float | None

    average_mfe_pct: float | None
    average_mae_pct: float | None

    best_trade_symbol: str | None
    best_trade_pnl: float | None
    worst_trade_symbol: str | None
    worst_trade_pnl: float | None

    def to_dict(self) -> dict:
        return asdict(self)


def _average(
    values: list[float],
    *,
    digits: int = 6,
) -> float | None:
    if not values:
        return None

    return round(
        sum(values) / len(values),
        digits,
    )


def _record_trading_date(
    record: WebullPaperOrderRecord,
) -> str:
    eastern = ZoneInfo("America/New_York")

    return (
        record.submitted_at
        .astimezone(eastern)
        .strftime("%Y-%m-%d")
    )


def build_webull_paper_daily_performance(
    *,
    date_str: str,
    records: list[WebullPaperOrderRecord],
) -> WebullPaperDailyPerformance:
    """
    Build realized LOCAL PAPER performance for one New York
    trading date.

    NO ENTRY orders count as approved orders but not entered
    trades. OPEN positions count as entered trades but are not
    included in realized P&L or win-rate calculations.
    """
    # Validate the requested date instead of silently accepting
    # malformed values.
    datetime.strptime(
        date_str,
        "%Y-%m-%d",
    )

    daily = [
        record
        for record in records
        if _record_trading_date(record) == date_str
    ]

    entered = [
        record
        for record in daily
        if record.filled_at is not None
    ]

    open_trades = [
        record
        for record in entered
        if record.lifecycle_status == "OPEN"
    ]

    closed_entered = [
        record
        for record in entered
        if (
            record.lifecycle_status == "CLOSED"
            and record.realized_pnl is not None
            and record.return_pct is not None
        )
    ]

    no_entry = [
        record
        for record in daily
        if (
            record.lifecycle_status == "CLOSED"
            and record.exit_reason == "NO ENTRY"
            and record.filled_at is None
        )
    ]

    target_exits = [
        record
        for record in closed_entered
        if record.exit_reason == "TARGET"
    ]

    stop_exits = [
        record
        for record in closed_entered
        if record.exit_reason == "STOP"
    ]

    time_exits = [
        record
        for record in closed_entered
        if record.exit_reason == "TIME EXIT"
    ]

    profitable = [
        record
        for record in closed_entered
        if record.realized_pnl > 0
    ]

    losing = [
        record
        for record in closed_entered
        if record.realized_pnl < 0
    ]

    breakeven = [
        record
        for record in closed_entered
        if record.realized_pnl == 0
    ]

    realized_values = [
        float(record.realized_pnl)
        for record in closed_entered
    ]

    return_values = [
        float(record.return_pct)
        for record in closed_entered
    ]

    mfe_values = [
        float(record.mfe_pct)
        for record in closed_entered
        if record.mfe_pct is not None
    ]

    mae_values = [
        float(record.mae_pct)
        for record in closed_entered
        if record.mae_pct is not None
    ]

    winner_values = [
        float(record.realized_pnl)
        for record in profitable
    ]

    loser_values = [
        float(record.realized_pnl)
        for record in losing
    ]

    best_trade = (
        max(
            closed_entered,
            key=lambda record: (
                record.realized_pnl,
                record.symbol,
            ),
        )
        if closed_entered
        else None
    )

    worst_trade = (
        min(
            closed_entered,
            key=lambda record: (
                record.realized_pnl,
                record.symbol,
            ),
        )
        if closed_entered
        else None
    )

    closed_count = len(closed_entered)

    # Win rate deliberately excludes breakeven trades from the
    # numerator but keeps all realized trades in the denominator.
    win_rate_pct = (
        round(
            len(profitable)
            / closed_count
            * 100.0,
            6,
        )
        if closed_count
        else None
    )

    realized_pnl = round(
        sum(realized_values),
        6,
    )

    # With realized local-paper P&L, arithmetic average P&L per
    # closed trade is the empirical expectancy per trade.
    average_pnl = _average(
        realized_values
    )

    return WebullPaperDailyPerformance(
        date=date_str,
        orders_approved=len(daily),
        trades_entered=len(entered),
        open_trades=len(open_trades),
        closed_trades=closed_count,
        no_entry=len(no_entry),
        target_exits=len(target_exits),
        stop_exits=len(stop_exits),
        time_exits=len(time_exits),
        profitable_trades=len(profitable),
        losing_trades=len(losing),
        breakeven_trades=len(breakeven),
        win_rate_pct=win_rate_pct,
        realized_pnl=realized_pnl,
        average_pnl_per_trade=average_pnl,
        average_return_pct=_average(
            return_values
        ),
        average_winner=_average(
            winner_values
        ),
        average_loser=_average(
            loser_values
        ),
        expectancy_per_trade=average_pnl,
        average_mfe_pct=_average(
            mfe_values
        ),
        average_mae_pct=_average(
            mae_values
        ),
        best_trade_symbol=(
            best_trade.symbol
            if best_trade is not None
            else None
        ),
        best_trade_pnl=(
            round(
                float(best_trade.realized_pnl),
                6,
            )
            if best_trade is not None
            else None
        ),
        worst_trade_symbol=(
            worst_trade.symbol
            if worst_trade is not None
            else None
        ),
        worst_trade_pnl=(
            round(
                float(worst_trade.realized_pnl),
                6,
            )
            if worst_trade is not None
            else None
        ),
    )


def load_webull_paper_daily_performance(
    *,
    date_str: str,
    store: WebullPaperOrderStore | None = None,
) -> WebullPaperDailyPerformance:
    """
    Load the durable LOCAL PAPER ledger and build one day's
    performance report.
    """
    store = store or WebullPaperOrderStore()

    return build_webull_paper_daily_performance(
        date_str=date_str,
        records=list(
            store.load().values()
        ),
    )
