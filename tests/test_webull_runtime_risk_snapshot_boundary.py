import ast
from pathlib import Path

from trading_bot.webull_runtime_risk import (
    WebullRuntimeRiskError as LegacyError,
    WebullRuntimeRiskSnapshot as LegacySnapshot,
    WebullRuntimeRiskSnapshotClient as LegacyClient,
)
from trading_bot.webull_runtime_risk_snapshot import (
    WebullRuntimeRiskError,
    WebullRuntimeRiskSnapshot,
    WebullRuntimeRiskSnapshotClient,
)


def test_legacy_runtime_risk_api_reexports_read_only_types():
    assert (
        LegacyError
        is WebullRuntimeRiskError
    )

    assert (
        LegacySnapshot
        is WebullRuntimeRiskSnapshot
    )

    assert (
        LegacyClient
        is WebullRuntimeRiskSnapshotClient
    )


def test_read_only_runtime_risk_module_has_no_execution_dependencies():
    path = Path(
        "trading_bot/"
        "webull_runtime_risk_snapshot.py"
    )

    tree = ast.parse(
        path.read_text(
            encoding="utf-8"
        )
    )

    forbidden = {
        "WebullSandboxBroker",
        "WebullSandboxExecutionManager",
        "WebullExecutionLedger",
        "WebullRiskProtectedSubmissionService",
        "TradeClient",
        "ApiClient",
    }

    found = set()

    for node in ast.walk(tree):
        if isinstance(
            node,
            ast.ImportFrom,
        ):
            for alias in node.names:
                if alias.name in forbidden:
                    found.add(
                        alias.name
                    )

        elif isinstance(
            node,
            ast.Name,
        ):
            if node.id in forbidden:
                found.add(
                    node.id
                )

    assert found == set()


def test_read_only_runtime_risk_module_has_no_mutation_methods():
    path = Path(
        "trading_bot/"
        "webull_runtime_risk_snapshot.py"
    )

    tree = ast.parse(
        path.read_text(
            encoding="utf-8"
        )
    )

    forbidden_attributes = {
        "place_order",
        "replace_order",
        "cancel_order",
        "close_order",
        "submit",
        "submit_order",
        "submit_with_account_risk",
    }

    found = set()

    for node in ast.walk(tree):
        if (
            isinstance(
                node,
                ast.Attribute,
            )
            and node.attr
            in forbidden_attributes
        ):
            found.add(
                node.attr
            )

    assert found == set()
