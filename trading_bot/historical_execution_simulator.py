from __future__ import annotations

import json
import math
import os

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .webull_execution import WebullTradeIntent
from .webull_reduce_only_close import (
    WebullReduceOnlyCloseIntent,
)


class HistoricalExecutionError(RuntimeError):
    pass


ACTIVE_ORDER_STATUSES = {
    "SUBMITTED",
    "PARTIALLY_FILLED",
    "SUBMISSION_UNKNOWN",
}


@dataclass(frozen=True)
class HistoricalBar:
    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

    def __post_init__(self) -> None:
        symbol = self.symbol.strip().upper()

        if not symbol:
            raise HistoricalExecutionError(
                "BAR_SYMBOL_REQUIRED"
            )

        if self.timestamp.tzinfo is None:
            raise HistoricalExecutionError(
                "BAR_TIMESTAMP_MUST_BE_TIMEZONE_AWARE"
            )

        values = (
            float(self.open),
            float(self.high),
            float(self.low),
            float(self.close),
            float(self.volume),
        )

        if not all(
            math.isfinite(value)
            for value in values
        ):
            raise HistoricalExecutionError(
                "BAR_VALUE_NOT_FINITE"
            )

        if self.high < self.low:
            raise HistoricalExecutionError(
                "BAR_HIGH_BELOW_LOW"
            )

        if not (
            self.low
            <= self.open
            <= self.high
        ):
            raise HistoricalExecutionError(
                "BAR_OPEN_OUTSIDE_RANGE"
            )

        if not (
            self.low
            <= self.close
            <= self.high
        ):
            raise HistoricalExecutionError(
                "BAR_CLOSE_OUTSIDE_RANGE"
            )

        if self.volume < 0:
            raise HistoricalExecutionError(
                "BAR_VOLUME_NEGATIVE"
            )

        object.__setattr__(
            self,
            "symbol",
            symbol,
        )

        object.__setattr__(
            self,
            "timestamp",
            self.timestamp.astimezone(UTC),
        )


@dataclass
class HistoricalExecutionOrder:
    client_order_id: str
    strategy_name: str
    symbol: str
    side: str
    quantity: int
    limit_price: float
    created_at: datetime

    status: str = "SUBMITTED"

    filled_quantity: float = 0.0
    average_fill_price: float | None = None

    confirmed_position_quantity: float | None = None

    @property
    def remaining_quantity(self) -> float:
        return max(
            0.0,
            float(self.quantity)
            - float(self.filled_quantity),
        )

    @property
    def active(self) -> bool:
        return (
            self.status
            in ACTIVE_ORDER_STATUSES
        )


class HistoricalExecutionSimulator:
    """
    Deterministic historical broker/account simulator.

    It deliberately consumes the same two execution intent types
    used by the Webull execution layer:

      WebullTradeIntent
          BUY only

      WebullReduceOnlyCloseIntent
          SELL only against confirmed long inventory

    No network calls exist in this class.
    """

    VERSION = 1

    def __init__(
        self,
        *,
        starting_cash: float,
    ) -> None:
        cash = float(starting_cash)

        if (
            not math.isfinite(cash)
            or cash < 0
        ):
            raise HistoricalExecutionError(
                "INVALID_STARTING_CASH"
            )

        self.cash = cash

        self.holdings: dict[
            str,
            float,
        ] = {}

        self.orders: dict[
            str,
            HistoricalExecutionOrder,
        ] = {}

        self.assert_invariants()

    @property
    def reserved_buy_cash(self) -> float:
        total = 0.0

        for order in self.orders.values():
            if (
                order.active
                and order.side == "BUY"
            ):
                total += (
                    order.remaining_quantity
                    * order.limit_price
                )

        return total

    @property
    def available_cash(self) -> float:
        return (
            self.cash
            - self.reserved_buy_cash
        )

    def held_quantity(
        self,
        symbol: str,
    ) -> float:
        return float(
            self.holdings.get(
                symbol.strip().upper(),
                0.0,
            )
        )

    def reserved_sell_quantity(
        self,
        symbol: str,
    ) -> float:
        key = symbol.strip().upper()

        return sum(
            order.remaining_quantity
            for order
            in self.orders.values()
            if (
                order.active
                and order.side == "SELL"
                and order.symbol == key
            )
        )

    def available_to_close(
        self,
        symbol: str,
    ) -> float:
        key = symbol.strip().upper()

        return (
            self.held_quantity(key)
            - self.reserved_sell_quantity(
                key
            )
        )

    def _ensure_unique(
        self,
        client_order_id: str,
    ) -> None:
        key = client_order_id.strip()

        if not key:
            raise HistoricalExecutionError(
                "CLIENT_ORDER_ID_REQUIRED"
            )

        if key in self.orders:
            raise HistoricalExecutionError(
                "DUPLICATE_CLIENT_ORDER_ID"
            )

    def _store_order(
        self,
        order: HistoricalExecutionOrder,
    ) -> HistoricalExecutionOrder:
        self.orders[
            order.client_order_id
        ] = order

        self.assert_invariants()

        return order

    def place_buy(
        self,
        intent: WebullTradeIntent,
        *,
        ambiguous_after_accept: bool = False,
    ) -> HistoricalExecutionOrder:
        if intent.side != "BUY":
            raise HistoricalExecutionError(
                "HISTORICAL_BUY_MUST_BE_BUY"
            )

        self._ensure_unique(
            intent.client_order_id
        )

        required_cash = (
            float(intent.quantity)
            * float(intent.limit_price)
        )

        if (
            required_cash
            > self.available_cash
            + 0.000001
        ):
            raise HistoricalExecutionError(
                "INSUFFICIENT_AVAILABLE_CASH"
            )

        order = HistoricalExecutionOrder(
            client_order_id=(
                intent.client_order_id
            ),
            strategy_name=(
                intent.strategy_name
            ),
            symbol=intent.symbol,
            side="BUY",
            quantity=intent.quantity,
            limit_price=(
                float(intent.limit_price)
            ),
            created_at=(
                intent.created_at
                .astimezone(UTC)
            ),
            status=(
                "SUBMISSION_UNKNOWN"
                if ambiguous_after_accept
                else "SUBMITTED"
            ),
        )

        self._store_order(order)

        if ambiguous_after_accept:
            raise HistoricalExecutionError(
                "SUBMISSION_UNKNOWN"
            )

        return order

    def place_reduce_only_close(
        self,
        intent: WebullReduceOnlyCloseIntent,
        *,
        ambiguous_after_accept: bool = False,
    ) -> HistoricalExecutionOrder:
        if intent.side != "SELL":
            raise HistoricalExecutionError(
                "HISTORICAL_CLOSE_MUST_BE_SELL"
            )

        self._ensure_unique(
            intent.client_order_id
        )

        held = self.held_quantity(
            intent.symbol
        )

        if (
            abs(
                held
                - float(
                    intent.confirmed_position_quantity
                )
            )
            > 0.00001
        ):
            raise HistoricalExecutionError(
                "CONFIRMED_POSITION_CHANGED"
            )

        existing_sell = any(
            order.active
            and order.side == "SELL"
            and order.symbol == intent.symbol
            for order
            in self.orders.values()
        )

        if existing_sell:
            raise HistoricalExecutionError(
                "ACTIVE_CLOSE_ALREADY_EXISTS"
            )

        if (
            float(intent.quantity)
            > self.available_to_close(
                intent.symbol
            )
            + 0.00001
        ):
            raise HistoricalExecutionError(
                "CLOSE_QUANTITY_EXCEEDS_AVAILABLE_POSITION"
            )

        order = HistoricalExecutionOrder(
            client_order_id=(
                intent.client_order_id
            ),
            strategy_name=(
                intent.strategy_name
            ),
            symbol=intent.symbol,
            side="SELL",
            quantity=intent.quantity,
            limit_price=(
                float(intent.limit_price)
            ),
            created_at=(
                intent.created_at
                .astimezone(UTC)
            ),
            status=(
                "SUBMISSION_UNKNOWN"
                if ambiguous_after_accept
                else "SUBMITTED"
            ),
            confirmed_position_quantity=(
                float(
                    intent.confirmed_position_quantity
                )
            ),
        )

        self._store_order(order)

        if ambiguous_after_accept:
            raise HistoricalExecutionError(
                "SUBMISSION_UNKNOWN"
            )

        return order

    def resolve_submission(
        self,
        client_order_id: str,
        *,
        accepted: bool,
    ) -> HistoricalExecutionOrder:
        order = self.orders.get(
            client_order_id.strip()
        )

        if order is None:
            raise HistoricalExecutionError(
                "ORDER_NOT_FOUND"
            )

        if (
            order.status
            != "SUBMISSION_UNKNOWN"
        ):
            raise HistoricalExecutionError(
                "ORDER_NOT_SUBMISSION_UNKNOWN"
            )

        order.status = (
            "SUBMITTED"
            if accepted
            else "REJECTED"
        )

        self.assert_invariants()

        return order

    def cancel(
        self,
        client_order_id: str,
    ) -> HistoricalExecutionOrder:
        order = self.orders.get(
            client_order_id.strip()
        )

        if order is None:
            raise HistoricalExecutionError(
                "ORDER_NOT_FOUND"
            )

        if order.status in {
            "FILLED",
            "CANCELLED",
            "REJECTED",
        }:
            return order

        order.status = "CANCELLED"

        self.assert_invariants()

        return order

    @staticmethod
    def _can_fill(
        order: HistoricalExecutionOrder,
        bar: HistoricalBar,
    ) -> bool:
        if bar.timestamp < order.created_at:
            return False

        if bar.symbol != order.symbol:
            return False

        if order.side == "BUY":
            return (
                bar.low
                <= order.limit_price
            )

        if order.side == "SELL":
            return (
                bar.high
                >= order.limit_price
            )

        raise HistoricalExecutionError(
            "UNSUPPORTED_HISTORICAL_SIDE"
        )

    def _apply_fill(
        self,
        *,
        order: HistoricalExecutionOrder,
        quantity: float,
    ) -> None:
        quantity = float(quantity)

        if quantity <= 0:
            return

        if (
            quantity
            > order.remaining_quantity
            + 0.00001
        ):
            raise HistoricalExecutionError(
                "FILL_EXCEEDS_REMAINING_ORDER"
            )

        price = float(
            order.limit_price
        )

        previous_filled = float(
            order.filled_quantity
        )

        new_filled = (
            previous_filled
            + quantity
        )

        previous_value = (
            0.0
            if order.average_fill_price is None
            else (
                previous_filled
                * float(
                    order.average_fill_price
                )
            )
        )

        average = (
            previous_value
            + quantity * price
        ) / new_filled

        if order.side == "BUY":
            cost = quantity * price

            if cost > self.cash + 0.000001:
                raise HistoricalExecutionError(
                    "CASH_WOULD_GO_NEGATIVE"
                )

            self.cash -= cost

            self.holdings[
                order.symbol
            ] = (
                self.held_quantity(
                    order.symbol
                )
                + quantity
            )

        elif order.side == "SELL":
            held = self.held_quantity(
                order.symbol
            )

            if quantity > held + 0.00001:
                raise HistoricalExecutionError(
                    "POSITION_WOULD_GO_NEGATIVE"
                )

            self.holdings[
                order.symbol
            ] = (
                held
                - quantity
            )

            if (
                abs(
                    self.holdings[
                        order.symbol
                    ]
                )
                <= 0.00001
            ):
                self.holdings.pop(
                    order.symbol,
                    None,
                )

            self.cash += (
                quantity
                * price
            )

        else:
            raise HistoricalExecutionError(
                "UNSUPPORTED_HISTORICAL_SIDE"
            )

        order.filled_quantity = (
            new_filled
        )

        order.average_fill_price = (
            average
        )

        order.status = (
            "FILLED"
            if (
                order.remaining_quantity
                <= 0.00001
            )
            else "PARTIALLY_FILLED"
        )

        self.assert_invariants()

    def process_bar(
        self,
        bar: HistoricalBar,
        *,
        max_fill_quantity: (
            float | None
        ) = None,
    ) -> tuple[
        HistoricalExecutionOrder,
        ...
    ]:
        if max_fill_quantity is not None:
            max_fill_quantity = float(
                max_fill_quantity
            )

            if (
                not math.isfinite(
                    max_fill_quantity
                )
                or max_fill_quantity < 0
            ):
                raise HistoricalExecutionError(
                    "INVALID_MAX_FILL_QUANTITY"
                )

        changed = []

        candidates = sorted(
            (
                order
                for order
                in self.orders.values()
                if (
                    order.active
                    and order.status
                    != "SUBMISSION_UNKNOWN"
                )
            ),
            key=lambda order: (
                order.created_at,
                order.client_order_id,
            ),
        )

        for order in candidates:
            if not self._can_fill(
                order,
                bar,
            ):
                continue

            quantity = (
                order.remaining_quantity
            )

            if max_fill_quantity is not None:
                quantity = min(
                    quantity,
                    max_fill_quantity,
                )

            if quantity <= 0:
                continue

            self._apply_fill(
                order=order,
                quantity=quantity,
            )

            changed.append(order)

        self.assert_invariants()

        return tuple(changed)

    def assert_invariants(self) -> None:
        if (
            not math.isfinite(
                float(self.cash)
            )
            or self.cash < -0.00001
        ):
            raise HistoricalExecutionError(
                "INVARIANT_CASH_NEGATIVE"
            )

        for symbol, quantity in (
            self.holdings.items()
        ):
            if (
                not symbol
                or not math.isfinite(
                    float(quantity)
                )
                or quantity < -0.00001
            ):
                raise HistoricalExecutionError(
                    "INVARIANT_POSITION_NEGATIVE"
                )

        if self.available_cash < -0.00001:
            raise HistoricalExecutionError(
                "INVARIANT_BUY_RESERVATION_EXCEEDS_CASH"
            )

        symbols = set(
            self.holdings
        )

        symbols.update(
            order.symbol
            for order
            in self.orders.values()
        )

        for symbol in symbols:
            reserved = (
                self.reserved_sell_quantity(
                    symbol
                )
            )

            held = self.held_quantity(
                symbol
            )

            if reserved > held + 0.00001:
                raise HistoricalExecutionError(
                    "INVARIANT_SELL_RESERVATION_EXCEEDS_POSITION"
                )

            active_sells = [
                order
                for order
                in self.orders.values()
                if (
                    order.active
                    and order.side == "SELL"
                    and order.symbol == symbol
                )
            ]

            if len(active_sells) > 1:
                raise HistoricalExecutionError(
                    "INVARIANT_MULTIPLE_ACTIVE_CLOSES"
                )

    @staticmethod
    def _format_time(
        value: datetime,
    ) -> str:
        return (
            value.astimezone(UTC)
            .isoformat()
            .replace(
                "+00:00",
                "Z",
            )
        )

    @staticmethod
    def _parse_time(
        value: Any,
    ) -> datetime:
        timestamp = (
            datetime.fromisoformat(
                str(value).replace(
                    "Z",
                    "+00:00",
                )
            )
        )

        if timestamp.tzinfo is None:
            raise HistoricalExecutionError(
                "STATE_TIMESTAMP_NOT_AWARE"
            )

        return timestamp.astimezone(UTC)

    def state_dict(self) -> dict:
        return {
            "version": self.VERSION,
            "cash": self.cash,
            "holdings": dict(
                sorted(
                    self.holdings.items()
                )
            ),
            "orders": [
                {
                    **asdict(order),
                    "created_at": (
                        self._format_time(
                            order.created_at
                        )
                    ),
                }
                for order
                in sorted(
                    self.orders.values(),
                    key=lambda item: (
                        item.created_at,
                        item.client_order_id,
                    ),
                )
            ],
        }

    @classmethod
    def from_state(
        cls,
        payload: dict,
    ) -> HistoricalExecutionSimulator:
        if payload.get("version") != cls.VERSION:
            raise HistoricalExecutionError(
                "UNSUPPORTED_HISTORICAL_STATE_VERSION"
            )

        simulator = cls(
            starting_cash=float(
                payload["cash"]
            )
        )

        simulator.holdings = {
            str(symbol).strip().upper():
            float(quantity)
            for symbol, quantity
            in dict(
                payload.get(
                    "holdings",
                    {}
                )
            ).items()
        }

        simulator.orders = {}

        for raw in payload.get(
            "orders",
            [],
        ):
            order = HistoricalExecutionOrder(
                client_order_id=str(
                    raw["client_order_id"]
                ),
                strategy_name=str(
                    raw["strategy_name"]
                ),
                symbol=str(
                    raw["symbol"]
                ).upper(),
                side=str(
                    raw["side"]
                ).upper(),
                quantity=int(
                    raw["quantity"]
                ),
                limit_price=float(
                    raw["limit_price"]
                ),
                created_at=(
                    cls._parse_time(
                        raw["created_at"]
                    )
                ),
                status=str(
                    raw["status"]
                ).upper(),
                filled_quantity=float(
                    raw.get(
                        "filled_quantity",
                        0.0,
                    )
                ),
                average_fill_price=(
                    None
                    if raw.get(
                        "average_fill_price"
                    ) is None
                    else float(
                        raw[
                            "average_fill_price"
                        ]
                    )
                ),
                confirmed_position_quantity=(
                    None
                    if raw.get(
                        "confirmed_position_quantity"
                    ) is None
                    else float(
                        raw[
                            "confirmed_position_quantity"
                        ]
                    )
                ),
            )

            if (
                order.client_order_id
                in simulator.orders
            ):
                raise HistoricalExecutionError(
                    "DUPLICATE_CLIENT_ORDER_ID"
                )

            simulator.orders[
                order.client_order_id
            ] = order

        simulator.assert_invariants()

        return simulator

    def save_state(
        self,
        path: str | Path,
    ) -> None:
        output = Path(path)

        temp = output.with_suffix(
            output.suffix + ".tmp"
        )

        output.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        encoded = json.dumps(
            self.state_dict(),
            indent=2,
            sort_keys=True,
        ) + "\n"

        temp.write_text(
            encoded,
            encoding="utf-8",
        )

        os.chmod(
            temp,
            0o600,
        )

        os.replace(
            temp,
            output,
        )

        os.chmod(
            output,
            0o600,
        )

    @classmethod
    def load_state(
        cls,
        path: str | Path,
    ) -> HistoricalExecutionSimulator:
        payload = json.loads(
            Path(path).read_text(
                encoding="utf-8"
            )
        )

        return cls.from_state(
            payload
        )
