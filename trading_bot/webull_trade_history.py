from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from webull.trade.trade_client import TradeClient

from .config import (
    WEBULL_APP_KEY,
    WEBULL_APP_SECRET,
)
from .webull_sdk_security import (
    build_secure_webull_api_client,
)


EASTERN = ZoneInfo("America/New_York")


class WebullTradeHistoryError(RuntimeError):
    pass


@dataclass(frozen=True)
class WebullFill:
    symbol: str
    side: str
    quantity: float
    price: float
    filled_at: datetime

    @property
    def date(self) -> str:
        return self.filled_at.astimezone(
            EASTERN
        ).date().isoformat()


@dataclass(frozen=True)
class RealizedTrade:
    date: str
    symbol: str
    buy_time: datetime
    sell_time: datetime
    quantity: float
    buy_price: float
    sell_price: float
    gross_cost: float
    gross_proceeds: float
    realized_pnl: float
    return_pct: float


@dataclass(frozen=True)
class DailyTradeSummary:
    date: str
    closed_trades: int
    winning_trades: int
    losing_trades: int
    breakeven_trades: int
    gross_profit: float
    gross_loss: float
    realized_pnl: float
    win_rate_pct: float | None


def _filled_datetime(
    milliseconds: Any,
) -> datetime:
    try:
        value = float(milliseconds)
    except (TypeError, ValueError) as error:
        raise WebullTradeHistoryError(
            "Webull fill has invalid filled_time."
        ) from error

    return datetime.fromtimestamp(
        value / 1000.0,
        tz=EASTERN,
    )


def parse_webull_fills(
    payload: Any,
) -> list[WebullFill]:
    if not isinstance(payload, list):
        raise WebullTradeHistoryError(
            "Webull order history payload must be a list."
        )

    fills: list[WebullFill] = []

    for group in payload:
        if not isinstance(group, dict):
            continue

        orders = group.get("orders", [])

        if not isinstance(orders, list):
            continue

        for order in orders:
            if not isinstance(order, dict):
                continue

            if str(
                order.get("status", "")
            ).strip().upper() != "FILLED":
                continue

            side = str(
                order.get("side", "")
            ).strip().upper()

            if side not in {"BUY", "SELL"}:
                continue

            try:
                quantity = float(
                    order.get(
                        "filled_quantity",
                        0,
                    )
                )
                price = float(
                    order.get(
                        "filled_price",
                        0,
                    )
                )
            except (TypeError, ValueError):
                continue

            symbol = str(
                order.get("symbol", "")
            ).strip().upper()

            filled_time = order.get(
                "filled_time"
            )

            if (
                not symbol
                or quantity <= 0
                or price <= 0
                or filled_time in {None, ""}
            ):
                continue

            fills.append(
                WebullFill(
                    symbol=symbol,
                    side=side,
                    quantity=quantity,
                    price=price,
                    filled_at=_filled_datetime(
                        filled_time
                    ),
                )
            )

    fills.sort(
        key=lambda fill: fill.filled_at
    )

    return fills


def fills_for_date(
    fills: list[WebullFill],
    date_str: str,
) -> list[WebullFill]:
    return [
        fill
        for fill in fills
        if fill.date == date_str
    ]


def calculate_fifo_realized_trades(
    fills: list[WebullFill],
    date_str: str,
) -> tuple[
    list[RealizedTrade],
    dict[str, float],
]:
    """
    Match BUY inventory to SELL fills FIFO.

    Only long positions are supported. A SELL with no prior
    BUY inventory is ignored because this project does not
    support short selling.
    """
    dated_fills = fills_for_date(
        fills,
        date_str,
    )

    inventory: dict[
        str,
        deque[list[Any]],
    ] = defaultdict(deque)

    realized: list[RealizedTrade] = []

    for fill in dated_fills:
        if fill.side == "BUY":
            inventory[fill.symbol].append(
                [
                    fill.quantity,
                    fill.price,
                    fill.filled_at,
                ]
            )
            continue

        sell_remaining = fill.quantity

        while (
            sell_remaining > 0
            and inventory[fill.symbol]
        ):
            lot = inventory[
                fill.symbol
            ][0]

            buy_remaining = float(
                lot[0]
            )

            matched_quantity = min(
                sell_remaining,
                buy_remaining,
            )

            buy_price = float(
                lot[1]
            )
            buy_time = lot[2]

            gross_cost = (
                matched_quantity
                * buy_price
            )

            gross_proceeds = (
                matched_quantity
                * fill.price
            )

            pnl = (
                gross_proceeds
                - gross_cost
            )

            return_pct = (
                pnl / gross_cost * 100
                if gross_cost > 0
                else 0.0
            )

            realized.append(
                RealizedTrade(
                    date=date_str,
                    symbol=fill.symbol,
                    buy_time=buy_time,
                    sell_time=fill.filled_at,
                    quantity=matched_quantity,
                    buy_price=round(
                        buy_price,
                        4,
                    ),
                    sell_price=round(
                        fill.price,
                        4,
                    ),
                    gross_cost=round(
                        gross_cost,
                        2,
                    ),
                    gross_proceeds=round(
                        gross_proceeds,
                        2,
                    ),
                    realized_pnl=round(
                        pnl,
                        2,
                    ),
                    return_pct=round(
                        return_pct,
                        4,
                    ),
                )
            )

            buy_remaining -= (
                matched_quantity
            )

            sell_remaining -= (
                matched_quantity
            )

            if buy_remaining <= 0:
                inventory[
                    fill.symbol
                ].popleft()
            else:
                lot[0] = buy_remaining

    remaining = {
        symbol: round(
            sum(
                float(lot[0])
                for lot in lots
            ),
            6,
        )
        for symbol, lots in inventory.items()
        if lots
    }

    return realized, remaining


def summarize_realized_trades(
    trades: list[RealizedTrade],
    date_str: str,
) -> DailyTradeSummary:
    wins = [
        trade
        for trade in trades
        if trade.realized_pnl > 0
    ]

    losses = [
        trade
        for trade in trades
        if trade.realized_pnl < 0
    ]

    breakeven = [
        trade
        for trade in trades
        if trade.realized_pnl == 0
    ]

    closed_count = len(trades)

    gross_profit = round(
        sum(
            trade.realized_pnl
            for trade in wins
        ),
        2,
    )

    gross_loss = round(
        sum(
            trade.realized_pnl
            for trade in losses
        ),
        2,
    )

    realized_pnl = round(
        sum(
            trade.realized_pnl
            for trade in trades
        ),
        2,
    )

    win_rate = (
        round(
            len(wins)
            / closed_count
            * 100,
            2,
        )
        if closed_count
        else None
    )

    return DailyTradeSummary(
        date=date_str,
        closed_trades=closed_count,
        winning_trades=len(wins),
        losing_trades=len(losses),
        breakeven_trades=len(
            breakeven
        ),
        gross_profit=gross_profit,
        gross_loss=gross_loss,
        realized_pnl=realized_pnl,
        win_rate_pct=win_rate,
    )


class WebullTradeHistoryClient:
    """
    Read-only Webull trade-history adapter.

    This client exposes no place, cancel, replace, or preview
    order methods.
    """

    def __init__(
        self,
        trade_client: Any | None = None,
    ) -> None:
        if trade_client is not None:
            self._trade_client = trade_client
            return

        if not WEBULL_APP_KEY:
            raise WebullTradeHistoryError(
                "WEBULL_APP_KEY is not configured."
            )

        if not WEBULL_APP_SECRET:
            raise WebullTradeHistoryError(
                "WEBULL_APP_SECRET is not configured."
            )

        api_client = build_secure_webull_api_client(
            WEBULL_APP_KEY,
            WEBULL_APP_SECRET,
        )

        self._trade_client = (
            TradeClient(api_client)
        )

    def get_recent_fills(
        self,
    ) -> list[WebullFill]:
        account_response = (
            self._trade_client.account_v2
            .get_account_list()
        )

        if (
            getattr(
                account_response,
                "status_code",
                None,
            )
            != 200
        ):
            raise WebullTradeHistoryError(
                "Webull account lookup failed."
            )

        accounts = account_response.json()

        if (
            not isinstance(accounts, list)
            or not accounts
        ):
            raise WebullTradeHistoryError(
                "Webull returned no account."
            )

        account_id = accounts[0].get(
            "account_id"
        )

        if not account_id:
            raise WebullTradeHistoryError(
                "Webull account ID missing."
            )

        # Webull's current production endpoint rejected same-day
        # date parameters during validation, so request the SDK's
        # default recent-history window and filter locally.
        response = (
            self._trade_client.order_v3
            .get_order_history(
                account_id,
                page_size=100,
            )
        )

        if (
            getattr(
                response,
                "status_code",
                None,
            )
            != 200
        ):
            raise WebullTradeHistoryError(
                "Webull order history lookup failed."
            )

        return parse_webull_fills(
            response.json()
        )
