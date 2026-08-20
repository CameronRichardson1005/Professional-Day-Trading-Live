from __future__ import annotations

import logging
from typing import Any

from webull.core.client import ApiClient


WEBULL_SDK_LOGGER_NAMES = (
    "webull.core",
    "webull.core.http.response",
)


def disable_webull_sdk_request_logging(
        api_client: Any,
) -> None:
    """
    Prevent the SDK from serializing signed requests.

    Webull's client installs console and rotating-file handlers
    unless it sees logging as already configured. Its error path
    includes authentication headers and account identifiers, so
    application-level response sanitizing happens too late.
    """
    for logger_name in WEBULL_SDK_LOGGER_NAMES:
        logger = logging.getLogger(logger_name)

        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            handler.close()

        logger.addHandler(
            logging.NullHandler()
        )
        logger.disabled = True
        logger.propagate = False

    # These are the flags used by Webull's TradeClient and
    # DataClient to decide whether to install their unsafe
    # default console and file handlers.
    api_client._stream_logger_set = True
    api_client._file_logger_set = True


def build_secure_webull_api_client(
        app_key: str,
        app_secret: str,
) -> ApiClient:
    api_client = ApiClient(
        app_key,
        app_secret,
        "us",
    )

    api_client.add_endpoint(
        "us",
        "api.webull.com",
    )

    disable_webull_sdk_request_logging(
        api_client
    )

    return api_client
