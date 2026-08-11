import json
from datetime import UTC, datetime
from threading import Event, Lock
from typing import Any, Callable

from websockets.sync.client import connect

from .config import API_KEY, API_SECRET


class AlpacaStockStream:
    """
    Collect Alpaca stock minute bars from the real-time WebSocket.

    The collector stores one latest bar per symbol and timestamp.
    An updated bar replaces the earlier version of that same minute.

    Snapshot reads are thread-safe so the Quick Flip monitor can
    inspect bars while collect_until() continues on a background
    thread.
    """

    VALID_FEEDS = {"iex", "sip"}

    def __init__(
        self,
        symbols: list[str],
        feed: str = "iex",
        connect_fn: Callable[..., Any] = connect,
    ) -> None:
        feed = feed.strip().lower()

        if feed not in self.VALID_FEEDS:
            raise ValueError(
                "WebSocket feed must be 'iex' or 'sip'."
            )

        cleaned_symbols = [
            symbol.strip().upper()
            for symbol in symbols
            if symbol.strip()
        ]

        if not cleaned_symbols:
            raise ValueError(
                "At least one WebSocket symbol is required."
            )

        self.symbols = list(
            dict.fromkeys(cleaned_symbols)
        )

        self.feed = feed
        self.connect_fn = connect_fn

        self.url = (
            "wss://stream.data.alpaca.markets/"
            f"v2/{self.feed}"
        )

        self.bars: dict[
            str,
            dict[str, dict[str, Any]],
        ] = {
            symbol: {}
            for symbol in self.symbols
        }

        # collect_until() may run in a background thread while
        # Quick Flip reads snapshots from the monitoring thread.
        self._bars_lock = Lock()

    @staticmethod
    def _normalise_timestamp(
        value: Any,
    ) -> str:
        return str(value or "")

    def process_message(
        self,
        message: dict[str, Any],
    ) -> bool:
        """
        Process one Alpaca stream message.

        Returns True when a bar or updated bar was accepted.
        """
        message_type = str(
            message.get("T", "")
        )

        if message_type not in {"b", "u"}:
            return False

        symbol = str(
            message.get("S", "")
        ).upper()

        timestamp = self._normalise_timestamp(
            message.get("t")
        )

        if (
            symbol not in self.bars
            or not timestamp
        ):
            return False

        required_fields = (
            "o",
            "h",
            "l",
            "c",
        )

        if not all(
            isinstance(
                message.get(field),
                (int, float),
            )
            for field in required_fields
        ):
            return False

        bar = {
            key: value
            for key, value
            in message.items()
            if key not in {"T", "S"}
        }

        # Preserve the same structure used elsewhere.
        bar["t"] = timestamp

        with self._bars_lock:
            self.bars[
                symbol
            ][timestamp] = bar

        return True

    def bars_for_symbol(
        self,
        symbol: str,
    ) -> list[dict[str, Any]]:
        symbol = symbol.strip().upper()

        with self._bars_lock:
            bars = {
                timestamp: dict(bar)
                for timestamp, bar
                in self.bars.get(
                    symbol,
                    {},
                ).items()
            }

        return [
            bars[timestamp]
            for timestamp in sorted(bars)
        ]

    def snapshot(
        self,
    ) -> dict[str, list[dict[str, Any]]]:
        """
        Return an independent chronological copy of all bars.

        Mutating the returned snapshot cannot alter the live
        stream collector's internal state.
        """
        with self._bars_lock:
            snapshot = {
                symbol: {
                    timestamp: dict(bar)
                    for timestamp, bar
                    in self.bars.get(
                        symbol,
                        {},
                    ).items()
                }
                for symbol in self.symbols
            }

        return {
            symbol: [
                bars[timestamp]
                for timestamp in sorted(bars)
            ]
            for symbol, bars
            in snapshot.items()
        }

    def collect_until(
        self,
        stop_time: datetime,
        stop_event: Event | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        """
        Connect, authenticate, subscribe, and collect bars
        until stop_time.

        stop_time must be a naive UTC datetime, matching
        the existing live tracker convention.
        """
        external_stop = (
            stop_event or Event()
        )

        with self.connect_fn(
            self.url,
            open_timeout=10,
            ping_interval=20,
            ping_timeout=20,
            close_timeout=5,
        ) as websocket:
            connected = json.loads(
                websocket.recv()
            )

            if not any(
                item.get("T") == "success"
                and item.get("msg")
                == "connected"
                for item in connected
            ):
                raise RuntimeError(
                    "Alpaca WebSocket did not "
                    "confirm connection."
                )

            websocket.send(
                json.dumps(
                    {
                        "action": "auth",
                        "key": API_KEY,
                        "secret": API_SECRET,
                    }
                )
            )

            authenticated = json.loads(
                websocket.recv()
            )

            if not any(
                item.get("T") == "success"
                and item.get("msg")
                == "authenticated"
                for item in authenticated
            ):
                raise RuntimeError(
                    "Alpaca WebSocket "
                    "authentication failed."
                )

            websocket.send(
                json.dumps(
                    {
                        "action": "subscribe",
                        "bars": self.symbols,
                        "updatedBars": self.symbols,
                    }
                )
            )

            while (
                datetime.now(UTC)
                .replace(tzinfo=None)
                < stop_time
                and not external_stop.is_set()
            ):
                try:
                    raw_message = websocket.recv(
                        timeout=1
                    )
                except TimeoutError:
                    continue

                messages = json.loads(
                    raw_message
                )

                if not isinstance(
                    messages,
                    list,
                ):
                    continue

                for message in messages:
                    if isinstance(
                        message,
                        dict,
                    ):
                        self.process_message(
                            message
                        )

        return self.snapshot()
