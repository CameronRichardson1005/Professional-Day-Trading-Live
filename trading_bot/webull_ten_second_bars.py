from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from typing import Any


EASTERN = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class WebullTradeTick:
    symbol: str
    timestamp_ms: int
    price: float
    volume: float
    trading_session: str = ""
    side: str = ""

    @property
    def timestamp(self) -> datetime:
        return datetime.fromtimestamp(
            self.timestamp_ms / 1000,
            tz=timezone.utc,
        ).astimezone(EASTERN)


@dataclass(frozen=True)
class TenSecondBar:
    symbol: str
    timestamp: datetime

    open: float
    high: float
    low: float
    close: float

    volume: float
    trades: int

    trading_session: str = ""


def _read_value(
    obj: Any,
    name: str,
    default=None,
):
    if isinstance(obj, dict):
        return obj.get(
            name,
            default,
        )

    return getattr(
        obj,
        name,
        default,
    )


def tick_from_webull_message(
    quote: Any,
) -> WebullTradeTick:
    """
    Convert a Webull streaming TICK message into
    our internal immutable trade-tick model.

    Accepts either:
    - SDK/protobuf-style quote objects
    - dictionaries used by tests/research tools
    """

    symbol = str(
        _read_value(
            quote,
            "symbol",
            "",
        )
    ).strip()

    timestamp_raw = _read_value(
        quote,
        "timestamp",
        None,
    )

    price_raw = _read_value(
        quote,
        "price",
        None,
    )

    volume_raw = _read_value(
        quote,
        "volume",
        0,
    )

    if not symbol:
        raise ValueError(
            "Webull tick is missing symbol."
        )

    if timestamp_raw in (
        None,
        "",
    ):
        raise ValueError(
            "Webull tick is missing timestamp."
        )

    if price_raw in (
        None,
        "",
    ):
        raise ValueError(
            "Webull tick is missing price."
        )

    timestamp_ms = int(
        timestamp_raw
    )

    price = float(
        price_raw
    )

    volume = float(
        volume_raw or 0
    )

    if timestamp_ms <= 0:
        raise ValueError(
            "Webull timestamp must be positive."
        )

    if price <= 0:
        raise ValueError(
            "Webull trade price must be positive."
        )

    if volume < 0:
        raise ValueError(
            "Webull trade volume cannot be negative."
        )

    return WebullTradeTick(
        symbol=symbol,
        timestamp_ms=timestamp_ms,
        price=price,
        volume=volume,
        trading_session=str(
            _read_value(
                quote,
                "trading_session",
                "",
            )
            or ""
        ),
        side=str(
            _read_value(
                quote,
                "side",
                "",
            )
            or ""
        ),
    )


def ten_second_bucket(
    timestamp: datetime,
) -> datetime:
    return timestamp.replace(
        second=(
            timestamp.second
            // 10
            * 10
        ),
        microsecond=0,
    )


class TenSecondBarAggregator:
    """
    Streaming trade -> completed 10-second OHLCV bars.

    A bar is finalized when the first trade from the
    following 10-second bucket arrives.

    Late trades belonging to an already-completed
    bucket are ignored so live strategy decisions
    are never rewritten after the fact.
    """

    def __init__(
        self,
    ) -> None:
        self._states: dict[
            str,
            dict[str, Any],
        ] = {}

    def add_tick(
        self,
        tick: WebullTradeTick,
    ) -> TenSecondBar | None:
        timestamp = tick.timestamp
        bucket = ten_second_bucket(
            timestamp
        )

        state = self._states.get(
            tick.symbol
        )

        if state is None:
            self._states[
                tick.symbol
            ] = self._new_state(
                tick=tick,
                bucket=bucket,
            )

            return None

        current_bucket = state[
            "bucket"
        ]

        if bucket < current_bucket:
            # Late print for an already closed/older
            # event-time bucket.
            return None

        if bucket == current_bucket:
            self._update_state(
                state=state,
                tick=tick,
            )

            return None

        completed = self._bar_from_state(
            symbol=tick.symbol,
            state=state,
        )

        self._states[
            tick.symbol
        ] = self._new_state(
            tick=tick,
            bucket=bucket,
        )

        return completed

    def flush(
        self,
        symbol: str,
    ) -> TenSecondBar | None:
        """
        Finalize the currently-open bar explicitly.

        Useful at shutdown or a strategy cutoff.
        """

        state = self._states.pop(
            symbol,
            None,
        )

        if state is None:
            return None

        return self._bar_from_state(
            symbol=symbol,
            state=state,
        )

    @staticmethod
    def _new_state(
        *,
        tick: WebullTradeTick,
        bucket: datetime,
    ) -> dict[str, Any]:
        return {
            "bucket": bucket,
            "open": tick.price,
            "high": tick.price,
            "low": tick.price,
            "close": tick.price,
            "volume": tick.volume,
            "trades": 1,
            "session": (
                tick.trading_session
            ),
        }

    @staticmethod
    def _update_state(
        *,
        state: dict[str, Any],
        tick: WebullTradeTick,
    ) -> None:
        state["high"] = max(
            state["high"],
            tick.price,
        )

        state["low"] = min(
            state["low"],
            tick.price,
        )

        state["close"] = (
            tick.price
        )

        state["volume"] += (
            tick.volume
        )

        state["trades"] += 1

    @staticmethod
    def _bar_from_state(
        *,
        symbol: str,
        state: dict[str, Any],
    ) -> TenSecondBar:
        return TenSecondBar(
            symbol=symbol,
            timestamp=state[
                "bucket"
            ],
            open=state[
                "open"
            ],
            high=state[
                "high"
            ],
            low=state[
                "low"
            ],
            close=state[
                "close"
            ],
            volume=state[
                "volume"
            ],
            trades=state[
                "trades"
            ],
            trading_session=state[
                "session"
            ],
        )
