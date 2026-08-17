import trading_bot.webull_sandbox_runtime as runtime


def install_fakes(
    monkeypatch,
    *,
    management_armed,
):
    calls = {}

    monkeypatch.setattr(
        runtime,
        "WEBULL_SANDBOX_ACCOUNT_ID",
        "sandbox-cash",
    )

    monkeypatch.setattr(
        runtime,
        "WEBULL_EXECUTION_MODE",
        "SANDBOX",
    )

    monkeypatch.setattr(
        runtime,
        "WEBULL_SANDBOX_ORDER_MANAGEMENT_ENABLED",
        management_armed,
    )

    monkeypatch.setattr(
        runtime,
        "WEBULL_SANDBOX_ORDER_SUBMISSION_ENABLED",
        True,
    )

    class FakeSnapshotClient:
        def __init__(
            self,
            *,
            account_id,
            execution_mode,
        ):
            calls["snapshot"] = {
                "account_id": account_id,
                "execution_mode": execution_mode,
            }

    class FakeBroker:
        def __init__(
            self,
            *,
            account_id,
            execution_mode,
            submission_enabled,
        ):
            calls["broker"] = {
                "account_id": account_id,
                "execution_mode": execution_mode,
                "submission_enabled": (
                    submission_enabled
                ),
            }

    class FakeCloseLedger:
        def __init__(self):
            calls["ledger"] = self

    class FakeCloseManager:
        def __init__(
            self,
            *,
            broker,
            ledger,
            snapshot_client,
            execution_mode,
        ):
            calls["manager"] = {
                "broker": broker,
                "ledger": ledger,
                "snapshot_client": snapshot_client,
                "execution_mode": execution_mode,
            }

    class FakeCloseService:
        def __init__(
            self,
            *,
            snapshot_client,
            close_manager,
            management_armed,
        ):
            calls["service"] = {
                "snapshot_client": snapshot_client,
                "close_manager": close_manager,
                "management_armed": (
                    management_armed
                ),
            }

    monkeypatch.setattr(
        runtime,
        "WebullSandboxAccountSnapshotClient",
        FakeSnapshotClient,
    )

    monkeypatch.setattr(
        runtime,
        "WebullSandboxBroker",
        FakeBroker,
    )

    monkeypatch.setattr(
        runtime,
        "WebullReduceOnlyCloseLedger",
        FakeCloseLedger,
    )

    monkeypatch.setattr(
        runtime,
        "WebullSandboxReduceOnlyCloseManager",
        FakeCloseManager,
    )

    monkeypatch.setattr(
        runtime,
        "WebullSandboxManualCloseService",
        FakeCloseService,
    )

    return calls


def test_close_runtime_builder_defaults_disarmed(
    monkeypatch,
):
    calls = install_fakes(
        monkeypatch,
        management_armed=False,
    )

    runtime.build_webull_sandbox_manual_close_service()

    assert calls["snapshot"] == {
        "account_id": "sandbox-cash",
        "execution_mode": "SANDBOX",
    }

    assert calls["broker"] == {
        "account_id": "sandbox-cash",
        "execution_mode": "SANDBOX",
        "submission_enabled": False,
    }

    assert (
        calls["service"]["management_armed"]
        is False
    )


def test_close_runtime_uses_only_management_arm(
    monkeypatch,
):
    calls = install_fakes(
        monkeypatch,
        management_armed=True,
    )

    runtime.build_webull_sandbox_manual_close_service()

    assert (
        calls["broker"]["submission_enabled"]
        is False
    )

    assert (
        calls["service"]["management_armed"]
        is True
    )


def test_entry_submission_flag_cannot_arm_close_broker(
    monkeypatch,
):
    calls = install_fakes(
        monkeypatch,
        management_armed=False,
    )

    assert (
        runtime.WEBULL_SANDBOX_ORDER_SUBMISSION_ENABLED
        is True
    )

    runtime.build_webull_sandbox_manual_close_service()

    assert (
        calls["broker"]["submission_enabled"]
        is False
    )

    assert (
        calls["service"]["management_armed"]
        is False
    )



def test_close_manager_receives_fresh_snapshot_client(
    monkeypatch,
):
    calls = install_fakes(
        monkeypatch,
        management_armed=False,
    )

    runtime.build_webull_sandbox_manual_close_service()

    assert (
        calls["manager"]["snapshot_client"]
        is calls["service"]["snapshot_client"]
    )
