from types import SimpleNamespace

import main as main_module


class FakeService:
    def __init__(self):
        self.requests = []
        self.cancel_requests = []

    def place(self, request):
        self.requests.append(request)

        return SimpleNamespace(
            client_order_id="manual-1",
            symbol=request.symbol,
            quantity=request.quantity,
            limit_price=request.limit_price,
            status="SUBMITTED",
            broker_order_id="broker-1",
            broker_status="SUBMITTED",
        )

    def cancel(
        self,
        *,
        client_order_id,
        confirmation,
    ):
        self.cancel_requests.append(
            (
                client_order_id,
                confirmation,
            )
        )

        return SimpleNamespace(
            client_order_id=client_order_id,
            symbol="SOUN",
            status="CANCELLED",
            broker_status="CANCELLED",
            manual_override=True,
        )


def test_manual_sandbox_cli_requires_confirmation(
    monkeypatch,
    capsys,
):
    monkeypatch.setattr(
        main_module,
        "setup_logging",
        lambda: "test.log",
    )

    monkeypatch.setattr(
        main_module.sys,
        "argv",
        [
            "main.py",
            "webull-sandbox-test-order",
            "SOUN",
            "1",
            "5.25",
            "WRONG",
        ],
    )

    result = main_module.main()

    assert result == 2

    output = capsys.readouterr().out

    assert (
        "confirmation phrase was incorrect"
        in output
    )


def test_manual_sandbox_cli_runs_before_bot(
    monkeypatch,
    capsys,
):
    service = FakeService()

    monkeypatch.setattr(
        main_module,
        "setup_logging",
        lambda: "test.log",
    )

    monkeypatch.setattr(
        main_module,
        "build_webull_sandbox_manual_order_service",
        lambda: service,
    )

    class ForbiddenTradingBot:
        def __init__(self):
            raise AssertionError(
                "TradingBot must not be constructed."
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
            "webull-sandbox-test-order",
            "SOUN",
            "1",
            "5.25",
            "CONFIRM_SANDBOX_ORDER",
        ],
    )

    result = main_module.main()

    assert result == 0
    assert len(service.requests) == 1

    output = capsys.readouterr().out

    assert (
        "WEBULL SANDBOX TEST ORDER"
        in output
    )

    assert (
        "NO LIVE WEBULL ORDER WAS PLACED"
        in output
    )



def test_manual_sandbox_cancel_cli(
    monkeypatch,
    capsys,
):
    service = FakeService()

    monkeypatch.setattr(
        main_module,
        "setup_logging",
        lambda: "test.log",
    )

    monkeypatch.setattr(
        main_module,
        "build_webull_sandbox_manual_order_service",
        lambda: service,
    )

    class ForbiddenTradingBot:
        def __init__(self):
            raise AssertionError(
                "TradingBot must not be constructed."
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
            "webull-sandbox-test-cancel",
            "manual-1",
            "CONFIRM_SANDBOX_CANCEL",
        ],
    )

    result = main_module.main()

    assert result == 0

    assert service.cancel_requests == [
        (
            "manual-1",
            "CONFIRM_SANDBOX_CANCEL",
        )
    ]

    output = capsys.readouterr().out

    assert (
        "WEBULL SANDBOX TEST CANCEL"
        in output
    )

    assert (
        "Status: CANCELLED"
        in output
    )

    assert (
        "NO LIVE WEBULL ORDER WAS MODIFIED"
        in output
    )
