import ast
import inspect
from pathlib import Path

import pytest

import trading_bot.webull_sandbox_shadow_runtime as runtime_module

from trading_bot.webull_execution import (
    WebullExecutionMode,
)
from trading_bot.webull_sandbox_broker import (
    SANDBOX_ENDPOINT,
)
from trading_bot.webull_sandbox_shadow_runtime import (
    WebullSandboxShadowRuntimeError,
    build_webull_sandbox_shadow_runtime,
)


class SentinelTradeClient:
    """
    Deliberately has no network methods.

    Successful runtime construction with this object proves the
    factory performs no Webull request during assembly.
    """

    pass


def install_fake_client_builder(
    monkeypatch,
):
    calls = []
    client = SentinelTradeClient()

    def fake_builder(
        *,
        app_key,
        app_secret,
        endpoint,
    ):
        calls.append({
            "app_key": app_key,
            "app_secret": app_secret,
            "endpoint": endpoint,
        })

        return client

    monkeypatch.setattr(
        runtime_module,
        "build_quiet_trade_client",
        fake_builder,
    )

    return client, calls


def build_runtime(
    monkeypatch,
    tmp_path,
    **kwargs,
):
    client, calls = (
        install_fake_client_builder(
            monkeypatch
        )
    )

    runtime = (
        build_webull_sandbox_shadow_runtime(
            trading_date_provider=(
                lambda: "2026-08-18"
            ),
            history_start_date=(
                "2026-08-01"
            ),
            journal_path=(
                tmp_path / "shadow.json"
            ),
            account_id="sandbox-account",
            app_key="sandbox-key",
            app_secret="sandbox-secret",
            execution_mode=(
                WebullExecutionMode.SANDBOX.value
            ),
            **kwargs,
        )
    )

    return runtime, client, calls


def test_factory_pins_sdk_client_to_sandbox_endpoint(
    monkeypatch,
    tmp_path,
):
    runtime, client, calls = (
        build_runtime(
            monkeypatch,
            tmp_path,
        )
    )

    assert calls == [
        {
            "app_key": "sandbox-key",
            "app_secret": (
                "sandbox-secret"
            ),
            "endpoint": SANDBOX_ENDPOINT,
        }
    ]

    assert (
        runtime.account_snapshot_client
        ._trade_client
        is client
    )

    assert (
        runtime.history_reader.trade_client
        is client
    )


def test_same_explicit_sandbox_account_is_used_everywhere(
    monkeypatch,
    tmp_path,
):
    runtime, _, _ = build_runtime(
        monkeypatch,
        tmp_path,
    )

    assert (
        runtime.account_snapshot_client
        .account_id
        == "sandbox-account"
    )

    assert (
        runtime.history_reader
        .account_id
        == "sandbox-account"
    )


def test_runtime_components_are_wired_to_each_other(
    monkeypatch,
    tmp_path,
):
    runtime, _, _ = build_runtime(
        monkeypatch,
        tmp_path,
    )

    assert (
        runtime.risk_snapshot_client
        .snapshot_client
        is runtime.account_snapshot_client
    )

    assert (
        runtime.risk_snapshot_client
        .daily_realized_pnl_provider
        is runtime.daily_realized_pnl_provider
    )

    assert (
        runtime.daily_realized_pnl_provider
        .history_reader
        is runtime.history_reader
    )

    assert (
        runtime.service
        .risk_snapshot_client
        is runtime.risk_snapshot_client
    )

    assert (
        runtime.service.router
        is runtime.router
    )

    assert (
        runtime.router.coordinator
        is runtime.coordinator
    )


def test_factory_construction_is_offline(
    monkeypatch,
    tmp_path,
):
    runtime, _, calls = build_runtime(
        monkeypatch,
        tmp_path,
    )

    assert len(calls) == 1

    # SentinelTradeClient exposes no account_v2/order_v3
    # methods. Reaching here proves construction made no
    # remote read call.
    assert runtime is not None


def test_real_configured_kill_switch_is_passed_through(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(
        runtime_module,
        "WEBULL_TRADING_KILL_SWITCH",
        True,
    )

    runtime, _, _ = build_runtime(
        monkeypatch,
        tmp_path,
    )

    provider = (
        runtime.risk_snapshot_client
        .kill_switch_provider
    )

    assert provider() is True


def test_factory_has_no_kill_switch_override_argument():
    signature = inspect.signature(
        build_webull_sandbox_shadow_runtime
    )

    assert (
        "kill_switch_provider"
        not in signature.parameters
    )

    assert (
        "kill_switch_active"
        not in signature.parameters
    )


def test_factory_has_no_endpoint_override_argument():
    signature = inspect.signature(
        build_webull_sandbox_shadow_runtime
    )

    assert (
        "endpoint"
        not in signature.parameters
    )

    assert (
        "host"
        not in signature.parameters
    )


def test_non_sandbox_mode_fails_before_client_construction(
    monkeypatch,
    tmp_path,
):
    _, calls = (
        install_fake_client_builder(
            monkeypatch
        )
    )

    with pytest.raises(
        WebullSandboxShadowRuntimeError,
        match=(
            "^SHADOW_SANDBOX_MODE_REQUIRED$"
        ),
    ):
        build_webull_sandbox_shadow_runtime(
            trading_date_provider=(
                lambda: "2026-08-18"
            ),
            history_start_date=(
                "2026-08-01"
            ),
            journal_path=(
                tmp_path / "shadow.json"
            ),
            account_id="sandbox-account",
            app_key="sandbox-key",
            app_secret="sandbox-secret",
            execution_mode=(
                WebullExecutionMode.DISABLED.value
            ),
        )

    assert calls == []


def test_missing_account_fails_before_client_construction(
    monkeypatch,
    tmp_path,
):
    _, calls = (
        install_fake_client_builder(
            monkeypatch
        )
    )

    with pytest.raises(
        WebullSandboxShadowRuntimeError,
        match=(
            "^SHADOW_SANDBOX_ACCOUNT_ID_REQUIRED$"
        ),
    ):
        build_webull_sandbox_shadow_runtime(
            trading_date_provider=(
                lambda: "2026-08-18"
            ),
            history_start_date=(
                "2026-08-01"
            ),
            journal_path=(
                tmp_path / "shadow.json"
            ),
            account_id="",
            app_key="sandbox-key",
            app_secret="sandbox-secret",
            execution_mode="SANDBOX",
        )

    assert calls == []


def test_missing_credentials_fail_before_client_construction(
    monkeypatch,
    tmp_path,
):
    _, calls = (
        install_fake_client_builder(
            monkeypatch
        )
    )

    with pytest.raises(
        WebullSandboxShadowRuntimeError,
        match=(
            "^SHADOW_SANDBOX_APP_KEY_REQUIRED$"
        ),
    ):
        build_webull_sandbox_shadow_runtime(
            trading_date_provider=(
                lambda: "2026-08-18"
            ),
            history_start_date=(
                "2026-08-01"
            ),
            journal_path=(
                tmp_path / "shadow.json"
            ),
            account_id="sandbox-account",
            app_key="",
            app_secret="sandbox-secret",
            execution_mode="SANDBOX",
        )

    assert calls == []


def test_invalid_trading_date_provider_fails_before_client(
    monkeypatch,
    tmp_path,
):
    _, calls = (
        install_fake_client_builder(
            monkeypatch
        )
    )

    with pytest.raises(
        WebullSandboxShadowRuntimeError,
        match=(
            "^SHADOW_TRADING_DATE_PROVIDER_INVALID$"
        ),
    ):
        build_webull_sandbox_shadow_runtime(
            trading_date_provider=None,
            history_start_date=(
                "2026-08-01"
            ),
            journal_path=(
                tmp_path / "shadow.json"
            ),
            account_id="sandbox-account",
            app_key="sandbox-key",
            app_secret="sandbox-secret",
            execution_mode="SANDBOX",
        )

    assert calls == []


def test_factory_module_contains_no_live_webull_host():
    text = Path(
        "trading_bot/"
        "webull_sandbox_shadow_runtime.py"
    ).read_text(
        encoding="utf-8"
    )

    assert "api.webull.com" not in text
    assert "api.sandbox.webull.com" not in text

    # Sandbox host must come only from the established constant.
    assert "SANDBOX_ENDPOINT" in text


def test_factory_has_no_execution_mutation_boundary():
    path = Path(
        "trading_bot/"
        "webull_sandbox_shadow_runtime.py"
    )

    tree = ast.parse(
        path.read_text(
            encoding="utf-8"
        )
    )

    forbidden_names = {
        "WebullSandboxBroker",
        "WebullSandboxExecutionManager",
        "WebullExecutionLedger",
        "WebullRiskProtectedSubmissionService",
    }

    forbidden_attributes = {
        "place_order",
        "replace_order",
        "cancel_order",
        "close_order",
        "submit",
        "submit_order",
        "submit_with_account_risk",
    }

    found = []

    for node in ast.walk(tree):
        if isinstance(
            node,
            ast.ImportFrom,
        ):
            for alias in node.names:
                if alias.name in forbidden_names:
                    found.append(
                        f"import:{alias.name}"
                    )

        elif isinstance(
            node,
            ast.Name,
        ):
            if node.id in forbidden_names:
                found.append(
                    f"name:{node.id}"
                )

        elif isinstance(
            node,
            ast.Attribute,
        ):
            if node.attr in forbidden_attributes:
                found.append(
                    f"attribute:{node.attr}"
                )

    assert found == []
