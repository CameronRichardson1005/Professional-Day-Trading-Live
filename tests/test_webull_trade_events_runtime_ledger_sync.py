from types import SimpleNamespace

import trading_bot.webull_sandbox_runtime as runtime_module


ACCOUNT_ID = "sandbox-account"
CLIENT_ORDER_ID = "client-order-1"


class FakeQueue:
    def __init__(
        self,
        *,
        maxsize,
    ):
        self.maxsize = maxsize


def queue_factory(
    *,
    maxsize,
):
    return FakeQueue(
        maxsize=maxsize
    )


class FakeProcess:
    def __init__(
        self,
        *args,
        **kwargs,
    ):
        self.args = args
        self.kwargs = kwargs
        self.alive = False

    def is_alive(self):
        return self.alive

    def start(self):
        self.alive = True

    def terminate(self):
        self.alive = False

    def kill(self):
        self.alive = False

    def join(
        self,
        timeout=None,
    ):
        del timeout


def process_factory(
    *args,
    **kwargs,
):
    return FakeProcess(
        *args,
        **kwargs,
    )


def install_runtime_config(
    monkeypatch,
):
    monkeypatch.setattr(
        runtime_module,
        "WEBULL_EXECUTION_MODE",
        "SANDBOX",
    )

    monkeypatch.setattr(
        runtime_module,
        "WEBULL_SANDBOX_APP_KEY",
        "test-key",
    )

    monkeypatch.setattr(
        runtime_module,
        "WEBULL_SANDBOX_APP_SECRET",
        "test-secret",
    )

    monkeypatch.setattr(
        runtime_module,
        "WEBULL_SANDBOX_ACCOUNT_ID",
        ACCOUNT_ID,
    )


def valid_event():
    return {
        "kind": "ORDER_STATUS_CHANGED",
        "account_id": ACCOUNT_ID,
        "client_order_id": (
            CLIENT_ORDER_ID
        ),
        "symbol": "AAPL",
        "side": "BUY",
        "order_status": "CANCELLED",
        "scene_type": "CANCEL_SUCCESS",
        "qty": "1.00",
        "filled_qty": "0.000",
    }


def local_record():
    return SimpleNamespace(
        client_order_id=(
            CLIENT_ORDER_ID
        ),
        execution_mode="SANDBOX",
        symbol="AAPL",
        side="BUY",
    )


class FakeLedger:
    def __init__(self):
        self.records = {
            CLIENT_ORDER_ID: (
                local_record()
            )
        }

    def load(self):
        return self.records


def test_runtime_uses_default_ledger_sync_handler(
    monkeypatch,
    tmp_path,
):
    install_runtime_config(
        monkeypatch
    )

    sentinel_handler = (
        lambda event: event
    )

    calls = []

    def build_handler():
        calls.append(True)
        return sentinel_handler

    monkeypatch.setattr(
        runtime_module,
        "_build_webull_trade_events_ledger_sync_handler",
        build_handler,
    )

    runtime = (
        runtime_module
        .build_webull_sandbox_trade_events_runtime(
            queue_factory=queue_factory,
            process_factory=(
                process_factory
            ),
            journal_path=(
                tmp_path
                / "events.jsonl"
            ),
        )
    )

    assert calls == [True]

    assert (
        runtime.controller.event_handler
        is sentinel_handler
    )

    assert (
        runtime.supervisor.process
        is None
    )


def test_explicit_handler_overrides_default(
    monkeypatch,
    tmp_path,
):
    install_runtime_config(
        monkeypatch
    )

    explicit_handler = (
        lambda event: event
    )

    default_calls = []

    def forbidden_default():
        default_calls.append(True)

        raise AssertionError(
            "Default handler must not be built "
            "when an explicit handler is supplied."
        )

    monkeypatch.setattr(
        runtime_module,
        "_build_webull_trade_events_ledger_sync_handler",
        forbidden_default,
    )

    runtime = (
        runtime_module
        .build_webull_sandbox_trade_events_runtime(
            event_handler=(
                explicit_handler
            ),
            queue_factory=queue_factory,
            process_factory=(
                process_factory
            ),
            journal_path=(
                tmp_path
                / "events.jsonl"
            ),
        )
    )

    assert default_calls == []

    assert (
        runtime.controller.event_handler
        is explicit_handler
    )

    assert (
        runtime.supervisor.process
        is None
    )


def test_default_handler_is_lazy_and_broker_is_disarmed(
    monkeypatch,
):
    install_runtime_config(
        monkeypatch
    )

    ledger = FakeLedger()

    broker_calls = []

    class FakeBroker:
        def __init__(
            self,
            *,
            account_id,
            execution_mode,
            submission_enabled,
        ):
            broker_calls.append(
                {
                    "account_id": (
                        account_id
                    ),
                    "execution_mode": (
                        execution_mode
                    ),
                    "submission_enabled": (
                        submission_enabled
                    ),
                }
            )

    manager_instances = []

    class FakeManager:
        def __init__(
            self,
            *,
            broker,
            ledger,
            execution_mode,
        ):
            self.broker = broker
            self.ledger = ledger
            self.execution_mode = (
                execution_mode
            )
            self.reconcile_calls = []

            manager_instances.append(
                self
            )

        def reconcile(
            self,
            *,
            client_order_id,
        ):
            self.reconcile_calls.append(
                client_order_id
            )

            return SimpleNamespace(
                client_order_id=(
                    client_order_id
                ),
                status="CANCELLED",
            )

    monkeypatch.setattr(
        runtime_module,
        "WebullSandboxBroker",
        FakeBroker,
    )

    monkeypatch.setattr(
        runtime_module,
        "WebullSandboxExecutionManager",
        FakeManager,
    )

    handler = (
        runtime_module
        ._build_webull_trade_events_ledger_sync_handler(
            ledger=ledger,
        )
    )

    # Critical regression:
    # constructing the handler itself is offline.
    assert broker_calls == []
    assert manager_instances == []

    result = handler(
        valid_event()
    )

    assert result.status == "CANCELLED"

    assert broker_calls == [
        {
            "account_id": ACCOUNT_ID,
            "execution_mode": "SANDBOX",
            "submission_enabled": False,
        }
    ]

    assert len(
        manager_instances
    ) == 1

    assert (
        manager_instances[0]
        .reconcile_calls
        == [
            CLIENT_ORDER_ID
        ]
    )

    # Reuse the same manager/synchronizer rather than creating a
    # new SDK client for every event.
    handler(
        valid_event()
    )

    assert len(
        broker_calls
    ) == 1

    assert len(
        manager_instances
    ) == 1


def test_injected_manager_remains_lazy(
    monkeypatch,
):
    install_runtime_config(
        monkeypatch
    )

    ledger = FakeLedger()

    class ForbiddenBroker:
        def __init__(
            self,
            *args,
            **kwargs,
        ):
            del args
            del kwargs

            raise AssertionError(
                "Injected manager must not "
                "construct a broker."
            )

    monkeypatch.setattr(
        runtime_module,
        "WebullSandboxBroker",
        ForbiddenBroker,
    )

    calls = []

    class FakeManager:
        def reconcile(
            self,
            *,
            client_order_id,
        ):
            calls.append(
                client_order_id
            )

            return SimpleNamespace(
                client_order_id=(
                    client_order_id
                ),
                status="CANCELLED",
            )

    manager = FakeManager()

    handler = (
        runtime_module
        ._build_webull_trade_events_ledger_sync_handler(
            ledger=ledger,
            execution_manager=manager,
        )
    )

    assert calls == []

    result = handler(
        valid_event()
    )

    assert result.status == "CANCELLED"

    assert calls == [
        CLIENT_ORDER_ID
    ]
