from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from trading_bot.bot import TradingBot
from trading_bot.models import Stock


EASTERN = ZoneInfo("America/New_York")


class FakeAlpaca:
    def __init__(self, five_minute_bars=None):
        self.opening_calls = 0
        self.atr_calls = 0
        self.five_minute_calls = []
        self.one_minute_calls = 0

        self.five_minute_bars = (
            five_minute_bars
            if five_minute_bars is not None
            else {"TEST": []}
        )

    def get_opening_15min_bars(
        self,
        **kwargs,
    ):
        self.opening_calls += 1

        return {
            "TEST": {
                "t": "2026-08-11T13:30:00Z",
                "o": 10.80,
                "h": 11.50,
                "l": 10.00,
                "c": 10.20,
                "v": 500000,
            }
        }

    def get_previous_day_ranges_all(
        self,
        **kwargs,
    ):
        self.atr_calls += 1

        return {
            "TEST": 1.00,
        }

    def get_historical_5min_bars(
        self,
        **kwargs,
    ):
        self.five_minute_calls.append(
            dict(kwargs)
        )

        return self.five_minute_bars

    def get_historical_1min_bars(
        self,
        **kwargs,
    ):
        self.one_minute_calls += 1

        raise AssertionError(
            "Quick Flip live must not request 1Min bars."
        )


class Clock:
    def __init__(self, values):
        self.values = list(values)
        self.index = 0

    def now(self):
        if self.index >= len(self.values):
            return self.values[-1]

        value = self.values[self.index]
        self.index += 1
        return value


def build_bot(
    *,
    alpaca=None,
    monitor=None,
):
    bot = object.__new__(TradingBot)

    bot.stocks = {
        "TEST": Stock(
            symbol="TEST"
        )
    }

    bot.symbols_csv = "TEST"

    bot.alpaca = (
        alpaca
        if alpaca is not None
        else FakeAlpaca()
    )

    bot.quick_flip_results = {}
    bot.quick_flip_status = {}

    if monitor is None:
        class FakeMonitor:
            def evaluate_five_minute_candles(
                self,
                **kwargs,
            ):
                return SimpleNamespace(
                    status="WATCHING",
                    signal=None,
                )

        monitor = FakeMonitor()

    bot.quick_flip_monitor = monitor

    return bot


def standard_clock():
    return Clock(
        [
            datetime(
                2026, 8, 11,
                9, 50,
                tzinfo=EASTERN,
            ),
            datetime(
                2026, 8, 11,
                9, 50,
                tzinfo=EASTERN,
            ),
            datetime(
                2026, 8, 11,
                11, 0,
                tzinfo=EASTERN,
            ),
        ]
    )


def test_live_monitor_fetches_static_inputs_once():
    bot = build_bot()
    clock = standard_clock()

    bot.run_quick_flip_monitor(
        date_str="2026-08-11",
        now_fn=clock.now,
        sleep_fn=lambda seconds: None,
        data_feed="iex",
    )

    assert bot.alpaca.opening_calls == 1
    assert bot.alpaca.atr_calls == 1


def test_live_monitor_uses_native_5min_bars():
    bot = build_bot()
    clock = standard_clock()

    bot.run_quick_flip_monitor(
        date_str="2026-08-11",
        now_fn=clock.now,
        sleep_fn=lambda seconds: None,
        data_feed="iex",
    )

    first = bot.alpaca.five_minute_calls[0]

    assert (
        first["start_iso"]
        == "2026-08-11T13:45:00Z"
    )

    assert (
        first["end_iso"]
        == "2026-08-11T13:50:00Z"
    )

    assert first["feed"] == "iex"

    assert bot.alpaca.one_minute_calls == 0


def test_live_monitor_does_not_use_1min_websocket():
    bot = build_bot()

    class ForbiddenStream:
        def __init__(self, *args, **kwargs):
            raise AssertionError(
                "1Min WebSocket must not be created."
            )

    clock = standard_clock()

    bot.run_quick_flip_monitor(
        date_str="2026-08-11",
        now_fn=clock.now,
        sleep_fn=lambda seconds: None,
        data_feed="iex",
        stream_factory=ForbiddenStream,
    )

    assert bot.alpaca.one_minute_calls == 0


def test_only_completed_native_5min_candles_are_evaluated():
    alpaca = FakeAlpaca(
        five_minute_bars={
            "TEST": [
                {
                    "t": "2026-08-11T13:45:00Z",
                    "o": 10.00,
                    "h": 10.30,
                    "l": 9.90,
                    "c": 10.20,
                    "v": 1000,
                },
                {
                    "t": "2026-08-11T13:50:00Z",
                    "o": 10.20,
                    "h": 10.40,
                    "l": 10.10,
                    "c": 10.30,
                    "v": 900,
                },
            ]
        }
    )

    captured = []

    class CaptureMonitor:
        def evaluate_five_minute_candles(
            self,
            *,
            candles,
            **kwargs,
        ):
            captured.append(
                list(candles)
            )

            return SimpleNamespace(
                status="WATCHING",
                signal=None,
            )

    bot = build_bot(
        alpaca=alpaca,
        monitor=CaptureMonitor(),
    )

    clock = Clock(
        [
            datetime(
                2026, 8, 11,
                9, 52,
                tzinfo=EASTERN,
            ),
            datetime(
                2026, 8, 11,
                9, 52,
                tzinfo=EASTERN,
            ),
            datetime(
                2026, 8, 11,
                11, 0,
                tzinfo=EASTERN,
            ),
        ]
    )

    bot.run_quick_flip_monitor(
        date_str="2026-08-11",
        now_fn=clock.now,
        sleep_fn=lambda seconds: None,
        data_feed="iex",
    )

    first_evaluation = captured[0]

    assert len(first_evaluation) == 1

    assert (
        first_evaluation[0].timestamp.isoformat()
        == "2026-08-11T13:45:00+00:00"
    )


def test_live_monitor_does_not_create_stop_fields():
    bot = build_bot()

    bot.stocks["TEST"].stop_loss = 8.88
    bot.stocks["TEST"].trading_stop_loss = 8.77

    clock = standard_clock()

    bot.run_quick_flip_monitor(
        date_str="2026-08-11",
        now_fn=clock.now,
        sleep_fn=lambda seconds: None,
        data_feed="iex",
    )

    stock = bot.stocks["TEST"]

    assert stock.stop_loss == 8.88
    assert stock.trading_stop_loss == 8.77


def test_live_monitor_stops_at_1100():
    bot = build_bot()

    bot.run_quick_flip_monitor(
        date_str="2026-08-11",
        now_fn=lambda: datetime(
            2026, 8, 11,
            11, 0,
            tzinfo=EASTERN,
        ),
        sleep_fn=lambda seconds: None,
        data_feed="iex",
    )

    assert bot.alpaca.opening_calls == 0
    assert bot.alpaca.atr_calls == 0
    assert bot.alpaca.five_minute_calls == []
    assert bot.alpaca.one_minute_calls == 0


def test_same_quick_flip_signal_is_previewed_once():
    signal = SimpleNamespace(
        signal="INVEST",
        pattern="HAMMER",
        entry_price=9.25,
        take_profit_1=10.0,
        take_profit_2=11.0,
        reversal_time="2026-08-11T13:50:00Z",
        confirmation_time="2026-08-11T13:55:00Z",
    )

    class FakeMonitor:
        def evaluate_five_minute_candles(
            self,
            **kwargs,
        ):
            return SimpleNamespace(
                status="CONFIRMED",
                signal=signal,
            )

    bot = build_bot(
        monitor=FakeMonitor()
    )

    class FakePreviewService:
        instances = []

        def __init__(self):
            self.calls = []
            self.__class__.instances.append(self)

        def prepare_previews(
            self,
            results,
        ):
            self.calls.append(
                list(results)
            )

            return [
                {
                    "status": "PREVIEW READY",
                    "submitted": False,
                    "symbol": "TEST",
                    "quantity": 10,
                    "limitBuy": 9.25,
                    "takeProfit1": 10.0,
                    "takeProfit2": 11.0,
                }
            ]

    clock = Clock(
        [
            datetime(
                2026, 8, 11,
                9, 50,
                tzinfo=EASTERN,
            ),
            datetime(
                2026, 8, 11,
                9, 50,
                tzinfo=EASTERN,
            ),
            datetime(
                2026, 8, 11,
                9, 55,
                tzinfo=EASTERN,
            ),
            datetime(
                2026, 8, 11,
                11, 0,
                tzinfo=EASTERN,
            ),
        ]
    )

    bot.run_quick_flip_monitor(
        date_str="2026-08-11",
        now_fn=clock.now,
        sleep_fn=lambda seconds: None,
        data_feed="iex",
        preview_service_factory=(
            FakePreviewService
        ),
    )

    service = FakePreviewService.instances[0]

    assert len(service.calls) == 1

    assert len(
        bot.quick_flip_webull_previews
    ) == 1

    assert (
        bot.quick_flip_webull_previews[0]
        ["submitted"]
        is False
    )


def test_quick_flip_preview_ready_sends_one_macos_notification(
    monkeypatch,
):
    signal = SimpleNamespace(
        signal="INVEST",
        pattern="HAMMER",
        entry_price=9.25,
        take_profit_1=10.0,
        take_profit_2=11.0,
        reversal_time="2026-08-11T13:50:00Z",
        confirmation_time="2026-08-11T13:55:00Z",
    )

    class FakeMonitor:
        def evaluate_five_minute_candles(
            self,
            **kwargs,
        ):
            return SimpleNamespace(
                status="CONFIRMED",
                signal=signal,
            )

    bot = build_bot(
        monitor=FakeMonitor()
    )

    class FakePreviewService:
        def prepare_previews(
            self,
            results,
        ):
            return [
                {
                    "status": "PREVIEW READY",
                    "submitted": False,
                    "symbol": "TEST",
                    "quantity": 10,
                    "limitBuy": 9.25,
                    "takeProfit1": 10.0,
                    "takeProfit2": 11.0,
                }
            ]

    calls = []

    def fake_run(*args, **kwargs):
        calls.append(
            (args, kwargs)
        )

        return SimpleNamespace(
            returncode=0
        )

    monkeypatch.setattr(
        "trading_bot.bot.subprocess.run",
        fake_run,
    )

    clock = standard_clock()

    bot.run_quick_flip_monitor(
        date_str="2026-08-11",
        now_fn=clock.now,
        sleep_fn=lambda seconds: None,
        data_feed="iex",
        preview_service_factory=(
            FakePreviewService
        ),
    )

    assert len(calls) == 1

    command = calls[0][0][0]

    assert command[0] == "osascript"
    assert "TEST" in command[-1]
    assert "9.2500" in command[-1]
    assert "10.0000" in command[-1]
    assert "11.0000" in command[-1]
