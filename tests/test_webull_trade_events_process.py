import pytest

import trading_bot.webull_trade_events_process as module

from trading_bot.webull_trade_events_process import (
    WebullTradeEventsProcessError,
    WebullTradeEventsProcessSupervisor,
)


def worker_target():
    return None


class FakeProcess:
    def __init__(
        self,
        *,
        target,
        args,
        name,
        daemon,
    ):
        self.target = target
        self.args = args
        self.name = name
        self.daemon = daemon

        self.start_calls = 0
        self.terminate_calls = 0
        self.kill_calls = 0
        self.join_calls = []

        self._alive = False

        self.survive_terminate = False
        self.survive_kill = False

        self.exitcode = None

    def start(self):
        self.start_calls += 1
        self._alive = True

    def is_alive(self):
        return self._alive

    def terminate(self):
        self.terminate_calls += 1

        if not self.survive_terminate:
            self._alive = False
            self.exitcode = -15

    def kill(self):
        self.kill_calls += 1

        if not self.survive_kill:
            self._alive = False
            self.exitcode = -9

    def join(
        self,
        timeout=None,
    ):
        self.join_calls.append(
            timeout
        )


def factory_with_capture():
    created = []

    def factory(**kwargs):
        process = FakeProcess(
            **kwargs
        )

        created.append(
            process
        )

        return process

    return factory, created


def test_construction_does_not_start_process():
    factory, created = (
        factory_with_capture()
    )

    supervisor = (
        WebullTradeEventsProcessSupervisor(
            worker_target=worker_target,
            process_factory=factory,
        )
    )

    assert created == []
    assert supervisor.is_alive() is False


def test_start_creates_daemon_worker():
    factory, created = (
        factory_with_capture()
    )

    supervisor = (
        WebullTradeEventsProcessSupervisor(
            worker_target=worker_target,
            process_factory=factory,
        )
    )

    supervisor.start()

    assert len(created) == 1

    process = created[0]

    assert process.daemon is True

    assert (
        process.name
        == "webull-trade-events"
    )

    assert (
        process.target
        is module._worker_bootstrap
    )

    assert process.start_calls == 1
    assert supervisor.is_alive() is True


def test_second_start_while_alive_fails_closed():
    factory, _ = factory_with_capture()

    supervisor = (
        WebullTradeEventsProcessSupervisor(
            worker_target=worker_target,
            process_factory=factory,
        )
    )

    supervisor.start()

    with pytest.raises(
        WebullTradeEventsProcessError,
        match=(
            "TRADE_EVENTS_WORKER_ALREADY_RUNNING"
        ),
    ):
        supervisor.start()


def test_stop_terminates_and_joins_worker():
    factory, created = (
        factory_with_capture()
    )

    supervisor = (
        WebullTradeEventsProcessSupervisor(
            worker_target=worker_target,
            process_factory=factory,
            stop_timeout_seconds=1.5,
        )
    )

    supervisor.start()

    stopped = supervisor.stop()

    process = created[0]

    assert stopped is True
    assert process.terminate_calls == 1
    assert process.kill_calls == 0

    assert process.join_calls == [
        1.5,
    ]

    assert supervisor.is_alive() is False


def test_stop_uses_kill_if_terminate_cannot_stop():
    factory, created = (
        factory_with_capture()
    )

    supervisor = (
        WebullTradeEventsProcessSupervisor(
            worker_target=worker_target,
            process_factory=factory,
            stop_timeout_seconds=1.0,
        )
    )

    supervisor.start()

    process = created[0]
    process.survive_terminate = True

    assert supervisor.stop() is True

    assert process.terminate_calls == 1
    assert process.kill_calls == 1

    assert process.join_calls == [
        1.0,
        1.0,
    ]

    assert supervisor.is_alive() is False


def test_stop_fails_if_worker_survives_kill():
    factory, created = (
        factory_with_capture()
    )

    supervisor = (
        WebullTradeEventsProcessSupervisor(
            worker_target=worker_target,
            process_factory=factory,
        )
    )

    supervisor.start()

    process = created[0]

    process.survive_terminate = True
    process.survive_kill = True

    with pytest.raises(
        WebullTradeEventsProcessError,
        match=(
            "TRADE_EVENTS_WORKER_STOP_FAILED"
        ),
    ):
        supervisor.stop()


def test_health_check_requires_live_worker():
    factory, created = (
        factory_with_capture()
    )

    supervisor = (
        WebullTradeEventsProcessSupervisor(
            worker_target=worker_target,
            process_factory=factory,
        )
    )

    with pytest.raises(
        WebullTradeEventsProcessError,
        match=(
            "TRADE_EVENTS_WORKER_NOT_STARTED"
        ),
    ):
        supervisor.ensure_healthy()

    supervisor.start()

    supervisor.ensure_healthy()

    created[0]._alive = False

    with pytest.raises(
        WebullTradeEventsProcessError,
        match=(
            "TRADE_EVENTS_WORKER_NOT_RUNNING"
        ),
    ):
        supervisor.ensure_healthy()


def test_bootstrap_redirects_before_worker_runs(
    monkeypatch,
):
    actions = []

    monkeypatch.setattr(
        module,
        "_redirect_worker_output",
        lambda: actions.append(
            "redirect"
        ),
    )

    def target():
        actions.append(
            "target"
        )

    module._worker_bootstrap(
        target,
        (),
    )

    assert actions == [
        "redirect",
        "target",
    ]


def test_output_redirect_targets_stdout_and_stderr(
    monkeypatch,
):
    calls = []

    monkeypatch.setattr(
        module.os,
        "open",
        lambda path, flags: 99,
    )

    monkeypatch.setattr(
        module.os,
        "dup2",
        lambda source, target: (
            calls.append(
                (
                    "dup2",
                    source,
                    target,
                )
            )
        ),
    )

    monkeypatch.setattr(
        module.os,
        "close",
        lambda descriptor: (
            calls.append(
                (
                    "close",
                    descriptor,
                )
            )
        ),
    )

    module._redirect_worker_output()

    assert (
        "dup2",
        99,
        1,
    ) in calls

    assert (
        "dup2",
        99,
        2,
    ) in calls

    assert (
        "close",
        99,
    ) in calls
