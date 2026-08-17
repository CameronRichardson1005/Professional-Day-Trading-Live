from __future__ import annotations

import logging

from webull.core.client import ApiClient
from webull.trade.trade_client import TradeClient


class WebullSdkSafetyError(RuntimeError):
    pass


def suppress_webull_sdk_logging() -> None:
    """
    Prevent Webull SDK request details, authentication headers,
    signatures, and credentials from propagating into our logs.
    """

    for name in (
        "webull",
        "webull.core",
        "webull.core.client",
    ):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = False
        logger.setLevel(logging.CRITICAL + 1)

    for name, candidate in list(
        logging.Logger.manager.loggerDict.items()
    ):
        if not (
            name == "webull"
            or name.startswith("webull.")
        ):
            continue

        if not isinstance(candidate, logging.Logger):
            continue

        candidate.handlers.clear()
        candidate.propagate = False
        candidate.setLevel(logging.CRITICAL + 1)


def build_quiet_trade_client(
    *,
    app_key: str,
    app_secret: str,
    endpoint: str,
) -> TradeClient:
    key = app_key.strip()
    secret = app_secret.strip()
    host = endpoint.strip()

    if not key:
        raise WebullSdkSafetyError(
            "WEBULL_APP_KEY_REQUIRED"
        )

    if not secret:
        raise WebullSdkSafetyError(
            "WEBULL_APP_SECRET_REQUIRED"
        )

    if not host:
        raise WebullSdkSafetyError(
            "WEBULL_ENDPOINT_REQUIRED"
        )

    suppress_webull_sdk_logging()

    api_client = ApiClient(
        key,
        secret,
        "us",
    )

    api_client.add_endpoint(
        "us",
        host,
    )

    # Installed Webull SDK TradeClient automatically enables
    # stream/file logging unless these are already marked set.
    api_client._stream_logger_set = True
    api_client._file_logger_set = True

    trade_client = TradeClient(api_client)

    suppress_webull_sdk_logging()

    return trade_client
