import logging

import pytest

import trading_bot.webull_sdk_safety as safety


class FakeApiClient:
    def __init__(
        self,
        app_key,
        app_secret,
        region,
    ):
        self.app_key = app_key
        self.app_secret = app_secret
        self.region = region
        self.endpoints = []

    def add_endpoint(
        self,
        region,
        endpoint,
    ):
        self.endpoints.append(
            (region, endpoint)
        )


class FakeTradeClient:
    def __init__(
        self,
        api_client,
    ):
        assert api_client._stream_logger_set is True
        assert api_client._file_logger_set is True
        self.api_client = api_client


def test_quiet_trade_client_disarms_default_logging(
    monkeypatch,
):
    monkeypatch.setattr(
        safety,
        "ApiClient",
        FakeApiClient,
    )

    monkeypatch.setattr(
        safety,
        "TradeClient",
        FakeTradeClient,
    )

    client = safety.build_quiet_trade_client(
        app_key="key",
        app_secret="secret",
        endpoint="api.sandbox.webull.com",
    )

    api_client = client.api_client

    assert api_client.region == "us"

    assert api_client.endpoints == [
        (
            "us",
            "api.sandbox.webull.com",
        )
    ]

    assert api_client._stream_logger_set
    assert api_client._file_logger_set


def test_webull_loggers_do_not_propagate():
    safety.suppress_webull_sdk_logging()

    logger = logging.getLogger("webull")

    assert logger.handlers == []
    assert logger.propagate is False
    assert logger.level > logging.CRITICAL


@pytest.mark.parametrize(
    "key,secret,endpoint,error",
    [
        ("", "secret", "host", "WEBULL_APP_KEY_REQUIRED"),
        ("key", "", "host", "WEBULL_APP_SECRET_REQUIRED"),
        ("key", "secret", "", "WEBULL_ENDPOINT_REQUIRED"),
    ],
)
def test_invalid_configuration_fails_closed(
    key,
    secret,
    endpoint,
    error,
):
    with pytest.raises(
        safety.WebullSdkSafetyError,
        match=error,
    ):
        safety.build_quiet_trade_client(
            app_key=key,
            app_secret=secret,
            endpoint=endpoint,
        )
