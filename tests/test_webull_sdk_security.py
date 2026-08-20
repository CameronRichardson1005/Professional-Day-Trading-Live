import logging

import webull.core.client as webull_core_client
from webull.core.http.initializer.client_initializer import (
    ClientInitializer,
)

import trading_bot.webull_preview_client as preview_module
from trading_bot.webull_preview_client import (
    WebullPreviewClient,
)


def test_preview_client_does_not_install_raw_sdk_log_routes(
        monkeypatch,
        tmp_path,
        capsys,
):
    fake_token = "fake-access-token-must-not-appear"
    fake_account = "fake-account-id-must-not-appear"

    sdk_logger = logging.getLogger("webull.core")
    response_logger = logging.getLogger(
        "webull.core.http.response"
    )

    original_sdk_state = (
        list(sdk_logger.handlers),
        sdk_logger.level,
        sdk_logger.disabled,
        sdk_logger.propagate,
    )
    original_response_state = (
        list(response_logger.handlers),
        response_logger.level,
        response_logger.disabled,
        response_logger.propagate,
    )

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        preview_module,
        "WEBULL_APP_KEY",
        "fake-app-key",
    )
    monkeypatch.setattr(
        preview_module,
        "WEBULL_APP_SECRET",
        "fake-app-secret",
    )
    monkeypatch.setattr(
        ClientInitializer,
        "initializer",
        lambda api_client: None,
    )

    try:
        WebullPreviewClient()

        webull_core_client.logger.error(
            "Request headers: x-access-token=%s; "
            "account_id=%s",
            fake_token,
            fake_account,
        )

        for handler in sdk_logger.handlers:
            handler.flush()

        captured = capsys.readouterr()
        combined_output = captured.out + captured.err

        assert fake_token not in combined_output
        assert fake_account not in combined_output
        assert not (
            tmp_path / "webull_trade_sdk.log"
        ).exists()
    finally:
        for handler in list(sdk_logger.handlers):
            if handler not in original_sdk_state[0]:
                sdk_logger.removeHandler(handler)
                handler.close()

        sdk_logger.handlers = original_sdk_state[0]
        sdk_logger.setLevel(original_sdk_state[1])
        sdk_logger.disabled = original_sdk_state[2]
        sdk_logger.propagate = original_sdk_state[3]

        response_logger.handlers = (
            original_response_state[0]
        )
        response_logger.setLevel(
            original_response_state[1]
        )
        response_logger.disabled = (
            original_response_state[2]
        )
        response_logger.propagate = (
            original_response_state[3]
        )
