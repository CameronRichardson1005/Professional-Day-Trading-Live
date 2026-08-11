from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from .webull_paper_order_store import (
    WebullPaperOrderRecord,
    WebullPaperOrderStore,
)


@dataclass(frozen=True)
class WebullPaperAnalyticsGroup:
    key: str

    approved_orders: int
    entered_trades: int
    closed_trades: int
    no_entry: int

    wins: int
    losses: int
    breakeven: int

    target_exits: int
    stop_exits: int
    time_exits: int

    win_rate_pct: float | None
    realized_pnl: float
    average_pnl_per_trade: float | None
    average_return_pct: float | None
    expectancy_per_trade: float | None

    average_mfe_pct: float | None
    average_mae_pct: float | None

    sample_label: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class WebullPaperAnalyticsReport:
    total_orders: int
    entered_trades: int
    closed_trades: int
    open_trades: int
    no_entry: int

    realized_pnl: float
    win_rate_pct: float | None
    average_return_pct: float | None
    expectancy_per_trade: float | None

    by_symbol: tuple[WebullPaperAnalyticsGroup, ...]
    by_entry_time: tuple[WebullPaperAnalyticsGroup, ...]

    by_reward_risk: tuple[WebullPaperAnalyticsGroup, ...]
    by_impulse_atr: tuple[WebullPaperAnalyticsGroup, ...]
    by_pullback_volume: tuple[WebullPaperAnalyticsGroup, ...]
    by_confirmation_time: tuple[WebullPaperAnalyticsGroup, ...]

    simulation_only: bool = True
    broker_submitted: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


def _average(
    values: list[float],
) -> float | None:
    if not values:
        return None

    return round(
        sum(values) / len(values),
        6,
    )


def _sample_label(
    closed_trades: int,
) -> str:
    if closed_trades == 0:
        return "NO CLOSED SAMPLE"

    if closed_trades < 5:
        return "VERY SMALL SAMPLE"

    if closed_trades < 20:
        return "SMALL SAMPLE"

    if closed_trades < 50:
        return "DEVELOPING SAMPLE"

    return "LARGER SAMPLE"


def _entry_time_bucket(
    record: WebullPaperOrderRecord,
) -> str:
    if record.filled_at is None:
        return "NO ENTRY"

    eastern = ZoneInfo("America/New_York")
    local = record.filled_at.astimezone(eastern)

    minute = local.minute

    if minute < 15:
        end_minute = 14
        start_minute = 0
    elif minute < 30:
        start_minute = 15
        end_minute = 29
    elif minute < 45:
        start_minute = 30
        end_minute = 44
    else:
        start_minute = 45
        end_minute = 59

    return (
        f"{local.hour:02d}:{start_minute:02d}"
        f"-{local.hour:02d}:{end_minute:02d} ET"
    )


def _reward_risk_bucket(
    record: WebullPaperOrderRecord,
) -> str:
    value = record.reward_risk

    if value is None:
        return "UNAVAILABLE"

    value = float(value)

    if value < 1.50:
        return "<1.50"
    if value < 2.00:
        return "1.50-1.99"
    if value < 2.50:
        return "2.00-2.49"

    return ">=2.50"


def _impulse_atr_bucket(
    record: WebullPaperOrderRecord,
) -> str:
    value = record.impulse_atr_multiple

    if value is None:
        return "UNAVAILABLE"

    value = float(value)

    if value < 0.50:
        return "<0.50 ATR"
    if value < 0.75:
        return "0.50-0.74 ATR"
    if value < 1.00:
        return "0.75-0.99 ATR"
    if value < 1.50:
        return "1.00-1.49 ATR"

    return ">=1.50 ATR"


def _pullback_volume_bucket(
    record: WebullPaperOrderRecord,
) -> str:
    value = record.pullback_volume_ratio

    if value is None:
        return "UNAVAILABLE"

    value = float(value)

    if value < 0.50:
        return "<0.50"
    if value < 0.75:
        return "0.50-0.74"
    if value < 1.00:
        return "0.75-0.99"

    return ">=1.00"


def _confirmation_time_bucket(
    record: WebullPaperOrderRecord,
) -> str:
    value = record.confirmation_time

    if value is None or not value.strip():
        return "UNAVAILABLE"

    raw = value.strip()
    eastern = ZoneInfo("America/New_York")

    parsed = None

    try:
        parsed = datetime.fromisoformat(
            raw.replace("Z", "+00:00")
        )
    except ValueError:
        try:
            parsed = datetime.strptime(
                raw,
                "%H:%M",
            )
        except ValueError:
            return "UNPARSEABLE"

    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(eastern)

    hour = parsed.hour
    minute = parsed.minute

    if minute < 15:
        start_minute = 0
        end_minute = 14
    elif minute < 30:
        start_minute = 15
        end_minute = 29
    elif minute < 45:
        start_minute = 30
        end_minute = 44
    else:
        start_minute = 45
        end_minute = 59

    return (
        f"{hour:02d}:{start_minute:02d}"
        f"-{hour:02d}:{end_minute:02d} ET"
    )


def _group_records_by(
    *,
    records: list[WebullPaperOrderRecord],
    bucket_fn,
) -> tuple[WebullPaperAnalyticsGroup, ...]:
    grouped: dict[
        str,
        list[WebullPaperOrderRecord],
    ] = {}

    for record in records:
        key = bucket_fn(record)

        grouped.setdefault(
            key,
            [],
        ).append(record)

    return tuple(
        _group(
            key=key,
            records=group_records,
        )
        for key, group_records
        in sorted(grouped.items())
    )


def _group(
    *,
    key: str,
    records: list[WebullPaperOrderRecord],
) -> WebullPaperAnalyticsGroup:
    entered = [
        record
        for record in records
        if record.filled_at is not None
    ]

    closed = [
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
        for record in records
        if (
            record.lifecycle_status == "CLOSED"
            and record.exit_reason == "NO ENTRY"
            and record.filled_at is None
        )
    ]

    wins = [
        record
        for record in closed
        if float(record.realized_pnl) > 0
    ]

    losses = [
        record
        for record in closed
        if float(record.realized_pnl) < 0
    ]

    breakeven = [
        record
        for record in closed
        if float(record.realized_pnl) == 0
    ]

    pnl_values = [
        float(record.realized_pnl)
        for record in closed
    ]

    return_values = [
        float(record.return_pct)
        for record in closed
    ]

    mfe_values = [
        float(record.mfe_pct)
        for record in closed
        if record.mfe_pct is not None
    ]

    mae_values = [
        float(record.mae_pct)
        for record in closed
        if record.mae_pct is not None
    ]

    closed_count = len(closed)

    return WebullPaperAnalyticsGroup(
        key=key,
        approved_orders=len(records),
        entered_trades=len(entered),
        closed_trades=closed_count,
        no_entry=len(no_entry),
        wins=len(wins),
        losses=len(losses),
        breakeven=len(breakeven),
        target_exits=sum(
            record.exit_reason == "TARGET"
            for record in closed
        ),
        stop_exits=sum(
            record.exit_reason == "STOP"
            for record in closed
        ),
        time_exits=sum(
            record.exit_reason == "TIME EXIT"
            for record in closed
        ),
        win_rate_pct=(
            round(
                len(wins)
                / closed_count
                * 100.0,
                6,
            )
            if closed_count
            else None
        ),
        realized_pnl=round(
            sum(pnl_values),
            6,
        ),
        average_pnl_per_trade=_average(
            pnl_values
        ),
        average_return_pct=_average(
            return_values
        ),
        expectancy_per_trade=_average(
            pnl_values
        ),
        average_mfe_pct=_average(
            mfe_values
        ),
        average_mae_pct=_average(
            mae_values
        ),
        sample_label=_sample_label(
            closed_count
        ),
    )


def build_webull_paper_analytics(
    *,
    records: list[WebullPaperOrderRecord],
) -> WebullPaperAnalyticsReport:
    closed = [
        record
        for record in records
        if (
            record.filled_at is not None
            and record.lifecycle_status == "CLOSED"
            and record.realized_pnl is not None
            and record.return_pct is not None
        )
    ]

    open_trades = [
        record
        for record in records
        if (
            record.filled_at is not None
            and record.lifecycle_status == "OPEN"
        )
    ]

    no_entry = [
        record
        for record in records
        if (
            record.lifecycle_status == "CLOSED"
            and record.exit_reason == "NO ENTRY"
            and record.filled_at is None
        )
    ]

    entered = [
        record
        for record in records
        if record.filled_at is not None
    ]

    wins = [
        record
        for record in closed
        if float(record.realized_pnl) > 0
    ]

    pnl_values = [
        float(record.realized_pnl)
        for record in closed
    ]

    return_values = [
        float(record.return_pct)
        for record in closed
    ]

    by_symbol_records: dict[
        str,
        list[WebullPaperOrderRecord],
    ] = {}

    for record in records:
        by_symbol_records.setdefault(
            record.symbol,
            [],
        ).append(record)

    by_entry_time_records: dict[
        str,
        list[WebullPaperOrderRecord],
    ] = {}

    for record in entered:
        bucket = _entry_time_bucket(record)

        by_entry_time_records.setdefault(
            bucket,
            [],
        ).append(record)

    by_symbol = tuple(
        _group(
            key=symbol,
            records=group_records,
        )
        for symbol, group_records
        in sorted(
            by_symbol_records.items()
        )
    )

    by_entry_time = tuple(
        _group(
            key=bucket,
            records=group_records,
        )
        for bucket, group_records
        in sorted(
            by_entry_time_records.items()
        )
    )

    by_reward_risk = _group_records_by(
        records=records,
        bucket_fn=_reward_risk_bucket,
    )

    by_impulse_atr = _group_records_by(
        records=records,
        bucket_fn=_impulse_atr_bucket,
    )

    by_pullback_volume = _group_records_by(
        records=records,
        bucket_fn=_pullback_volume_bucket,
    )

    by_confirmation_time = _group_records_by(
        records=records,
        bucket_fn=_confirmation_time_bucket,
    )

    closed_count = len(closed)

    return WebullPaperAnalyticsReport(
        total_orders=len(records),
        entered_trades=len(entered),
        closed_trades=closed_count,
        open_trades=len(open_trades),
        no_entry=len(no_entry),
        realized_pnl=round(
            sum(pnl_values),
            6,
        ),
        win_rate_pct=(
            round(
                len(wins)
                / closed_count
                * 100.0,
                6,
            )
            if closed_count
            else None
        ),
        average_return_pct=_average(
            return_values
        ),
        expectancy_per_trade=_average(
            pnl_values
        ),
        by_symbol=by_symbol,
        by_entry_time=by_entry_time,
        by_reward_risk=by_reward_risk,
        by_impulse_atr=by_impulse_atr,
        by_pullback_volume=by_pullback_volume,
        by_confirmation_time=(
            by_confirmation_time
        ),
    )


def load_webull_paper_analytics(
    *,
    store: WebullPaperOrderStore | None = None,
) -> WebullPaperAnalyticsReport:
    store = store or WebullPaperOrderStore()

    return build_webull_paper_analytics(
        records=list(
            store.load().values()
        )
    )
