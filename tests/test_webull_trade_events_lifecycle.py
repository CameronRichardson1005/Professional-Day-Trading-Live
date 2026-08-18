from types import SimpleNamespace

import pytest

from trading_bot.webull_trade_events_lifecycle import (
    WebullTradeEventsLifecycle,
    WebullTradeEventsLifecycleError,
)


class FakeHealth:
    def __init__(self):
        self.trusted = False
        self.fatal_reason = None
        self.lost_reasons = []

    def mark_worker_lost(
        self,
        reason,
    ):
        self.trusted = False
        self.fatal_reason = reason
        self.lost_reasons.append(
            reason
        )


class FakeSupervisor:
    def __init__(
        self,
        *,
        start_error=None,
        stop_error=None,
    ):
        self.alive = False
        self.start_error = start_error
        self.stop_error = stop_error
        self.start_calls = 0
        self.stop_calls = 0

    def is_alive(self):
        return self.alive

    def start(self):
        self.start_calls += 1

        if self.start_error:
            raise self.start_error

        self.alive = True

    def stop(self):
        self.stop_calls += 1

        if self.stop_error:
            raise self.stop_error

        was_alive = self.alive
        self.alive = False

        return was_alive


class FakeController:
    def __init__(
        self,
        *,
        health,
        actions,
    ):
        self.health = health
        self.actions = list(
            actions
        )
        self.poll_calls = 0

    def poll_once(self):
        self.poll_calls += 1

        if not self.actions:
            return SimpleNamespace(
                trusted=False
            )

        action = self.actions.pop(
            0
        )

        if isinstance(
            action,
            BaseException,
        ):
            raise action

        if isinstance(
            action,
            tuple,
        ):
            trusted, fatal_reason = (
                action
            )

            self.health.trusted = bool(
                trusted
            )
            self.health.fatal_reason = (
                fatal_reason
            )

            return SimpleNamespace(
                trusted=trusted
            )

        self.health.trusted = bool(
            action
        )

        return SimpleNamespace(
            trusted=bool(action)
        )


def make_runtime(
    *,
    actions,
    start_error=None,
    stop_error=None,
):
    health = FakeHealth()

    supervisor = FakeSupervisor(
        start_error=start_error,
        stop_error=stop_error,
    )

    controller = FakeController(
        health=health,
        actions=actions,
    )

    return SimpleNamespace(
        health=health,
        supervisor=supervisor,
        controller=controller,
    )


def test_construction_does_not_start_worker():
    runtime = make_runtime(
        actions=[True],
    )

    WebullTradeEventsLifecycle(
        runtime=runtime
    )

    assert (
        runtime.supervisor.start_calls
        == 0
    )

    assert (
        runtime.supervisor.stop_calls
        == 0
    )


def test_start_waits_until_trusted():
    runtime = make_runtime(
        actions=[
            False,
            True,
        ],
    )

    sleeps = []

    lifecycle = (
        WebullTradeEventsLifecycle(
            runtime=runtime,
            startup_timeout_seconds=10,
            poll_interval_seconds=0.25,
            monotonic=lambda: 0.0,
            sleeper=lambda seconds: (
                sleeps.append(seconds)
            ),
        )
    )

    result = lifecycle.start()

    assert result.trusted is True
    assert result.polls == 2

    assert (
        runtime.supervisor.start_calls
        == 1
    )

    assert (
        runtime.supervisor.stop_calls
        == 0
    )

    assert sleeps == [0.25]


def test_start_timeout_stops_and_revokes_trust():
    runtime = make_runtime(
        actions=[
            False,
            False,
        ],
    )

    times = iter([
        0.0,
        0.5,
        1.1,
    ])

    lifecycle = (
        WebullTradeEventsLifecycle(
            runtime=runtime,
            startup_timeout_seconds=1.0,
            poll_interval_seconds=0.1,
            monotonic=lambda: next(times),
            sleeper=lambda seconds: None,
        )
    )

    with pytest.raises(
        WebullTradeEventsLifecycleError,
        match=(
            "TRADE_EVENTS_STARTUP_TIMEOUT"
        ),
    ):
        lifecycle.start()

    assert (
        runtime.supervisor.stop_calls
        == 1
    )

    assert (
        runtime.health.fatal_reason
        == "TRADE_EVENTS_STARTUP_TIMEOUT"
    )

    assert runtime.health.trusted is False


def test_startup_controller_failure_stops_worker():
    runtime = make_runtime(
        actions=[
            RuntimeError(
                "reconciliation failed"
            ),
        ],
    )

    lifecycle = (
        WebullTradeEventsLifecycle(
            runtime=runtime,
            monotonic=lambda: 0.0,
            sleeper=lambda seconds: None,
        )
    )

    with pytest.raises(
        WebullTradeEventsLifecycleError,
        match=(
            "TRADE_EVENTS_STARTUP_FAILED"
        ),
    ):
        lifecycle.start()

    assert (
        runtime.supervisor.stop_calls
        == 1
    )

    assert (
        runtime.health.fatal_reason
        == "TRADE_EVENTS_STARTUP_FAILED"
    )


def test_fatal_health_during_startup_stops_immediately():
    runtime = make_runtime(
        actions=[
            (
                False,
                "TRADE_EVENTS_STREAM_FAILED",
            ),
        ],
    )

    lifecycle = (
        WebullTradeEventsLifecycle(
            runtime=runtime,
            monotonic=lambda: 0.0,
            sleeper=lambda seconds: None,
        )
    )

    with pytest.raises(
        WebullTradeEventsLifecycleError,
        match=(
            "TRADE_EVENTS_STARTUP_FATAL:"
            "TRADE_EVENTS_STREAM_FAILED"
        ),
    ):
        lifecycle.start()

    assert (
        runtime.supervisor.stop_calls
        == 1
    )

    assert (
        runtime.health.fatal_reason
        == "TRADE_EVENTS_STREAM_FAILED"
    )


def test_worker_start_failure_is_fail_closed():
    runtime = make_runtime(
        actions=[],
        start_error=RuntimeError(
            "cannot spawn"
        ),
    )

    lifecycle = (
        WebullTradeEventsLifecycle(
            runtime=runtime
        )
    )

    with pytest.raises(
        WebullTradeEventsLifecycleError,
        match=(
            "TRADE_EVENTS_WORKER_START_FAILED"
        ),
    ):
        lifecycle.start()

    assert runtime.health.trusted is False

    assert (
        runtime.health.fatal_reason
        == "TRADE_EVENTS_WORKER_START_FAILED"
    )


def test_runtime_poll_failure_stops_worker():
    runtime = make_runtime(
        actions=[
            RuntimeError(
                "queue failed"
            ),
        ],
    )

    runtime.supervisor.alive = True
    runtime.health.trusted = True

    lifecycle = (
        WebullTradeEventsLifecycle(
            runtime=runtime
        )
    )

    with pytest.raises(
        WebullTradeEventsLifecycleError,
        match=(
            "TRADE_EVENTS_RUNTIME_FAILED"
        ),
    ):
        lifecycle.poll_once()

    assert (
        runtime.supervisor.stop_calls
        == 1
    )

    assert runtime.health.trusted is False

    assert (
        runtime.health.fatal_reason
        == "TRADE_EVENTS_RUNTIME_FAILED"
    )


def test_stop_always_revokes_trust():
    runtime = make_runtime(
        actions=[],
    )

    runtime.supervisor.alive = True
    runtime.health.trusted = True

    lifecycle = (
        WebullTradeEventsLifecycle(
            runtime=runtime
        )
    )

    stopped = lifecycle.stop()

    assert stopped is True

    assert (
        runtime.supervisor.stop_calls
        == 1
    )

    assert runtime.health.trusted is False

    assert (
        runtime.health.fatal_reason
        == "TRADE_EVENTS_STOPPED"
    )


def test_invalid_timing_fails_before_worker_activity():
    runtime = make_runtime(
        actions=[],
    )

    with pytest.raises(
        WebullTradeEventsLifecycleError,
        match=(
            "TRADE_EVENTS_LIFECYCLE_TIMING_INVALID"
        ),
    ):
        WebullTradeEventsLifecycle(
            runtime=runtime,
            startup_timeout_seconds=0,
        )

    assert (
        runtime.supervisor.start_calls
        == 0
    )
