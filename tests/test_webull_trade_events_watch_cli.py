from types import SimpleNamespace
import sys

import pytest

import main as main_module


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def sleep(
        self,
        seconds,
    ):
        self.now += float(seconds)


class FakeJournal:
    def __init__(
        self,
        *,
        initial=0,
        final=0,
    ):
        self.counts = [
            initial,
            final,
        ]

    def event_count(self):
        if len(self.counts) > 1:
            return self.counts.pop(0)

        return self.counts[0]


class FakeSupervisor:
    def __init__(self):
        self.alive = False

    def is_alive(self):
        return self.alive


class FakeHealth:
    def __init__(self):
        self.fatal_reason = None


class FakeRuntime:
    def __init__(
        self,
        *,
        initial_events=0,
        final_events=0,
        start_error=None,
        stop_error=None,
        keep_alive_after_stop=False,
        trust_sequence=None,
    ):
        self.journal = FakeJournal(
            initial=initial_events,
            final=final_events,
        )

        self.supervisor = FakeSupervisor()
        self.health = FakeHealth()

        self.start_error = start_error
        self.stop_error = stop_error

        self.keep_alive_after_stop = (
            keep_alive_after_stop
        )

        self.trust_sequence = list(
            trust_sequence
            if trust_sequence is not None
            else [True]
        )


def install_common(
    monkeypatch,
    runtime,
):
    monkeypatch.setattr(
        main_module,
        "setup_logging",
        lambda: "test.log",
    )

    class ForbiddenTradingBot:
        def __init__(self):
            raise AssertionError(
                "TradingBot must not be constructed."
            )

    monkeypatch.setattr(
        main_module,
        "TradingBot",
        ForbiddenTradingBot,
    )

    monkeypatch.setattr(
        main_module,
        "WEBULL_SANDBOX_ORDER_SUBMISSION_ENABLED",
        False,
    )

    monkeypatch.setattr(
        main_module,
        "WEBULL_SANDBOX_ORDER_MANAGEMENT_ENABLED",
        False,
    )

    monkeypatch.setattr(
        main_module,
        "WEBULL_TRADING_KILL_SWITCH",
        True,
    )

    builder_calls = []

    def builder():
        builder_calls.append(True)
        return runtime

    monkeypatch.setattr(
        main_module,
        "build_webull_sandbox_trade_events_runtime",
        builder,
    )

    instances = []

    class FakeLifecycle:
        def __init__(
            self,
            *,
            runtime,
        ):
            self.runtime = runtime
            self.start_calls = 0
            self.poll_calls = 0
            self.stop_calls = 0

            instances.append(self)

        def start(self):
            self.start_calls += 1
            self.runtime.supervisor.alive = True

            if self.runtime.start_error is not None:
                raise self.runtime.start_error

            return SimpleNamespace(
                trusted=True,
                polls=3,
            )

        def poll_once(self):
            self.poll_calls += 1

            if (
                len(self.runtime.trust_sequence)
                > 1
            ):
                trusted = (
                    self.runtime.trust_sequence.pop(0)
                )
            else:
                trusted = (
                    self.runtime.trust_sequence[0]
                )

            return SimpleNamespace(
                trusted=trusted,
            )

        def stop(self):
            self.stop_calls += 1

            if self.runtime.stop_error is not None:
                raise self.runtime.stop_error

            if not self.runtime.keep_alive_after_stop:
                self.runtime.supervisor.alive = False

            return True

    monkeypatch.setattr(
        main_module,
        "WebullTradeEventsLifecycle",
        FakeLifecycle,
    )

    clock = FakeClock()

    monkeypatch.setattr(
        main_module.time,
        "monotonic",
        clock.monotonic,
    )

    monkeypatch.setattr(
        main_module.time,
        "sleep",
        clock.sleep,
    )

    return (
        builder_calls,
        instances,
        clock,
    )


def run_command(
    monkeypatch,
    *extra_args,
):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "main.py",
            "webull-sandbox-trade-events-watch",
            *extra_args,
        ],
    )

    return main_module.main()


def test_watch_cli_success_reports_event_delta(
    monkeypatch,
    capsys,
):
    runtime = FakeRuntime(
        initial_events=5,
        final_events=7,
    )

    builder_calls, instances, _ = (
        install_common(
            monkeypatch,
            runtime,
        )
    )

    result = run_command(
        monkeypatch,
        "1",
    )

    output = capsys.readouterr().out

    assert result == 0
    assert builder_calls == [True]
    assert len(instances) == 1

    lifecycle = instances[0]

    assert lifecycle.start_calls == 1
    assert lifecycle.poll_calls > 0
    assert lifecycle.stop_calls == 1

    assert runtime.supervisor.alive is False

    assert (
        "WEBULL SANDBOX TRADE EVENTS "
        "WATCH COMPLETE"
        in output
    )

    assert "Connected: True" in output
    assert "Reconciled: True" in output

    assert (
        "Trusted during watch: True"
        in output
    )

    assert "Watch seconds: 1.0" in output

    assert (
        "New journaled events: 2"
        in output
    )

    assert (
        "Total journaled events: 7"
        in output
    )

    assert "Worker stopped: True" in output

    assert (
        "webull-sandbox-trade-events-watch"
        in main_module.AVAILABLE_MODES
    )


def test_watch_cli_defaults_to_thirty_seconds(
    monkeypatch,
    capsys,
):
    runtime = FakeRuntime()

    install_common(
        monkeypatch,
        runtime,
    )

    assert (
        run_command(
            monkeypatch
        )
        == 0
    )

    output = capsys.readouterr().out

    assert (
        "Watch seconds: 30.0"
        in output
    )


@pytest.mark.parametrize(
    "argument",
    [
        "not-a-number",
        "0",
        "301",
    ],
)
def test_watch_cli_rejects_invalid_duration(
    monkeypatch,
    capsys,
    argument,
):
    runtime = FakeRuntime()

    builder_calls, instances, _ = (
        install_common(
            monkeypatch,
            runtime,
        )
    )

    assert (
        run_command(
            monkeypatch,
            argument,
        )
        == 2
    )

    assert builder_calls == []
    assert instances == []

    output = capsys.readouterr().out

    assert (
        "Watch seconds"
        in output
    )


@pytest.mark.parametrize(
    (
        "submission",
        "management",
        "kill_switch",
    ),
    [
        (
            True,
            False,
            True,
        ),
        (
            False,
            True,
            True,
        ),
        (
            False,
            False,
            False,
        ),
    ],
)
def test_watch_cli_requires_all_safety_guards(
    monkeypatch,
    capsys,
    submission,
    management,
    kill_switch,
):
    runtime = FakeRuntime()

    builder_calls, instances, _ = (
        install_common(
            monkeypatch,
            runtime,
        )
    )

    monkeypatch.setattr(
        main_module,
        "WEBULL_SANDBOX_ORDER_SUBMISSION_ENABLED",
        submission,
    )

    monkeypatch.setattr(
        main_module,
        "WEBULL_SANDBOX_ORDER_MANAGEMENT_ENABLED",
        management,
    )

    monkeypatch.setattr(
        main_module,
        "WEBULL_TRADING_KILL_SWITCH",
        kill_switch,
    )

    assert (
        run_command(
            monkeypatch,
            "1",
        )
        == 1
    )

    assert builder_calls == []
    assert instances == []

    output = capsys.readouterr().out

    assert "WATCH REFUSED" in output


def test_watch_cli_trust_loss_fails_closed_and_stops(
    monkeypatch,
    capsys,
):
    runtime = FakeRuntime(
        trust_sequence=[
            True,
            False,
        ],
    )

    _, instances, _ = (
        install_common(
            monkeypatch,
            runtime,
        )
    )

    runtime.health.fatal_reason = (
        "TRADE_EVENTS_STREAM_FAILED"
    )

    assert (
        run_command(
            monkeypatch,
            "1",
        )
        == 1
    )

    lifecycle = instances[0]

    assert lifecycle.stop_calls == 1
    assert runtime.supervisor.alive is False

    output = capsys.readouterr().out

    assert "WATCH FAILED" in output

    assert (
        "TRADE_EVENTS_WATCH_UNTRUSTED:"
        "TRADE_EVENTS_STREAM_FAILED"
        in output
    )


def test_watch_cli_startup_failure_still_stops(
    monkeypatch,
    capsys,
):
    runtime = FakeRuntime(
        start_error=RuntimeError(
            "TRADE_EVENTS_STARTUP_FAILED"
        )
    )

    _, instances, _ = (
        install_common(
            monkeypatch,
            runtime,
        )
    )

    assert (
        run_command(
            monkeypatch,
            "1",
        )
        == 1
    )

    lifecycle = instances[0]

    assert lifecycle.start_calls == 1
    assert lifecycle.stop_calls == 1
    assert runtime.supervisor.alive is False

    output = capsys.readouterr().out

    assert (
        "TRADE_EVENTS_STARTUP_FAILED"
        in output
    )


def test_watch_cli_shutdown_failure_is_failure(
    monkeypatch,
    capsys,
):
    runtime = FakeRuntime(
        stop_error=RuntimeError(
            "TRADE_EVENTS_STOP_FAILED"
        )
    )

    _, instances, _ = (
        install_common(
            monkeypatch,
            runtime,
        )
    )

    assert (
        run_command(
            monkeypatch,
            "1",
        )
        == 1
    )

    assert (
        instances[0].stop_calls
        == 1
    )

    output = capsys.readouterr().out

    assert "WATCH FAILED" in output

    assert (
        "TRADE_EVENTS_STOP_FAILED"
        in output
    )


def test_watch_cli_rejects_worker_left_alive(
    monkeypatch,
    capsys,
):
    runtime = FakeRuntime(
        keep_alive_after_stop=True,
    )

    _, instances, _ = (
        install_common(
            monkeypatch,
            runtime,
        )
    )

    assert (
        run_command(
            monkeypatch,
            "1",
        )
        == 1
    )

    assert (
        instances[0].stop_calls
        == 1
    )

    output = capsys.readouterr().out

    assert (
        "TRADE_EVENTS_WORKER_STILL_RUNNING"
        in output
    )
