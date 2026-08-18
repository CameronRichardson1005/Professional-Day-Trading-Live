from types import SimpleNamespace
import sys

import pytest

import main as main_module


class FakeSupervisor:
    def __init__(self):
        self.alive = False

    def is_alive(self):
        return self.alive


class FakeRuntime:
    def __init__(
        self,
        *,
        trusted=True,
        polls=3,
        start_error=None,
        stop_error=None,
        keep_alive_after_stop=False,
    ):
        self.supervisor = FakeSupervisor()
        self.trusted = trusted
        self.polls = polls
        self.start_error = start_error
        self.stop_error = stop_error
        self.keep_alive_after_stop = (
            keep_alive_after_stop
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
            self.stop_calls = 0

            instances.append(self)

        def start(self):
            self.start_calls += 1
            self.runtime.supervisor.alive = True

            if self.runtime.start_error is not None:
                raise self.runtime.start_error

            return SimpleNamespace(
                trusted=self.runtime.trusted,
                polls=self.runtime.polls,
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

    return builder_calls, instances


def run_command(
    monkeypatch,
    *extra_args,
):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "main.py",
            "webull-sandbox-trade-events-check",
            *extra_args,
        ],
    )

    return main_module.main()


def test_connectivity_cli_success_is_one_shot(
    monkeypatch,
    capsys,
):
    runtime = FakeRuntime(
        trusted=True,
        polls=4,
    )

    builder_calls, instances = (
        install_common(
            monkeypatch,
            runtime,
        )
    )

    result = run_command(
        monkeypatch
    )

    output = capsys.readouterr().out

    assert result == 0

    assert builder_calls == [True]
    assert len(instances) == 1

    lifecycle = instances[0]

    assert lifecycle.start_calls == 1
    assert lifecycle.stop_calls == 1

    assert runtime.supervisor.alive is False

    assert (
        "WEBULL SANDBOX TRADE EVENTS "
        "CHECK PASSED"
        in output
    )

    assert "Connected: True" in output
    assert "Reconciled: True" in output
    assert "Trusted: True" in output
    assert "Startup polls: 4" in output
    assert "Worker stopped: True" in output

    assert (
        "NO WEBULL ORDER WAS PLACED, "
        "MODIFIED, OR CANCELLED"
        in output
    )

    assert (
        "webull-sandbox-trade-events-check"
        in main_module.AVAILABLE_MODES
    )


def test_connectivity_cli_rejects_extra_arguments(
    monkeypatch,
    capsys,
):
    runtime = FakeRuntime()

    builder_calls, instances = (
        install_common(
            monkeypatch,
            runtime,
        )
    )

    result = run_command(
        monkeypatch,
        "unexpected",
    )

    output = capsys.readouterr().out

    assert result == 2
    assert builder_calls == []
    assert instances == []

    assert (
        "Usage: python main.py "
        "webull-sandbox-trade-events-check"
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
def test_connectivity_cli_requires_all_safety_guards(
    monkeypatch,
    capsys,
    submission,
    management,
    kill_switch,
):
    runtime = FakeRuntime()

    builder_calls, instances = (
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

    result = run_command(
        monkeypatch
    )

    output = capsys.readouterr().out

    assert result == 1
    assert builder_calls == []
    assert instances == []

    assert "CHECK REFUSED" in output

    assert (
        "sandbox submission=false"
        in output
    )

    assert (
        "sandbox management=false"
        in output
    )

    assert (
        "live kill switch=true"
        in output
    )


def test_connectivity_cli_startup_failure_still_stops(
    monkeypatch,
    capsys,
):
    runtime = FakeRuntime(
        start_error=RuntimeError(
            "TRADE_EVENTS_CONNECT_FAILED"
        )
    )

    builder_calls, instances = (
        install_common(
            monkeypatch,
            runtime,
        )
    )

    result = run_command(
        monkeypatch
    )

    output = capsys.readouterr().out

    assert result == 1
    assert builder_calls == [True]

    lifecycle = instances[0]

    assert lifecycle.start_calls == 1
    assert lifecycle.stop_calls == 1

    assert runtime.supervisor.alive is False

    assert "CHECK FAILED" in output

    assert (
        "TRADE_EVENTS_CONNECT_FAILED"
        in output
    )


def test_connectivity_cli_untrusted_result_fails_closed(
    monkeypatch,
    capsys,
):
    runtime = FakeRuntime(
        trusted=False,
    )

    _, instances = install_common(
        monkeypatch,
        runtime,
    )

    result = run_command(
        monkeypatch
    )

    output = capsys.readouterr().out

    assert result == 1

    assert (
        instances[0].stop_calls
        == 1
    )

    assert runtime.supervisor.alive is False

    assert (
        "TRADE_EVENTS_NOT_TRUSTED"
        in output
    )


def test_connectivity_cli_shutdown_failure_is_failure(
    monkeypatch,
    capsys,
):
    runtime = FakeRuntime(
        stop_error=RuntimeError(
            "TRADE_EVENTS_STOP_FAILED"
        )
    )

    _, instances = install_common(
        monkeypatch,
        runtime,
    )

    result = run_command(
        monkeypatch
    )

    output = capsys.readouterr().out

    assert result == 1

    assert (
        instances[0].stop_calls
        == 1
    )

    assert "CHECK FAILED" in output

    assert (
        "TRADE_EVENTS_STOP_FAILED"
        in output
    )


def test_connectivity_cli_rejects_worker_left_alive(
    monkeypatch,
    capsys,
):
    runtime = FakeRuntime(
        keep_alive_after_stop=True,
    )

    _, instances = install_common(
        monkeypatch,
        runtime,
    )

    result = run_command(
        monkeypatch
    )

    output = capsys.readouterr().out

    assert result == 1

    assert (
        instances[0].stop_calls
        == 1
    )

    assert runtime.supervisor.alive is True

    assert (
        "TRADE_EVENTS_WORKER_STILL_RUNNING"
        in output
    )
