from types import SimpleNamespace

import pytest

from trading_bot.webull_sandbox_persistent_runtime import (
    WebullSandboxPersistentRuntime,
    WebullSandboxPersistentRuntimeError,
)


class FakeSupervisor:
    def __init__(self):
        self.alive = False

    def is_alive(self):
        return self.alive


class FakeHealth:
    def __init__(
        self,
        fatal_reason=None,
    ):
        self.fatal_reason = (
            fatal_reason
        )


class FakeRuntime:
    def __init__(
        self,
        *,
        fatal_reason=None,
    ):
        self.supervisor = (
            FakeSupervisor()
        )
        self.controller = (
            SimpleNamespace()
        )
        self.health = (
            FakeHealth(
                fatal_reason=fatal_reason
            )
        )


class FakeLifecycle:
    def __init__(
        self,
        *,
        runtime,
        startup_trusted=True,
        poll_results=None,
        poll_error=None,
        interrupt=False,
        stop_error=None,
    ):
        self.runtime = runtime
        self.startup_trusted = (
            startup_trusted
        )
        self.poll_results = list(
            poll_results or []
        )
        self.poll_error = poll_error
        self.interrupt = interrupt
        self.stop_error = stop_error

        self.start_calls = 0
        self.poll_calls = 0
        self.stop_calls = 0

    def start(self):
        self.start_calls += 1
        self.runtime.supervisor.alive = (
            True
        )

        return SimpleNamespace(
            trusted=(
                self.startup_trusted
            ),
            polls=7,
        )

    def poll_once(self):
        self.poll_calls += 1

        if self.interrupt:
            raise KeyboardInterrupt

        if self.poll_error is not None:
            raise self.poll_error

        if self.poll_results:
            return self.poll_results.pop(
                0
            )

        return SimpleNamespace(
            trusted=True
        )

    def stop(self):
        self.stop_calls += 1

        if self.stop_error is not None:
            raise self.stop_error

        self.runtime.supervisor.alive = (
            False
        )

        return True


def build_service(
    *,
    runtime=None,
    lifecycle=None,
    sleeps=None,
):
    if runtime is None:
        runtime = FakeRuntime()

    if lifecycle is None:
        lifecycle = FakeLifecycle(
            runtime=runtime
        )

    if sleeps is None:
        sleeps = []

    def lifecycle_factory(
        *,
        runtime,
    ):
        assert runtime is lifecycle.runtime
        return lifecycle

    service = (
        WebullSandboxPersistentRuntime(
            runtime=runtime,
            lifecycle_factory=(
                lifecycle_factory
            ),
            poll_interval_seconds=0.25,
            sleeper=sleeps.append,
        )
    )

    return (
        service,
        runtime,
        lifecycle,
        sleeps,
    )


def test_construction_does_not_start_lifecycle():
    (
        service,
        runtime,
        lifecycle,
        sleeps,
    ) = build_service()

    assert service is not None
    assert lifecycle.start_calls == 0
    assert lifecycle.poll_calls == 0
    assert lifecycle.stop_calls == 0
    assert runtime.supervisor.alive is False
    assert sleeps == []


def test_bounded_run_starts_polls_and_stops():
    (
        service,
        runtime,
        lifecycle,
        sleeps,
    ) = build_service()

    report = service.run(
        max_polls=3
    )

    assert report.trusted is True
    assert report.startup_polls == 7
    assert report.runtime_polls == 3
    assert report.interrupted is False
    assert report.worker_stopped is True

    assert lifecycle.start_calls == 1
    assert lifecycle.poll_calls == 3
    assert lifecycle.stop_calls == 1
    assert runtime.supervisor.alive is False

    assert sleeps == [
        0.25,
        0.25,
    ]


def test_zero_poll_run_still_starts_and_stops():
    (
        service,
        runtime,
        lifecycle,
        sleeps,
    ) = build_service()

    report = service.run(
        max_polls=0
    )

    assert report.runtime_polls == 0
    assert report.worker_stopped is True
    assert lifecycle.start_calls == 1
    assert lifecycle.poll_calls == 0
    assert lifecycle.stop_calls == 1
    assert sleeps == []


def test_untrusted_startup_fails_closed():
    runtime = FakeRuntime()

    lifecycle = FakeLifecycle(
        runtime=runtime,
        startup_trusted=False,
    )

    service, _, _, _ = (
        build_service(
            runtime=runtime,
            lifecycle=lifecycle,
        )
    )

    with pytest.raises(
        WebullSandboxPersistentRuntimeError,
        match=(
            "^SANDBOX_RUNTIME_STARTUP_UNTRUSTED$"
        ),
    ):
        service.run(
            max_polls=1
        )

    assert lifecycle.stop_calls == 1
    assert runtime.supervisor.alive is False


def test_runtime_trust_loss_fails_closed():
    runtime = FakeRuntime(
        fatal_reason="STREAM_LOST"
    )

    lifecycle = FakeLifecycle(
        runtime=runtime,
        poll_results=[
            SimpleNamespace(
                trusted=False
            )
        ],
    )

    service, _, _, _ = (
        build_service(
            runtime=runtime,
            lifecycle=lifecycle,
        )
    )

    with pytest.raises(
        WebullSandboxPersistentRuntimeError,
        match=(
            "^SANDBOX_RUNTIME_UNTRUSTED:"
            "STREAM_LOST$"
        ),
    ):
        service.run(
            max_polls=1
        )

    assert lifecycle.stop_calls == 1
    assert runtime.supervisor.alive is False


def test_poll_exception_is_sanitized_and_stops():
    runtime = FakeRuntime()

    lifecycle = FakeLifecycle(
        runtime=runtime,
        poll_error=RuntimeError(
            "secret SDK detail"
        ),
    )

    service, _, _, _ = (
        build_service(
            runtime=runtime,
            lifecycle=lifecycle,
        )
    )

    with pytest.raises(
        WebullSandboxPersistentRuntimeError,
        match=(
            "^SANDBOX_RUNTIME_FAILED$"
        ),
    ) as captured:
        service.run(
            max_polls=1
        )

    assert (
        "secret SDK detail"
        not in str(
            captured.value
        )
    )

    assert lifecycle.stop_calls == 1
    assert runtime.supervisor.alive is False


def test_keyboard_interrupt_is_clean_shutdown():
    runtime = FakeRuntime()

    lifecycle = FakeLifecycle(
        runtime=runtime,
        interrupt=True,
    )

    service, _, _, _ = (
        build_service(
            runtime=runtime,
            lifecycle=lifecycle,
        )
    )

    report = service.run()

    assert report.trusted is True
    assert report.interrupted is True
    assert report.runtime_polls == 0
    assert report.worker_stopped is True

    assert lifecycle.stop_calls == 1
    assert runtime.supervisor.alive is False


def test_shutdown_failure_is_reported():
    runtime = FakeRuntime()

    lifecycle = FakeLifecycle(
        runtime=runtime,
        stop_error=RuntimeError(
            "shutdown detail"
        ),
    )

    service, _, _, _ = (
        build_service(
            runtime=runtime,
            lifecycle=lifecycle,
        )
    )

    with pytest.raises(
        WebullSandboxPersistentRuntimeError,
        match=(
            "^SANDBOX_RUNTIME_SHUTDOWN_FAILED$"
        ),
    ):
        service.run(
            max_polls=1
        )


@pytest.mark.parametrize(
    "value",
    [
        -1,
        1.5,
        True,
        "5",
    ],
)
def test_invalid_max_polls_rejected(
    value,
):
    service, _, _, _ = (
        build_service()
    )

    with pytest.raises(
        WebullSandboxPersistentRuntimeError,
        match=(
            "^SANDBOX_RUNTIME_MAX_POLLS_INVALID$"
        ),
    ):
        service.run(
            max_polls=value
        )
