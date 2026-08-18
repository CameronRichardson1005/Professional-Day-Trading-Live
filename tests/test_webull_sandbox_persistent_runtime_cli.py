from types import SimpleNamespace
import sys

import main as main_module


def run_cli(
    monkeypatch,
    capsys,
    *arguments,
):
    monkeypatch.setattr(
        main_module,
        "setup_logging",
        lambda: "test.log",
    )

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "main.py",
            *arguments,
        ],
    )

    status = main_module.main()

    output = (
        capsys
        .readouterr()
        .out
    )

    return status, output


def install_safe_state(
    monkeypatch,
):
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


def forbidden_builder():
    raise AssertionError(
        "Trade Events runtime must not be built."
    )


def test_runtime_usage_rejects_extra_argument(
    monkeypatch,
    capsys,
):
    install_safe_state(
        monkeypatch
    )

    monkeypatch.setattr(
        main_module,
        "build_webull_sandbox_trade_events_runtime",
        forbidden_builder,
    )

    status, output = run_cli(
        monkeypatch,
        capsys,
        "webull-sandbox-runtime",
        "unexpected",
    )

    assert status == 2

    assert (
        "Usage: python main.py "
        "webull-sandbox-runtime"
        in output
    )


def test_runtime_refuses_when_submission_enabled(
    monkeypatch,
    capsys,
):
    install_safe_state(
        monkeypatch
    )

    monkeypatch.setattr(
        main_module,
        "WEBULL_SANDBOX_ORDER_SUBMISSION_ENABLED",
        True,
    )

    monkeypatch.setattr(
        main_module,
        "build_webull_sandbox_trade_events_runtime",
        forbidden_builder,
    )

    status, output = run_cli(
        monkeypatch,
        capsys,
        "webull-sandbox-runtime",
    )

    assert status == 1
    assert (
        "WEBULL SANDBOX RUNTIME REFUSED"
        in output
    )

    assert (
        "sandbox submission=false"
        in output
    )


def test_runtime_refuses_when_management_enabled(
    monkeypatch,
    capsys,
):
    install_safe_state(
        monkeypatch
    )

    monkeypatch.setattr(
        main_module,
        "WEBULL_SANDBOX_ORDER_MANAGEMENT_ENABLED",
        True,
    )

    monkeypatch.setattr(
        main_module,
        "build_webull_sandbox_trade_events_runtime",
        forbidden_builder,
    )

    status, output = run_cli(
        monkeypatch,
        capsys,
        "webull-sandbox-runtime",
    )

    assert status == 1
    assert (
        "WEBULL SANDBOX RUNTIME REFUSED"
        in output
    )


def test_runtime_refuses_when_live_kill_switch_off(
    monkeypatch,
    capsys,
):
    install_safe_state(
        monkeypatch
    )

    monkeypatch.setattr(
        main_module,
        "WEBULL_TRADING_KILL_SWITCH",
        False,
    )

    monkeypatch.setattr(
        main_module,
        "build_webull_sandbox_trade_events_runtime",
        forbidden_builder,
    )

    status, output = run_cli(
        monkeypatch,
        capsys,
        "webull-sandbox-runtime",
    )

    assert status == 1
    assert (
        "WEBULL SANDBOX RUNTIME REFUSED"
        in output
    )

    assert (
        "live kill switch=true"
        in output
    )


def test_runtime_builds_and_runs_persistent_supervisor(
    monkeypatch,
    capsys,
):
    install_safe_state(
        monkeypatch
    )

    sentinel_runtime = object()

    builder_calls = []

    def build_runtime():
        builder_calls.append(
            True
        )

        return sentinel_runtime

    persistent_instances = []

    class FakePersistentRuntime:
        def __init__(
            self,
            *,
            runtime,
        ):
            assert (
                runtime
                is sentinel_runtime
            )

            self.run_calls = 0

            persistent_instances.append(
                self
            )

        def run(self):
            self.run_calls += 1

            return SimpleNamespace(
                trusted=True,
                startup_polls=5,
                runtime_polls=42,
                interrupted=True,
                worker_stopped=True,
            )

    monkeypatch.setattr(
        main_module,
        "build_webull_sandbox_trade_events_runtime",
        build_runtime,
    )

    monkeypatch.setattr(
        main_module,
        "WebullSandboxPersistentRuntime",
        FakePersistentRuntime,
    )

    status, output = run_cli(
        monkeypatch,
        capsys,
        "webull-sandbox-runtime",
    )

    assert status == 0

    assert builder_calls == [
        True
    ]

    assert len(
        persistent_instances
    ) == 1

    assert (
        persistent_instances[0]
        .run_calls
        == 1
    )

    assert (
        "WEBULL SANDBOX RUNTIME STOPPED"
        in output
    )

    assert (
        "Trusted startup: True"
        in output
    )

    assert (
        "Runtime polls: 42"
        in output
    )

    assert (
        "Interrupted: True"
        in output
    )

    assert (
        "Worker stopped: True"
        in output
    )


def test_runtime_failure_returns_nonzero_and_is_disarmed(
    monkeypatch,
    capsys,
):
    install_safe_state(
        monkeypatch
    )

    sentinel_runtime = object()

    monkeypatch.setattr(
        main_module,
        "build_webull_sandbox_trade_events_runtime",
        lambda: sentinel_runtime,
    )

    class FailingPersistentRuntime:
        def __init__(
            self,
            *,
            runtime,
        ):
            assert (
                runtime
                is sentinel_runtime
            )

        def run(self):
            raise RuntimeError(
                "SANDBOX_RUNTIME_FAILED"
            )

    monkeypatch.setattr(
        main_module,
        "WebullSandboxPersistentRuntime",
        FailingPersistentRuntime,
    )

    status, output = run_cli(
        monkeypatch,
        capsys,
        "webull-sandbox-runtime",
    )

    assert status == 1

    assert (
        "WEBULL SANDBOX RUNTIME FAILED"
        in output
    )

    assert (
        "Reason: SANDBOX_RUNTIME_FAILED"
        in output
    )

    assert (
        "EXECUTION-DISARMED"
        in output
    )
