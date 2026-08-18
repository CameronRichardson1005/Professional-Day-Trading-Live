from __future__ import annotations

from decimal import Decimal, InvalidOperation
from queue import Full
from typing import Any, Callable


WEBULL_SANDBOX_EVENTS_HOST = (
    "events-api.sandbox.webull.com"
)

TRADE_EVENT_TYPE_ORDER = 1024
TRADE_ORDER_STATUS_CHANGED = 1

_SUPPORTED_SCENE_TYPES = {
    "FILLED",
    "FINAL_FILLED",
    "PLACE_FAILED",
    "MODIFY_SUCCESS",
    "MODIFY_FAILED",
    "CANCEL_SUCCESS",
    "CANCEL_FAILED",
}

_SUPPORTED_SIDES = {
    "BUY",
    "SELL",
}


class WebullTradeEventsWorkerError(
    RuntimeError
):
    pass


def _normalize_accounts(
    account_ids: Any,
) -> tuple[str, ...]:
    if not isinstance(
        account_ids,
        (
            list,
            tuple,
        ),
    ):
        raise WebullTradeEventsWorkerError(
            "TRADE_EVENTS_ACCOUNTS_INVALID"
        )

    result: list[str] = []
    seen: set[str] = set()

    for raw_value in account_ids:
        value = str(
            raw_value
        ).strip()

        if not value:
            raise WebullTradeEventsWorkerError(
                "TRADE_EVENTS_ACCOUNT_ID_REQUIRED"
            )

        if value in seen:
            continue

        seen.add(
            value
        )

        result.append(
            value
        )

    if not result:
        raise WebullTradeEventsWorkerError(
            "TRADE_EVENTS_ACCOUNTS_REQUIRED"
        )

    return tuple(
        result
    )


def _required_text(
    payload: dict[str, Any],
    field: str,
    *,
    uppercase: bool = False,
) -> str:
    value = payload.get(
        field
    )

    if value is None:
        raise WebullTradeEventsWorkerError(
            f"TRADE_EVENTS_{field.upper()}_REQUIRED"
        )

    text = str(
        value
    ).strip()

    if not text:
        raise WebullTradeEventsWorkerError(
            f"TRADE_EVENTS_{field.upper()}_REQUIRED"
        )

    if uppercase:
        text = text.upper()

    return text


def _optional_text(
    payload: dict[str, Any],
    field: str,
    *,
    uppercase: bool = False,
) -> str | None:
    value = payload.get(
        field
    )

    if value is None:
        return None

    text = str(
        value
    ).strip()

    if not text:
        return None

    if uppercase:
        text = text.upper()

    return text


def _numeric_text(
    payload: dict[str, Any],
    field: str,
    *,
    minimum: Decimal,
    required: bool,
) -> tuple[str | None, Decimal | None]:
    value = payload.get(
        field
    )

    if value is None:
        if required:
            raise WebullTradeEventsWorkerError(
                f"TRADE_EVENTS_{field.upper()}_REQUIRED"
            )

        return None, None

    if isinstance(
        value,
        bool,
    ):
        raise WebullTradeEventsWorkerError(
            f"TRADE_EVENTS_{field.upper()}_INVALID"
        )

    text = str(
        value
    ).strip()

    if not text:
        if required:
            raise WebullTradeEventsWorkerError(
                f"TRADE_EVENTS_{field.upper()}_REQUIRED"
            )

        return None, None

    try:
        number = Decimal(
            text
        )
    except (
        InvalidOperation,
        ValueError,
    ) as error:
        raise WebullTradeEventsWorkerError(
            f"TRADE_EVENTS_{field.upper()}_INVALID"
        ) from error

    if (
        not number.is_finite()
        or number < minimum
    ):
        raise WebullTradeEventsWorkerError(
            f"TRADE_EVENTS_{field.upper()}_INVALID"
        )

    return text, number


def sanitize_webull_order_event(
    payload: Any,
    *,
    subscribed_account_ids: Any,
) -> dict[str, Any]:
    if not isinstance(
        payload,
        dict,
    ):
        raise WebullTradeEventsWorkerError(
            "TRADE_EVENTS_PAYLOAD_INVALID"
        )

    accounts = set(
        _normalize_accounts(
            subscribed_account_ids
        )
    )

    account_id = _required_text(
        payload,
        "account_id",
    )

    if account_id not in accounts:
        raise WebullTradeEventsWorkerError(
            "TRADE_EVENTS_ACCOUNT_MISMATCH"
        )

    client_order_id = _required_text(
        payload,
        "client_order_id",
    )

    symbol = _required_text(
        payload,
        "symbol",
        uppercase=True,
    )

    side = _required_text(
        payload,
        "side",
        uppercase=True,
    )

    if side not in _SUPPORTED_SIDES:
        raise WebullTradeEventsWorkerError(
            "TRADE_EVENTS_SIDE_UNSUPPORTED"
        )

    order_status = _required_text(
        payload,
        "order_status",
        uppercase=True,
    )

    scene_type = _required_text(
        payload,
        "scene_type",
        uppercase=True,
    )

    if (
        scene_type
        not in _SUPPORTED_SCENE_TYPES
    ):
        raise WebullTradeEventsWorkerError(
            "TRADE_EVENTS_SCENE_TYPE_UNSUPPORTED"
        )

    quantity_text, _ = _numeric_text(
        payload,
        "qty",
        minimum=Decimal(
            "0.0000000001"
        ),
        required=True,
    )

    filled_quantity_text, (
        filled_quantity
    ) = _numeric_text(
        payload,
        "filled_qty",
        minimum=Decimal(
            "0"
        ),
        required=True,
    )

    assert filled_quantity is not None

    filled_price_text: str | None = None
    filled_time: str | None = None

    if filled_quantity > 0:
        filled_price_text, _ = _numeric_text(
            payload,
            "filled_price",
            minimum=Decimal(
                "0.0000000001"
            ),
            required=True,
        )

        filled_time = _required_text(
            payload,
            "filled_time",
        )
    else:
        filled_price_text, _ = _numeric_text(
            payload,
            "filled_price",
            minimum=Decimal(
                "0"
            ),
            required=False,
        )

        filled_time = _optional_text(
            payload,
            "filled_time",
        )

    envelope: dict[str, Any] = {
        "kind": "ORDER_STATUS_CHANGED",
        "account_id": account_id,
        "client_order_id": (
            client_order_id
        ),
        "symbol": symbol,
        "side": side,
        "order_status": order_status,
        "scene_type": scene_type,
        "qty": quantity_text,
        "filled_qty": (
            filled_quantity_text
        ),
    }

    order_id = _optional_text(
        payload,
        "order_id",
    )

    if order_id is not None:
        envelope[
            "order_id"
        ] = order_id

    category = _optional_text(
        payload,
        "category",
        uppercase=True,
    )

    if category is not None:
        envelope[
            "category"
        ] = category

    order_type = _optional_text(
        payload,
        "order_type",
        uppercase=True,
    )

    if order_type is not None:
        envelope[
            "order_type"
        ] = order_type

    if filled_price_text is not None:
        envelope[
            "filled_price"
        ] = filled_price_text

    if filled_time is not None:
        envelope[
            "filled_time"
        ] = filled_time

    return envelope


def _put_control_message(
    control_queue: Any,
    message: dict[str, str],
) -> None:
    try:
        control_queue.put_nowait(
            message
        )
    except Full as error:
        raise WebullTradeEventsWorkerError(
            "TRADE_EVENTS_CONTROL_QUEUE_FULL"
        ) from error
    except Exception as error:
        raise WebullTradeEventsWorkerError(
            "TRADE_EVENTS_CONTROL_QUEUE_WRITE_FAILED"
        ) from error


def make_webull_trade_events_callback(
    *,
    subscribed_account_ids: Any,
    event_queue: Any,
    control_queue: Any,
) -> Callable[
    [
        Any,
        Any,
        Any,
        Any,
    ],
    None,
]:
    accounts = _normalize_accounts(
        subscribed_account_ids
    )

    def callback(
        event_type: Any,
        subscribe_type: Any,
        payload: Any,
        raw_message: Any,
    ) -> None:
        del raw_message

        if (
            event_type
            != TRADE_EVENT_TYPE_ORDER
            or subscribe_type
            != TRADE_ORDER_STATUS_CHANGED
        ):
            return

        try:
            envelope = (
                sanitize_webull_order_event(
                    payload,
                    subscribed_account_ids=(
                        accounts
                    ),
                )
            )
        except WebullTradeEventsWorkerError as error:
            _put_control_message(
                control_queue,
                {
                    "type": "FATAL",
                    "reason": str(
                        error
                    ),
                },
            )

            raise

        try:
            event_queue.put_nowait(
                envelope
            )
        except Full as error:
            reason = (
                "TRADE_EVENTS_EVENT_QUEUE_FULL"
            )

            _put_control_message(
                control_queue,
                {
                    "type": "FATAL",
                    "reason": reason,
                },
            )

            raise WebullTradeEventsWorkerError(
                reason
            ) from error
        except Exception as error:
            reason = (
                "TRADE_EVENTS_EVENT_QUEUE_WRITE_FAILED"
            )

            _put_control_message(
                control_queue,
                {
                    "type": "FATAL",
                    "reason": reason,
                },
            )

            raise WebullTradeEventsWorkerError(
                reason
            ) from error

    return callback


def _create_sdk_trade_events_client(
    *,
    app_key: str,
    app_secret: str,
    host: str,
) -> Any:
    from webull.trade.events.default_retry_policy import (
        DefaultSubscribeRetryPolicy,
    )
    from webull.trade.trade_events_client import (
        TradeEventsClient,
    )

    retry_policy = (
        DefaultSubscribeRetryPolicy(
            # Webull rejects zero. One is the smallest
            # supported bounded retry count and avoids the
            # SDK's unlimited default retry behavior.
            max_retry_times=1,
        )
    )

    return TradeEventsClient(
        app_key,
        app_secret,
        "us",
        host=host,
        port=443,
        tls_enable=True,
        retry_policy=retry_policy,
    )


def run_webull_trade_events_worker(
    *,
    app_key: str,
    app_secret: str,
    account_ids: Any,
    event_queue: Any,
    control_queue: Any,
    host: str = (
        WEBULL_SANDBOX_EVENTS_HOST
    ),
    client_factory: (
        Callable[..., Any] | None
    ) = None,
) -> None:
    app_key = str(
        app_key
    ).strip()

    app_secret = str(
        app_secret
    ).strip()

    if not app_key:
        raise WebullTradeEventsWorkerError(
            "TRADE_EVENTS_APP_KEY_REQUIRED"
        )

    if not app_secret:
        raise WebullTradeEventsWorkerError(
            "TRADE_EVENTS_APP_SECRET_REQUIRED"
        )

    host = str(
        host
    ).strip().lower()

    if (
        host
        != WEBULL_SANDBOX_EVENTS_HOST
    ):
        raise WebullTradeEventsWorkerError(
            "TRADE_EVENTS_SANDBOX_HOST_REQUIRED"
        )

    accounts = _normalize_accounts(
        account_ids
    )

    callback = (
        make_webull_trade_events_callback(
            subscribed_account_ids=accounts,
            event_queue=event_queue,
            control_queue=control_queue,
        )
    )

    try:
        if client_factory is None:
            client = (
                _create_sdk_trade_events_client(
                    app_key=app_key,
                    app_secret=app_secret,
                    host=host,
                )
            )
        else:
            client = client_factory(
                app_key=app_key,
                app_secret=app_secret,
                host=host,
            )
    except Exception as error:
        reason = (
            "TRADE_EVENTS_CLIENT_CREATE_FAILED"
        )

        _put_control_message(
            control_queue,
            {
                "type": "FATAL",
                "reason": reason,
            },
        )

        raise WebullTradeEventsWorkerError(
            reason
        ) from error

    client.on_events_message = (
        callback
    )

    def on_connect(
        sdk_client: Any,
        payload: Any,
        raw_message: Any,
    ) -> None:
        del sdk_client
        del payload
        del raw_message

        _put_control_message(
            control_queue,
            {
                "type": "CONNECTED",
            },
        )

    client.on_connect = (
        on_connect
    )

    try:
        disable_logger = getattr(
            client,
            "disable_logger",
            None,
        )

        if callable(
            disable_logger
        ):
            disable_logger()

        client.on_log = None

        client.do_subscribe(
            list(
                accounts
            )
        )
    except WebullTradeEventsWorkerError:
        raise
    except Exception as error:
        reason = (
            "TRADE_EVENTS_STREAM_FAILED"
        )

        _put_control_message(
            control_queue,
            {
                "type": "FATAL",
                "reason": reason,
            },
        )

        raise WebullTradeEventsWorkerError(
            reason
        ) from error

    reason = (
        "TRADE_EVENTS_STREAM_RETURNED"
    )

    _put_control_message(
        control_queue,
        {
            "type": "FATAL",
            "reason": reason,
        },
    )

    raise WebullTradeEventsWorkerError(
        reason
    )
