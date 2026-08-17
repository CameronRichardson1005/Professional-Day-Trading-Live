from types import SimpleNamespace

import main as main_module


class FakePreflight:
    def __init__(
        self,
        *,
        error=None,
    ):
        self.error = error
        self.run_calls = 0

    def run(self):
        self.run_calls += 1

        if self.error is not None:
            raise self.error

        return SimpleNamespace(
            allowed=True,
            reason="SANDBOX_PREFLIGHT_PASSED",
            account_id="sandbox-account",
            available_cash=500.0,
            current_exposure=100.0,
            reconciled_orders=2,
            active_manual_overrides=0,
            open_orders=1,
        )


def test_preflight_cli_is_read_only_and_succeeds(
    monkeypatch,
    capsys,
):
    fake = FakePreflight()

    monkeypatch.setattr(
        main_module,
        "setup_logging",
        lambda: "test.log",
    )

    monkeypatch.setattr(
        main_module,
        "build_webull_sandbox_preflight",
        lambda: fake,
    )

    monkeypatch.setattr(
        main_module.sys,
        "argv",
        [
            "main.py",
            "webull-sandbox-preflight",
        ],
    )

    result = main_module.main()

    captured = capsys.readouterr().out

    assert result == 0
    assert fake.run_calls == 1

    assert (
        "WEBULL SANDBOX PREFLIGHT PASSED"
        in captured
    )

    assert (
        "NO WEBULL ORDER WAS PLACED, "
        "MODIFIED, OR CANCELLED"
        in captured
    )


def test_preflight_cli_fails_closed(
    monkeypatch,
    capsys,
):
    fake = FakePreflight(
        error=RuntimeError(
            "CONTROLLED_PREFLIGHT_FAILURE"
        )
    )

    monkeypatch.setattr(
        main_module,
        "setup_logging",
        lambda: "test.log",
    )

    monkeypatch.setattr(
        main_module,
        "build_webull_sandbox_preflight",
        lambda: fake,
    )

    monkeypatch.setattr(
        main_module.sys,
        "argv",
        [
            "main.py",
            "webull-sandbox-preflight",
        ],
    )

    result = main_module.main()

    captured = capsys.readouterr().out

    assert result == 1

    assert (
        "WEBULL SANDBOX PREFLIGHT FAILED"
        in captured
    )

    assert (
        "CONTROLLED_PREFLIGHT_FAILURE"
        in captured
    )

    assert (
        "NO WEBULL ORDER WAS PLACED, "
        "MODIFIED, OR CANCELLED"
        in captured
    )


def test_preflight_runs_before_trading_bot_construction(
    monkeypatch,
):
    fake = FakePreflight()

    monkeypatch.setattr(
        main_module,
        "setup_logging",
        lambda: "test.log",
    )

    monkeypatch.setattr(
        main_module,
        "build_webull_sandbox_preflight",
        lambda: fake,
    )

    class ForbiddenTradingBot:
        def __init__(self):
            raise AssertionError(
                "TradingBot must not be constructed "
                "for sandbox preflight."
            )

    monkeypatch.setattr(
        main_module,
        "TradingBot",
        ForbiddenTradingBot,
    )

    monkeypatch.setattr(
        main_module.sys,
        "argv",
        [
            "main.py",
            "webull-sandbox-preflight",
        ],
    )

    assert main_module.main() == 0
