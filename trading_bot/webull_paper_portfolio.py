from __future__ import annotations

import math
import os

from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from .webull_paper_order_store import (
    WebullPaperOrderRecord,
    WebullPaperOrderStore,
)


DEFAULT_PAPER_STARTING_CASH = 10_000.0


class WebullPaperPortfolioError(RuntimeError):
    pass


@dataclass(frozen=True)
class WebullPaperOpenPosition:
    paper_order_id: str
    symbol: str
    quantity: int
    fill_price: float
    cost_basis: float
    mark_price: float
    mark_status: str
    market_value: float
    unrealized_pnl: float
    unrealized_return_pct: float
    filled_at: datetime
    target_price: float | None
    stop_price: float | None


@dataclass(frozen=True)
class WebullPaperClosedPosition:
    paper_order_id: str
    symbol: str
    quantity: int
    fill_price: float
    exit_price: float
    realized_pnl: float
    return_pct: float
    exit_reason: str
    filled_at: datetime
    closed_at: datetime


@dataclass(frozen=True)
class WebullPaperPortfolio:
    starting_cash: float
    cash: float
    buying_power: float

    open_cost_basis: float
    market_value: float

    realized_pnl: float
    unrealized_pnl: float
    total_pnl: float
    equity: float

    open_position_count: int
    closed_position_count: int
    pending_order_count: int
    no_entry_count: int

    overdrawn: bool

    open_positions: tuple[
        WebullPaperOpenPosition,
        ...
    ]
    closed_positions: tuple[
        WebullPaperClosedPosition,
        ...
    ]

    def to_dict(self) -> dict:
        return asdict(self)


def configured_paper_starting_cash() -> float:
    raw = os.getenv(
        "WEBULL_PAPER_STARTING_CASH",
        str(DEFAULT_PAPER_STARTING_CASH),
    )

    try:
        value = float(raw)
    except (TypeError, ValueError) as error:
        raise WebullPaperPortfolioError(
            "INVALID_PAPER_STARTING_CASH"
        ) from error

    if not math.isfinite(value) or value <= 0:
        raise WebullPaperPortfolioError(
            "INVALID_PAPER_STARTING_CASH"
        )

    return round(value, 2)


def _valid_mark(
    value,
) -> float | None:
    if not isinstance(value, (int, float)):
        return None

    converted = float(value)

    if not math.isfinite(converted):
        return None

    if converted <= 0:
        return None

    return converted


def build_webull_paper_portfolio(
    *,
    records: list[WebullPaperOrderRecord],
    latest_prices: dict[str, float] | None = None,
    starting_cash: float = DEFAULT_PAPER_STARTING_CASH,
) -> WebullPaperPortfolio:
    """
    Reconstruct the LOCAL PAPER account from the durable
    paper-order ledger.

    The ledger remains the source of truth. No broker account,
    margin balance, buying power, or Webull order endpoint is
    accessed by this calculation.
    """
    starting_cash = float(starting_cash)

    if (
        not math.isfinite(starting_cash)
        or starting_cash <= 0
    ):
        raise WebullPaperPortfolioError(
            "INVALID_PAPER_STARTING_CASH"
        )

    latest_prices = {
        str(symbol).strip().upper(): value
        for symbol, value in (
            latest_prices or {}
        ).items()
    }

    open_positions = []
    closed_positions = []

    pending_order_count = 0
    no_entry_count = 0

    for record in sorted(
        records,
        key=lambda item: (
            item.submitted_at,
            item.paper_order_id,
        ),
    ):
        if record.lifecycle_status == "ENTRY PENDING":
            pending_order_count += 1
            continue

        if (
            record.lifecycle_status == "CLOSED"
            and record.filled_at is None
        ):
            if record.exit_reason == "NO ENTRY":
                no_entry_count += 1
            continue

        if (
            record.filled_at is None
            or record.fill_price is None
        ):
            # A malformed lifecycle record should already be
            # rejected by WebullPaperOrderStore validation. This
            # guard keeps portfolio reconstruction fail-closed.
            raise WebullPaperPortfolioError(
                "FILLED_ORDER_MISSING_FILL_DATA"
            )

        fill_price = float(record.fill_price)
        cost_basis = round(
            fill_price * record.quantity,
            6,
        )

        if record.lifecycle_status == "OPEN":
            mark = _valid_mark(
                latest_prices.get(record.symbol)
            )

            if mark is None:
                # Reconstructing after restart is always possible
                # even before new market data arrives. In that
                # case valuation explicitly falls back to cost.
                mark = fill_price
                mark_status = "FILL FALLBACK"
            else:
                mark_status = "MARKED"

            market_value = round(
                mark * record.quantity,
                6,
            )

            unrealized_pnl = round(
                market_value - cost_basis,
                6,
            )

            unrealized_return_pct = round(
                (
                    unrealized_pnl
                    / cost_basis
                    * 100.0
                ),
                6,
            )

            open_positions.append(
                WebullPaperOpenPosition(
                    paper_order_id=(
                        record.paper_order_id
                    ),
                    symbol=record.symbol,
                    quantity=record.quantity,
                    fill_price=fill_price,
                    cost_basis=cost_basis,
                    mark_price=round(mark, 6),
                    mark_status=mark_status,
                    market_value=market_value,
                    unrealized_pnl=unrealized_pnl,
                    unrealized_return_pct=(
                        unrealized_return_pct
                    ),
                    filled_at=record.filled_at,
                    target_price=record.target_price,
                    stop_price=record.stop_price,
                )
            )

            continue

        if record.lifecycle_status != "CLOSED":
            raise WebullPaperPortfolioError(
                "UNSUPPORTED_LIFECYCLE_STATUS"
            )

        if (
            record.closed_at is None
            or record.exit_price is None
            or record.realized_pnl is None
            or record.return_pct is None
        ):
            raise WebullPaperPortfolioError(
                "CLOSED_ORDER_MISSING_EXIT_DATA"
            )

        closed_positions.append(
            WebullPaperClosedPosition(
                paper_order_id=record.paper_order_id,
                symbol=record.symbol,
                quantity=record.quantity,
                fill_price=fill_price,
                exit_price=float(
                    record.exit_price
                ),
                realized_pnl=float(
                    record.realized_pnl
                ),
                return_pct=float(
                    record.return_pct
                ),
                exit_reason=record.exit_reason,
                filled_at=record.filled_at,
                closed_at=record.closed_at,
            )
        )

    realized_pnl = round(
        sum(
            position.realized_pnl
            for position in closed_positions
        ),
        6,
    )

    open_cost_basis = round(
        sum(
            position.cost_basis
            for position in open_positions
        ),
        6,
    )

    market_value = round(
        sum(
            position.market_value
            for position in open_positions
        ),
        6,
    )

    unrealized_pnl = round(
        sum(
            position.unrealized_pnl
            for position in open_positions
        ),
        6,
    )

    # Closed trades return their capital to cash. Therefore the
    # durable net cash equation only needs realized P&L plus
    # capital currently committed to OPEN positions.
    cash = round(
        starting_cash
        + realized_pnl
        - open_cost_basis,
        6,
    )

    equity = round(
        cash + market_value,
        6,
    )

    total_pnl = round(
        realized_pnl + unrealized_pnl,
        6,
    )

    return WebullPaperPortfolio(
        starting_cash=round(
            starting_cash,
            2,
        ),
        cash=cash,
        buying_power=round(
            max(cash, 0.0),
            6,
        ),
        open_cost_basis=open_cost_basis,
        market_value=market_value,
        realized_pnl=realized_pnl,
        unrealized_pnl=unrealized_pnl,
        total_pnl=total_pnl,
        equity=equity,
        open_position_count=len(
            open_positions
        ),
        closed_position_count=len(
            closed_positions
        ),
        pending_order_count=(
            pending_order_count
        ),
        no_entry_count=no_entry_count,
        overdrawn=cash < 0,
        open_positions=tuple(
            open_positions
        ),
        closed_positions=tuple(
            closed_positions
        ),
    )


def load_webull_paper_portfolio(
    *,
    latest_prices: dict[str, float] | None = None,
    starting_cash: float | None = None,
    store: WebullPaperOrderStore | None = None,
) -> WebullPaperPortfolio:
    store = store or WebullPaperOrderStore()

    if starting_cash is None:
        starting_cash = (
            configured_paper_starting_cash()
        )

    return build_webull_paper_portfolio(
        records=list(
            store.load().values()
        ),
        latest_prices=latest_prices,
        starting_cash=starting_cash,
    )


def latest_prices_from_completed_bars(
    bars_by_symbol: dict[str, list[dict]],
) -> dict[str, float]:
    """
    Return the latest valid completed-bar close for each symbol.

    This function performs no market-data request. It only reads
    bars already supplied by the live strategy workflow.
    """
    latest: dict[str, tuple[datetime, float]] = {}

    for raw_symbol, bars in bars_by_symbol.items():
        symbol = str(raw_symbol).strip().upper()

        if not symbol:
            continue

        for bar in bars:
            try:
                timestamp = datetime.fromisoformat(
                    str(bar["t"]).replace(
                        "Z",
                        "+00:00",
                    )
                )
                close = float(bar["c"])
            except (
                KeyError,
                TypeError,
                ValueError,
            ) as error:
                raise WebullPaperPortfolioError(
                    "INVALID_PORTFOLIO_MARK_BAR"
                ) from error

            if timestamp.tzinfo is None:
                raise WebullPaperPortfolioError(
                    "PORTFOLIO_MARK_TIMESTAMP_"
                    "MUST_BE_TIMEZONE_AWARE"
                )

            if (
                not math.isfinite(close)
                or close <= 0
            ):
                raise WebullPaperPortfolioError(
                    "INVALID_PORTFOLIO_MARK_PRICE"
                )

            timestamp = timestamp.astimezone(UTC)

            existing = latest.get(symbol)

            if (
                existing is None
                or timestamp > existing[0]
            ):
                latest[symbol] = (
                    timestamp,
                    close,
                )

    return {
        symbol: round(value[1], 6)
        for symbol, value in latest.items()
    }
