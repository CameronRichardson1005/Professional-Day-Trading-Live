from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

from .webull_ten_second_bars import (
    TenSecondBar,
    TenSecondBarAggregator,
    tick_from_webull_message,
)
from .webull_ten_second_recorder import (
    TenSecondBarRecorder,
)


class WebullTickRecorderService:
    """
    Read-only Webull market-data recorder.

    Flow:
        streaming TICK
        -> parse
        -> aggregate
        -> completed 10-second OHLCV
        -> local CSV

    No broker/order APIs are used.
    """

    def __init__(
        self,
        *,
        symbols: Iterable[str],
        app_key: str,
        app_secret: str,
        output_root: str | Path = (
            "data/webull_10s"
        ),
    ) -> None:
        self.symbols = tuple(
            dict.fromkeys(
                str(symbol)
                .strip()
                .upper()
                for symbol in symbols
                if str(symbol).strip()
            )
        )

        if not self.symbols:
            raise ValueError(
                "At least one symbol is required."
            )

        if not app_key:
            raise ValueError(
                "Webull app key is required."
            )

        if not app_secret:
            raise ValueError(
                "Webull app secret is required."
            )

        self.app_key = app_key
        self.app_secret = app_secret

        self.aggregator = (
            TenSecondBarAggregator()
        )

        self.recorder = (
            TenSecondBarRecorder(
                output_root
            )
        )

        self.completed_bars = 0
        self.tick_messages = 0
        self.invalid_ticks = 0

        self._client = None

    def process_tick(
        self,
        quote: Any,
    ) -> TenSecondBar | None:
        """
        Process one Webull tick message.

        This method is deliberately independent
        from the network client so it can be fully
        unit-tested.
        """
        try:
            tick = (
                tick_from_webull_message(
                    quote
                )
            )
        except (
            TypeError,
            ValueError,
        ):
            self.invalid_ticks += 1
            return None

        if (
            tick.symbol
            not in self.symbols
        ):
            return None

        self.tick_messages += 1

        completed = (
            self.aggregator.add_tick(
                tick
            )
        )

        if completed is not None:
            self.recorder.append_bar(
                completed
            )

            self.completed_bars += 1

        return completed

    def flush_all(
        self,
    ) -> list[TenSecondBar]:
        completed = []

        for symbol in self.symbols:
            bar = self.aggregator.flush(
                symbol
            )

            if bar is None:
                continue

            self.recorder.append_bar(
                bar
            )

            self.completed_bars += 1

            completed.append(
                bar
            )

        return completed

    def run_forever(
        self,
    ) -> None:
        """
        Connect to Webull's read-only streaming
        market-data service and record live ticks.
        """
        # The Webull SDK can print authenticated
        # request details when an exception occurs.
        # Keep SDK logging suppressed here.
        logging.getLogger(
            "webull"
        ).setLevel(
            logging.CRITICAL
        )

        from webull.data.common.category import (
            Category,
        )
        from webull.data.common.subscribe_type import (
            SubscribeType,
        )
        from webull.data.data_streaming_client import (
            DataStreamingClient,
        )

        session_id = (
            "ten_second_recorder_"
            + uuid.uuid4().hex[:8]
        )

        client = DataStreamingClient(
            self.app_key,
            self.app_secret,
            "us",
            session_id,
            http_host="api.webull.com",
            mqtt_host="data-api.webull.com",
        )

        self._client = client

        def on_connect(
            streaming_client,
            api_client,
            connected_session_id,
        ):
            print(
                "Webull market-data stream "
                f"connected: {connected_session_id}"
            )

            print(
                "Recording symbols: "
                + ", ".join(
                    self.symbols
                )
            )

            streaming_client.subscribe(
                list(
                    self.symbols
                ),
                Category.US_STOCK.name,
                [
                    SubscribeType.TICK.name,
                ],
            )

        def on_subscribe(
            streaming_client,
            api_client,
            connected_session_id,
        ):
            print(
                "Webull TICK subscription "
                "successful."
            )

            print(
                "10-second forward recorder "
                "is running."
            )

        def on_message(
            streaming_client,
            topic,
            quotes,
        ):
            if topic != "tick":
                return

            # SDK callbacks may supply one quote or
            # a collection depending on message type.
            if isinstance(
                quotes,
                (
                    list,
                    tuple,
                ),
            ):
                messages = quotes
            else:
                messages = [
                    quotes
                ]

            for quote in messages:
                bar = self.process_tick(
                    quote
                )

                if bar is None:
                    continue

                print(
                    f"{bar.timestamp.isoformat()} "
                    f"{bar.symbol:<6} "
                    f"O={bar.open:.4f} "
                    f"H={bar.high:.4f} "
                    f"L={bar.low:.4f} "
                    f"C={bar.close:.4f} "
                    f"V={bar.volume:.0f} "
                    f"T={bar.trades}"
                )

        client.on_connect_success = (
            on_connect
        )

        client.on_subscribe_success = (
            on_subscribe
        )

        client.on_quotes_message = (
            on_message
        )

        try:
            client.connect_and_loop_forever()

        except KeyboardInterrupt:
            print()
            print(
                "Stopping Webull "
                "10-second recorder..."
            )

        finally:
            flushed = self.flush_all()

            print(
                f"Ticks processed: "
                f"{self.tick_messages:,}"
            )

            print(
                f"Completed bars written: "
                f"{self.completed_bars:,}"
            )

            if self.invalid_ticks:
                print(
                    f"Invalid ticks skipped: "
                    f"{self.invalid_ticks:,}"
                )

            if flushed:
                print(
                    f"Open bars flushed: "
                    f"{len(flushed)}"
                )
