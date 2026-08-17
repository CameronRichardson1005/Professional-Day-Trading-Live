from types import SimpleNamespace

import main as main_module


class FakeCloseService:
    def __init__(self):
        self.calls = []

    def close(self, request):
        self.calls.append(request)

        return SimpleNamespace(
            client_order_id="close-1",
            symbol="SOUN",
            side="SELL",
            quantity=1,
            limit_price=6.90,
            status="SUBMITTED",
            filled_quantity=0.0,
            position_reconciled=False,
            broker_order_id="broker-close-1",
            broker_status="SUBMITTED",
        )


def install_common(
    monkeypatch,
):
    monkeypatch.setattr(
        main_module,
        "setup_logging",
        lambda: "test.log",
    )

    class ForbiddenTradingBot:
        def __init__(self):
            raise AssertionError(
                "TradingBot must not be constructed "
                "for the sandbox close CLI."
            )

    monkeypatch.setattr(
        main_module,
        "TradingBot",
        ForbiddenTradingBot,
    )


def test_close_cli_calls_manual_service(
    monkeypatch,
    capsys,
):
    install_common(monkeypatch)

    service = FakeCloseService()

    monkeypatch.setattr(
        main_module,
        "build_webull_sandbox_manual_close_service",
        lambda: service,
    )

    monkeypatch.setattr(
        main_module.sys,
        "argv",
        [
            "main.py",
            "webull-sandbox-test-close",
            "SOUN",
            "1",
            "6.90",
            "CONFIRM_SANDBOX_CLOSE",
        ],
    )

    assert main_module.main() == 0

    output = capsys.readouterr().out

    assert (
        "WEBULL SANDBOX TEST CLOSE"
        in output
    )
    assert "Symbol: SOUN" in output
    assert "Side: SELL" in output
    assert "Quantity: 1" in output
    assert "Status: SUBMITTED" in output
    assert len(service.calls) == 1

    request = service.calls[0]

    assert request.symbol == "SOUN"
    assert request.quantity == 1
    assert request.limit_price == 6.90


def test_close_cli_rejects_wrong_confirmation(
    monkeypatch,
    capsys,
):
    install_common(monkeypatch)

    builder_calls = []

    monkeypatch.setattr(
        main_module,
        "build_webull_sandbox_manual_close_service",
        lambda: builder_calls.append(True),
    )

    monkeypatch.setattr(
        main_module.sys,
        "argv",
        [
            "main.py",
            "webull-sandbox-test-close",
            "SOUN",
            "1",
            "6.90",
            "WRONG",
        ],
    )

    assert main_module.main() == 2

    output = capsys.readouterr().out

    assert (
        "confirmation phrase was incorrect"
        in output
    )

    assert builder_calls == []


def test_close_cli_rejects_invalid_quantity(
    monkeypatch,
    capsys,
):
    install_common(monkeypatch)

    builder_calls = []

    monkeypatch.setattr(
        main_module,
        "build_webull_sandbox_manual_close_service",
        lambda: builder_calls.append(True),
    )

    monkeypatch.setattr(
        main_module.sys,
        "argv",
        [
            "main.py",
            "webull-sandbox-test-close",
            "SOUN",
            "not-a-number",
            "6.90",
            "CONFIRM_SANDBOX_CLOSE",
        ],
    )

    assert main_module.main() == 2

    output = capsys.readouterr().out

    assert (
        "Quantity must be an integer"
        in output
    )

    assert builder_calls == []


def test_close_cli_reports_service_failure(
    monkeypatch,
    capsys,
):
    install_common(monkeypatch)

    class FailingService:
        def close(self, request):
            raise RuntimeError(
                "SANDBOX_ORDER_MANAGEMENT_NOT_ARMED"
            )

    monkeypatch.setattr(
        main_module,
        "build_webull_sandbox_manual_close_service",
        lambda: FailingService(),
    )

    monkeypatch.setattr(
        main_module.sys,
        "argv",
        [
            "main.py",
            "webull-sandbox-test-close",
            "SOUN",
            "1",
            "6.90",
            "CONFIRM_SANDBOX_CLOSE",
        ],
    )

    assert main_module.main() == 1

    output = capsys.readouterr().out

    assert (
        "WEBULL SANDBOX TEST CLOSE FAILED"
        in output
    )

    assert (
        "SANDBOX_ORDER_MANAGEMENT_NOT_ARMED"
        in output
    )
