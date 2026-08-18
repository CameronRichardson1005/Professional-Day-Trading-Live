from pathlib import Path

import pytest

import trading_bot.webull_sandbox_runtime as module


class FakeQueue:
    def __init__(
        self,
        *,
        maxsize,
    ):
        self.maxsize = maxsize


def queue_factory_capture():
    created = []

    def factory(
        *,
        maxsize,
    ):
        queue = FakeQueue(
            maxsize=maxsize
        )

        created.append(
            queue
        )

        return queue

    return factory, created


def install_safe_config(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(
        module,
        "WEBULL_EXECUTION_MODE",
        "SANDBOX",
    )

    monkeypatch.setattr(
        module,
        "WEBULL_SANDBOX_APP_KEY",
        "sandbox-key",
    )

    monkeypatch.setattr(
        module,
        "WEBULL_SANDBOX_APP_SECRET",
        "sandbox-secret",
    )

    monkeypatch.setattr(
        module,
        "WEBULL_SANDBOX_ACCOUNT_ID",
        "sandbox-account-1",
    )

    monkeypatch.setattr(
        module,
        "WEBULL_TRADE_EVENTS_JOURNAL_FILE",
        tmp_path / "events.jsonl",
    )


def test_runtime_construction_does_not_start_process(
    monkeypatch,
    tmp_path,
):
    install_safe_config(
        monkeypatch,
        tmp_path,
    )

    queue_factory, _ = (
        queue_factory_capture()
    )

    process_factory_calls = []

    def forbidden_process_factory(
        **kwargs,
    ):
        process_factory_calls.append(
            kwargs
        )

        raise AssertionError(
            "Process must not be created "
            "during runtime construction."
        )

    runtime = (
        module
        .build_webull_sandbox_trade_events_runtime(
            reconcile=lambda: None,
            queue_factory=queue_factory,
            process_factory=(
                forbidden_process_factory
            ),
        )
    )

    assert process_factory_calls == []
    assert runtime.supervisor.process is None
    assert runtime.supervisor.is_alive() is False


def test_runtime_uses_shared_parent_worker_queues(
    monkeypatch,
    tmp_path,
):
    install_safe_config(
        monkeypatch,
        tmp_path,
    )

    queue_factory, created = (
        queue_factory_capture()
    )

    runtime = (
        module
        .build_webull_sandbox_trade_events_runtime(
            reconcile=lambda: None,
            queue_factory=queue_factory,
            process_factory=lambda **kwargs: None,
        )
    )

    assert len(created) == 2

    assert (
        runtime.event_queue.maxsize
        == module.WEBULL_TRADE_EVENTS_EVENT_QUEUE_MAXSIZE
    )

    assert (
        runtime.control_queue.maxsize
        == module.WEBULL_TRADE_EVENTS_CONTROL_QUEUE_MAXSIZE
    )

    assert (
        runtime.controller.event_queue
        is runtime.event_queue
    )

    assert (
        runtime.controller.control_queue
        is runtime.control_queue
    )

    worker_args = (
        runtime.supervisor.worker_args
    )

    assert (
        worker_args[3]
        is runtime.event_queue
    )

    assert (
        worker_args[4]
        is runtime.control_queue
    )


def test_runtime_worker_is_fixed_to_sandbox_host(
    monkeypatch,
    tmp_path,
):
    install_safe_config(
        monkeypatch,
        tmp_path,
    )

    queue_factory, _ = (
        queue_factory_capture()
    )

    runtime = (
        module
        .build_webull_sandbox_trade_events_runtime(
            reconcile=lambda: None,
            queue_factory=queue_factory,
            process_factory=lambda **kwargs: None,
        )
    )

    args = runtime.supervisor.worker_args

    assert args[0] == "sandbox-key"
    assert args[1] == "sandbox-secret"

    assert args[2] == (
        "sandbox-account-1",
    )

    assert (
        args[5]
        == module.WEBULL_SANDBOX_EVENTS_HOST
    )

    assert (
        runtime.supervisor.worker_target
        is module._run_webull_trade_events_worker_entry
    )


def test_runtime_uses_dedicated_journal_path(
    monkeypatch,
    tmp_path,
):
    install_safe_config(
        monkeypatch,
        tmp_path,
    )

    queue_factory, _ = (
        queue_factory_capture()
    )

    expected = (
        tmp_path / "events.jsonl"
    )

    runtime = (
        module
        .build_webull_sandbox_trade_events_runtime(
            reconcile=lambda: None,
            queue_factory=queue_factory,
            process_factory=lambda **kwargs: None,
        )
    )

    assert (
        runtime.journal.path
        == expected
    )

    assert isinstance(
        runtime.journal.path,
        Path,
    )


def test_parent_and_runtime_share_health_state(
    monkeypatch,
    tmp_path,
):
    install_safe_config(
        monkeypatch,
        tmp_path,
    )

    queue_factory, _ = (
        queue_factory_capture()
    )

    runtime = (
        module
        .build_webull_sandbox_trade_events_runtime(
            reconcile=lambda: None,
            queue_factory=queue_factory,
            process_factory=lambda **kwargs: None,
        )
    )

    assert (
        runtime.controller.health
        is runtime.health
    )

    health_check = (
        runtime.controller
        .ensure_worker_healthy
    )

    assert (
        health_check.__self__
        is runtime.supervisor
    )

    assert (
        health_check.__func__
        is runtime.supervisor.ensure_healthy.__func__
    )


def test_runtime_construction_does_not_reconcile(
    monkeypatch,
    tmp_path,
):
    install_safe_config(
        monkeypatch,
        tmp_path,
    )

    queue_factory, _ = (
        queue_factory_capture()
    )

    calls = []

    def reconcile():
        calls.append(
            True
        )

        raise AssertionError(
            "Reconciliation must not occur "
            "during construction."
        )

    runtime = (
        module
        .build_webull_sandbox_trade_events_runtime(
            reconcile=reconcile,
            queue_factory=queue_factory,
            process_factory=lambda **kwargs: None,
        )
    )

    assert calls == []

    assert (
        runtime.controller.reconcile
        is reconcile
    )


def test_non_sandbox_mode_fails_before_resource_creation(
    monkeypatch,
    tmp_path,
):
    install_safe_config(
        monkeypatch,
        tmp_path,
    )

    monkeypatch.setattr(
        module,
        "WEBULL_EXECUTION_MODE",
        "DISABLED",
    )

    queue_calls = []

    def forbidden_queue_factory(
        *,
        maxsize,
    ):
        queue_calls.append(
            maxsize
        )

        raise AssertionError(
            "Queue must not be created."
        )

    with pytest.raises(
        module.WebullSandboxTradeEventsRuntimeError,
        match=(
            "TRADE_EVENTS_SANDBOX_MODE_REQUIRED"
        ),
    ):
        module.build_webull_sandbox_trade_events_runtime(
            reconcile=lambda: None,
            queue_factory=forbidden_queue_factory,
            process_factory=lambda **kwargs: None,
        )

    assert queue_calls == []


@pytest.mark.parametrize(
    (
        "attribute",
        "reason",
    ),
    [
        (
            "WEBULL_SANDBOX_APP_KEY",
            "TRADE_EVENTS_SANDBOX_APP_KEY_REQUIRED",
        ),
        (
            "WEBULL_SANDBOX_APP_SECRET",
            "TRADE_EVENTS_SANDBOX_APP_SECRET_REQUIRED",
        ),
        (
            "WEBULL_SANDBOX_ACCOUNT_ID",
            "TRADE_EVENTS_SANDBOX_ACCOUNT_ID_REQUIRED",
        ),
    ],
)
def test_missing_required_sandbox_identity_fails_closed(
    monkeypatch,
    tmp_path,
    attribute,
    reason,
):
    install_safe_config(
        monkeypatch,
        tmp_path,
    )

    monkeypatch.setattr(
        module,
        attribute,
        "",
    )

    queue_calls = []

    def forbidden_queue_factory(
        *,
        maxsize,
    ):
        queue_calls.append(
            maxsize
        )

        raise AssertionError(
            "Queue must not be created."
        )

    with pytest.raises(
        module.WebullSandboxTradeEventsRuntimeError,
        match=reason,
    ):
        module.build_webull_sandbox_trade_events_runtime(
            reconcile=lambda: None,
            queue_factory=forbidden_queue_factory,
            process_factory=lambda **kwargs: None,
        )

    assert queue_calls == []
