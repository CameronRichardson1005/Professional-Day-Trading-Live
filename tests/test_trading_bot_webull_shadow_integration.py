import ast
import inspect
import textwrap
from types import SimpleNamespace

import pytest

import trading_bot.bot as bot_module
import trading_bot.config as config_module
import trading_bot.webull_sandbox_shadow_runtime as runtime_module

from trading_bot.bot import TradingBot


READY_MANIPULATION = {
    "status": "PREVIEW READY",
    "submitted": False,
    "symbol": "OPEN",
    "strategyName": "MANIPULATION",
    "side": "BUY",
    "quantity": 10,
    "limitBuy": 10.0,
    "target": 11.0,
    "tradingStopLoss": 9.5,
    "estimatedPositionValue": 100.0,
    "maxPositionValue": 225.0,
    "sizingConstraint": "TEST",
    "estimatedCost": 100.0,
    "estimatedTransactionFee": 0.0,
    "safetyAllowed": True,
}

READY_QUICK_FLIP = {
    "status": "PREVIEW READY",
    "submitted": False,
    "symbol": "SOUN",
    "strategyName": "QUICK_FLIP",
    "side": "BUY",
    "quantity": 20,
    "limitBuy": 5.0,
    "takeProfit1": 5.25,
    "takeProfit2": 5.5,
    "automaticStopLoss": False,
    "estimatedPositionValue": 100.0,
    "estimatedCost": 100.0,
    "estimatedTransactionFee": 0.0,
    "safetyAllowed": True,
}


class FakeRecord:
    def __init__(
        self,
        *,
        status="REJECTED_SHADOW",
        decision_reason="TRADING_KILL_SWITCH_ACTIVE",
    ):
        self.status = status
        self.decision_reason = decision_reason


class FakeShadowService:
    def __init__(
        self,
        *,
        error=None,
    ):
        self.error = error
        self.manipulation_calls = []
        self.quick_flip_calls = []

    def evaluate_manipulation_preview(
        self,
        *,
        preview,
    ):
        self.manipulation_calls.append(
            preview
        )

        if self.error is not None:
            raise self.error

        return FakeRecord()

    def evaluate_quick_flip_preview(
        self,
        *,
        preview,
    ):
        self.quick_flip_calls.append(
            preview
        )

        if self.error is not None:
            raise self.error

        return FakeRecord()


def bare_bot():
    bot = TradingBot.__new__(
        TradingBot
    )

    bot.webull_sandbox_shadow_runtime = None
    bot.webull_sandbox_shadow_runtime_date = None

    return bot


def test_missing_history_start_fails_before_factory(
    monkeypatch,
):
    bot = bare_bot()

    monkeypatch.setattr(
        config_module,
        "WEBULL_SANDBOX_SHADOW_HISTORY_START_DATE",
        "",
    )

    calls = []

    def forbidden_builder(**kwargs):
        calls.append(kwargs)
        raise AssertionError(
            "factory must not run"
        )

    monkeypatch.setattr(
        runtime_module,
        "build_webull_sandbox_shadow_runtime",
        forbidden_builder,
    )

    with pytest.raises(
        RuntimeError,
        match=(
            "^WEBULL_SANDBOX_SHADOW_"
            "HISTORY_START_DATE_REQUIRED$"
        ),
    ):
        bot._get_webull_sandbox_shadow_runtime(
            "2026-08-18"
        )

    assert calls == []


def test_lazy_factory_uses_explicit_history_start_and_caches(
    monkeypatch,
):
    bot = bare_bot()

    monkeypatch.setattr(
        config_module,
        "WEBULL_SANDBOX_SHADOW_HISTORY_START_DATE",
        "2026-08-01",
    )

    calls = []
    runtime = object()

    def fake_builder(**kwargs):
        calls.append(kwargs)
        return runtime

    monkeypatch.setattr(
        runtime_module,
        "build_webull_sandbox_shadow_runtime",
        fake_builder,
    )

    first = (
        bot._get_webull_sandbox_shadow_runtime(
            "2026-08-18"
        )
    )

    second = (
        bot._get_webull_sandbox_shadow_runtime(
            "2026-08-18"
        )
    )

    assert first is runtime
    assert second is runtime
    assert len(calls) == 1

    assert (
        calls[0][
            "history_start_date"
        ]
        == "2026-08-01"
    )

    assert (
        calls[0][
            "trading_date_provider"
        ]()
        == "2026-08-18"
    )


def test_new_trading_date_rebuilds_runtime(
    monkeypatch,
):
    bot = bare_bot()

    monkeypatch.setattr(
        config_module,
        "WEBULL_SANDBOX_SHADOW_HISTORY_START_DATE",
        "2026-08-01",
    )

    runtimes = [
        object(),
        object(),
    ]

    calls = []

    def fake_builder(**kwargs):
        calls.append(kwargs)
        return runtimes[
            len(calls) - 1
        ]

    monkeypatch.setattr(
        runtime_module,
        "build_webull_sandbox_shadow_runtime",
        fake_builder,
    )

    first = (
        bot._get_webull_sandbox_shadow_runtime(
            "2026-08-18"
        )
    )

    second = (
        bot._get_webull_sandbox_shadow_runtime(
            "2026-08-19"
        )
    )

    assert first is runtimes[0]
    assert second is runtimes[1]
    assert len(calls) == 2


def test_history_start_after_trading_date_fails_before_factory(
    monkeypatch,
):
    bot = bare_bot()

    monkeypatch.setattr(
        config_module,
        "WEBULL_SANDBOX_SHADOW_HISTORY_START_DATE",
        "2026-08-19",
    )

    calls = []

    def forbidden_builder(**kwargs):
        calls.append(kwargs)
        raise AssertionError(
            "factory must not run"
        )

    monkeypatch.setattr(
        runtime_module,
        "build_webull_sandbox_shadow_runtime",
        forbidden_builder,
    )

    with pytest.raises(
        RuntimeError,
        match=(
            "^WEBULL_SANDBOX_SHADOW_"
            "HISTORY_START_AFTER_TRADING_DATE$"
        ),
    ):
        bot._get_webull_sandbox_shadow_runtime(
            "2026-08-18"
        )

    assert calls == []


def test_manipulation_ready_preview_routes_to_shadow_service(
    capsys,
):
    bot = bare_bot()
    service = FakeShadowService()

    bot._get_webull_sandbox_shadow_runtime = (
        lambda date_str:
        SimpleNamespace(
            service=service
        )
    )

    record = (
        bot
        ._observe_webull_shadow_preview_safely(
            preview=dict(
                READY_MANIPULATION
            ),
            strategy_name="MANIPULATION",
            date_str="2026-08-18",
        )
    )

    assert record is not None
    assert len(
        service.manipulation_calls
    ) == 1
    assert service.quick_flip_calls == []

    output = capsys.readouterr().out

    assert "REJECTED_SHADOW" in output
    assert (
        "TRADING_KILL_SWITCH_ACTIVE"
        in output
    )
    assert "NOT SUBMITTED" in output


def test_quick_flip_ready_preview_routes_to_shadow_service():
    bot = bare_bot()
    service = FakeShadowService()

    bot._get_webull_sandbox_shadow_runtime = (
        lambda date_str:
        SimpleNamespace(
            service=service
        )
    )

    record = (
        bot
        ._observe_webull_shadow_preview_safely(
            preview=dict(
                READY_QUICK_FLIP
            ),
            strategy_name="QUICK_FLIP",
            date_str="2026-08-18",
        )
    )

    assert record is not None
    assert service.manipulation_calls == []
    assert len(
        service.quick_flip_calls
    ) == 1


def test_failed_or_undated_preview_does_not_build_runtime():
    bot = bare_bot()

    calls = []

    bot._get_webull_sandbox_shadow_runtime = (
        lambda date_str:
        calls.append(date_str)
    )

    failed = dict(
        READY_MANIPULATION
    )
    failed["status"] = (
        "PREVIEW FAILED"
    )

    assert (
        bot
        ._observe_webull_shadow_preview_safely(
            preview=failed,
            strategy_name="MANIPULATION",
            date_str="2026-08-18",
        )
        is None
    )

    assert (
        bot
        ._observe_webull_shadow_preview_safely(
            preview=dict(
                READY_MANIPULATION
            ),
            strategy_name="MANIPULATION",
            date_str=None,
        )
        is None
    )

    assert calls == []


def test_shadow_failure_is_isolated_from_preview(
    capsys,
):
    bot = bare_bot()

    original = dict(
        READY_MANIPULATION
    )

    service = FakeShadowService(
        error=RuntimeError(
            "controlled"
        )
    )

    bot._get_webull_sandbox_shadow_runtime = (
        lambda date_str:
        SimpleNamespace(
            service=service
        )
    )

    preview = dict(
        original
    )

    result = (
        bot
        ._observe_webull_shadow_preview_safely(
            preview=preview,
            strategy_name="MANIPULATION",
            date_str="2026-08-18",
        )
    )

    assert result is None
    assert preview == original

    output = capsys.readouterr().out

    assert (
        "Preview remains unchanged."
        in output
    )


def test_manipulation_preview_workflow_calls_shadow_observer(
    monkeypatch,
):
    bot = bare_bot()
    bot.stocks = {
        "OPEN": object(),
    }

    observed = []
    notified = []

    bot._notify_manipulation_preview = (
        lambda preview:
        notified.append(
            preview
        )
    )

    bot._observe_webull_shadow_preview_safely = (
        lambda **kwargs:
        observed.append(
            kwargs
        )
    )

    class FakePreviewService:
        committed_policy_funded = True
        committed_policy_decision_reason = (
            "FUNDED"
        )

        def prepare_previews(
            self,
            *,
            stocks,
            trading_date=None,
        ):
            return [
                dict(
                    READY_MANIPULATION
                )
            ]

    monkeypatch.setattr(
        bot_module,
        "WebullPreviewService",
        FakePreviewService,
    )

    results = bot.prepare_webull_previews(
        date_str="2026-08-18"
    )

    assert len(results) == 1
    assert len(notified) == 1
    assert len(observed) == 1

    assert (
        observed[0][
            "strategy_name"
        ]
        == "MANIPULATION"
    )

    assert (
        observed[0]["date_str"]
        == "2026-08-18"
    )


def test_quick_flip_ready_branch_contains_shadow_observer():
    source = inspect.getsource(
        TradingBot.run_quick_flip_monitor
    )

    assert (
        'strategy_name="QUICK_FLIP"'
        in source
    )

    ready_index = source.index(
        'preview.get("status")'
    )

    shadow_index = source.index(
        "_observe_webull_shadow_preview_safely",
        ready_index,
    )

    notify_or_print_index = (
        source.index(
            'f"{symbol}: QUICK FLIP "',
            shadow_index,
        )
    )

    assert (
        ready_index
        < shadow_index
        < notify_or_print_index
    )


def test_shadow_bot_methods_contain_no_order_mutation_calls():
    methods = (
        TradingBot
        ._get_webull_sandbox_shadow_runtime,
        TradingBot
        ._observe_webull_shadow_preview_safely,
    )

    forbidden = {
        "place_order",
        "replace_order",
        "cancel_order",
        "close_order",
        "submit",
        "submit_order",
        "submit_with_account_risk",
    }

    found = set()

    for method in methods:
        source = textwrap.dedent(
            inspect.getsource(
                method
            )
        )

        tree = ast.parse(
            source
        )

        for node in ast.walk(tree):
            if (
                isinstance(
                    node,
                    ast.Attribute,
                )
                and node.attr
                in forbidden
            ):
                found.add(
                    node.attr
                )

    assert found == set()
