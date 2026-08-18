from queue import Queue

import pytest

from trading_bot.webull_trade_events_worker import (
    TRADE_EVENT_TYPE_ORDER,
    TRADE_ORDER_STATUS_CHANGED,
    WEBULL_SANDBOX_EVENTS_HOST,
    WebullTradeEventsWorkerError,
    make_webull_trade_events_callback,
    run_webull_trade_events_worker,
    sanitize_webull_order_event,
)


def valid_payload():
    return {
        "request_id": "request-1",
        "account_id": "sandbox-1",
        "order_id": "broker-order-1",
        "client_order_id": "client-1",
        "instrument_id": "instrument-1",
        "order_status": "PARTIAL_FILLED",
        "symbol": "soun",
        "qty": "2.00",
        "filled_price": "4.25",
        "filled_qty": "1.00",
        "filled_time": (
            "2026-08-18T13:31:00.000Z"
        ),
        "side": "buy",
        "scene_type": "filled",
        "category": "us_stock",
        "order_type": "limit",
    }


def test_valid_partial_fill_is_sanitized():
    result = sanitize_webull_order_event(
        valid_payload(),
        subscribed_account_ids=(
            "sandbox-1",
        ),
    )

    assert result == {
        "kind": "ORDER_STATUS_CHANGED",
        "account_id": "sandbox-1",
        "client_order_id": "client-1",
        "symbol": "SOUN",
        "side": "BUY",
        "order_status": "PARTIAL_FILLED",
        "scene_type": "FILLED",
        "qty": "2.00",
        "filled_qty": "1.00",
        "order_id": "broker-order-1",
        "category": "US_STOCK",
        "order_type": "LIMIT",
        "filled_price": "4.25",
        "filled_time": (
            "2026-08-18T13:31:00.000Z"
        ),
    }


def test_unknown_fields_cannot_cross_boundary():
    payload = valid_payload()

    payload.update({
        "app_secret": "do-not-leak",
        "signature": "do-not-leak",
        "metadata": {
            "authorization": (
                "do-not-leak"
            ),
        },
        "fees": [
            {
                "type": "TEST",
                "actual_value": "999",
            }
        ],
    })

    result = sanitize_webull_order_event(
        payload,
        subscribed_account_ids=(
            "sandbox-1",
        ),
    )

    serialized = repr(
        result
    )

    assert "do-not-leak" not in serialized
    assert "app_secret" not in result
    assert "signature" not in result
    assert "metadata" not in result
    assert "fees" not in result


def test_zero_fill_can_omit_price_and_time():
    payload = valid_payload()

    payload["filled_qty"] = "0.000"
    payload.pop(
        "filled_price"
    )
    payload.pop(
        "filled_time"
    )

    result = sanitize_webull_order_event(
        payload,
        subscribed_account_ids=(
            "sandbox-1",
        ),
    )

    assert result[
        "filled_qty"
    ] == "0.000"

    assert (
        "filled_price"
        not in result
    )

    assert (
        "filled_time"
        not in result
    )


def test_account_mismatch_fails_closed():
    payload = valid_payload()

    payload[
        "account_id"
    ] = "different-account"

    with pytest.raises(
        WebullTradeEventsWorkerError,
        match=(
            "TRADE_EVENTS_ACCOUNT_MISMATCH"
        ),
    ):
        sanitize_webull_order_event(
            payload,
            subscribed_account_ids=(
                "sandbox-1",
            ),
        )


def test_unsupported_side_fails_closed():
    payload = valid_payload()

    payload[
        "side"
    ] = "SHORT"

    with pytest.raises(
        WebullTradeEventsWorkerError,
        match=(
            "TRADE_EVENTS_SIDE_UNSUPPORTED"
        ),
    ):
        sanitize_webull_order_event(
            payload,
            subscribed_account_ids=(
                "sandbox-1",
            ),
        )


def test_unknown_scene_fails_closed():
    payload = valid_payload()

    payload[
        "scene_type"
    ] = "UNKNOWN_NEW_SCENE"

    with pytest.raises(
        WebullTradeEventsWorkerError,
        match=(
            "TRADE_EVENTS_SCENE_TYPE_UNSUPPORTED"
        ),
    ):
        sanitize_webull_order_event(
            payload,
            subscribed_account_ids=(
                "sandbox-1",
            ),
        )


def test_positive_fill_requires_price():
    payload = valid_payload()

    payload.pop(
        "filled_price"
    )

    with pytest.raises(
        WebullTradeEventsWorkerError,
        match=(
            "TRADE_EVENTS_FILLED_PRICE_REQUIRED"
        ),
    ):
        sanitize_webull_order_event(
            payload,
            subscribed_account_ids=(
                "sandbox-1",
            ),
        )


def test_positive_fill_requires_time():
    payload = valid_payload()

    payload.pop(
        "filled_time"
    )

    with pytest.raises(
        WebullTradeEventsWorkerError,
        match=(
            "TRADE_EVENTS_FILLED_TIME_REQUIRED"
        ),
    ):
        sanitize_webull_order_event(
            payload,
            subscribed_account_ids=(
                "sandbox-1",
            ),
        )


def test_callback_ignores_non_order_event():
    events = Queue(
        maxsize=2
    )

    control = Queue(
        maxsize=2
    )

    callback = (
        make_webull_trade_events_callback(
            subscribed_account_ids=(
                "sandbox-1",
            ),
            event_queue=events,
            control_queue=control,
        )
    )

    callback(
        1028,
        2,
        {
            "secret": "ignored",
        },
        object(),
    )

    assert events.empty()
    assert control.empty()


def test_callback_queues_only_sanitized_event():
    events = Queue(
        maxsize=2
    )

    control = Queue(
        maxsize=2
    )

    callback = (
        make_webull_trade_events_callback(
            subscribed_account_ids=(
                "sandbox-1",
            ),
            event_queue=events,
            control_queue=control,
        )
    )

    payload = valid_payload()

    payload[
        "signature"
    ] = "must-not-cross"

    callback(
        TRADE_EVENT_TYPE_ORDER,
        TRADE_ORDER_STATUS_CHANGED,
        payload,
        {
            "raw_secret": (
                "must-not-cross"
            )
        },
    )

    event = (
        events.get_nowait()
    )

    assert (
        event[
            "client_order_id"
        ]
        == "client-1"
    )

    assert (
        "must-not-cross"
        not in repr(
            event
        )
    )

    assert control.empty()


def test_event_queue_overflow_is_fatal():
    events = Queue(
        maxsize=1
    )

    control = Queue(
        maxsize=2
    )

    events.put_nowait({
        "already": "full",
    })

    callback = (
        make_webull_trade_events_callback(
            subscribed_account_ids=(
                "sandbox-1",
            ),
            event_queue=events,
            control_queue=control,
        )
    )

    with pytest.raises(
        WebullTradeEventsWorkerError,
        match=(
            "TRADE_EVENTS_EVENT_QUEUE_FULL"
        ),
    ):
        callback(
            TRADE_EVENT_TYPE_ORDER,
            TRADE_ORDER_STATUS_CHANGED,
            valid_payload(),
            object(),
        )

    fatal = control.get_nowait()

    assert fatal == {
        "type": "FATAL",
        "reason": (
            "TRADE_EVENTS_EVENT_QUEUE_FULL"
        ),
    }


class FakeStreamingClient:
    def __init__(
        self,
    ):
        self.on_events_message = None
        self.on_connect = None
        self.on_log = "not-none"
        self.disable_logger_calls = 0
        self.accounts = None

    def disable_logger(
        self,
    ):
        self.disable_logger_calls += 1

    def do_subscribe(
        self,
        accounts,
    ):
        self.accounts = accounts

        self.on_connect(
            self,
            {
                "raw": "not-forwarded",
            },
            object(),
        )

        raise RuntimeError(
            "simulated stream loss"
        )


def test_worker_uses_sandbox_boundary_without_network():
    events = Queue(
        maxsize=5
    )

    control = Queue(
        maxsize=5
    )

    captured = {}
    fake_client = FakeStreamingClient()

    def factory(
        *,
        app_key,
        app_secret,
        host,
    ):
        captured[
            "app_key"
        ] = app_key

        captured[
            "app_secret"
        ] = app_secret

        captured[
            "host"
        ] = host

        return fake_client

    with pytest.raises(
        WebullTradeEventsWorkerError,
        match=(
            "TRADE_EVENTS_STREAM_FAILED"
        ),
    ):
        run_webull_trade_events_worker(
            app_key="test-key",
            app_secret="test-secret",
            account_ids=(
                "sandbox-1",
            ),
            event_queue=events,
            control_queue=control,
            client_factory=factory,
        )

    assert (
        captured["host"]
        == WEBULL_SANDBOX_EVENTS_HOST
    )

    assert fake_client.accounts == [
        "sandbox-1",
    ]

    assert (
        fake_client.disable_logger_calls
        == 1
    )

    assert fake_client.on_log is None

    first = control.get_nowait()
    second = control.get_nowait()

    assert first == {
        "type": "CONNECTED",
    }

    assert second == {
        "type": "FATAL",
        "reason": (
            "TRADE_EVENTS_STREAM_FAILED"
        ),
    }

    control_text = repr(
        (
            first,
            second,
        )
    )

    assert (
        "test-key"
        not in control_text
    )

    assert (
        "test-secret"
        not in control_text
    )


def test_production_host_is_rejected_before_client_creation():
    events = Queue(
        maxsize=2
    )

    control = Queue(
        maxsize=2
    )

    factory_calls = []

    def factory(
        **kwargs,
    ):
        factory_calls.append(
            kwargs
        )

        raise AssertionError(
            "factory must not run"
        )

    with pytest.raises(
        WebullTradeEventsWorkerError,
        match=(
            "TRADE_EVENTS_SANDBOX_HOST_REQUIRED"
        ),
    ):
        run_webull_trade_events_worker(
            app_key="test-key",
            app_secret="test-secret",
            account_ids=(
                "sandbox-1",
            ),
            event_queue=events,
            control_queue=control,
            host=(
                "events-api.webull.com"
            ),
            client_factory=factory,
        )

    assert factory_calls == []


def test_real_sdk_client_factory_constructs_without_network():
    """
    Regression for Webull SDK rejecting max_retry_times=0.

    Providing an explicit host means TradeEventsClient
    construction does not perform endpoint discovery, and this
    test deliberately never calls do_subscribe().
    """

    from trading_bot.webull_trade_events_worker import (
        _create_sdk_trade_events_client,
    )

    client = _create_sdk_trade_events_client(
        app_key="dummy-app-key",
        app_secret="dummy-app-secret",
        host="events-api.sandbox.webull.com",
    )

    assert client is not None

    assert (
        getattr(
            client,
            "_host",
            None,
        )
        == "events-api.sandbox.webull.com"
    )

    assert (
        getattr(
            client,
            "_port",
            None,
        )
        == 443
    )

    assert (
        getattr(
            client,
            "_tls_enable",
            None,
        )
        is True
    )


def test_client_creation_failure_publishes_fatal_control():
    from queue import Queue

    events = Queue(
        maxsize=2
    )

    control = Queue(
        maxsize=2
    )

    def failing_factory(
        **kwargs,
    ):
        del kwargs

        raise RuntimeError(
            "secret underlying SDK failure"
        )

    with pytest.raises(
        WebullTradeEventsWorkerError,
        match=(
            "TRADE_EVENTS_CLIENT_CREATE_FAILED"
        ),
    ):
        run_webull_trade_events_worker(
            app_key="test-key",
            app_secret="test-secret",
            account_ids=(
                "sandbox-1",
            ),
            event_queue=events,
            control_queue=control,
            host=(
                "events-api.sandbox.webull.com"
            ),
            client_factory=(
                failing_factory
            ),
        )

    assert control.get_nowait() == {
        "type": "FATAL",
        "reason": (
            "TRADE_EVENTS_CLIENT_CREATE_FAILED"
        ),
    }

    assert events.empty()
