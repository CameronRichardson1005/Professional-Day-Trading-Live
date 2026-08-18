import pytest

from trading_bot.webull_broker_history import (
    WebullBrokerHistoryError,
    WebullStrictBrokerHistoryReader,
)


class FakeResponse:
    def __init__(
        self,
        payload,
        *,
        status_code=200,
    ):
        self.payload = payload
        self.status_code = (
            status_code
        )

    def json(
        self,
    ):
        return self.payload


class FakeOrderV3:
    def __init__(
        self,
        pages,
    ):
        self.pages = pages
        self.calls = []

    def get_order_history(
        self,
        account_id,
        page_size=None,
        start_date=None,
        end_date=None,
        last_client_order_id=None,
    ):
        self.calls.append({
            "account_id": (
                account_id
            ),
            "page_size": (
                page_size
            ),
            "start_date": (
                start_date
            ),
            "end_date": (
                end_date
            ),
            "last_client_order_id": (
                last_client_order_id
            ),
        })

        return FakeResponse(
            self.pages.get(
                last_client_order_id,
                [],
            )
        )


class FakeTradeClient:
    def __init__(
        self,
        pages,
    ):
        self.order_v3 = FakeOrderV3(
            pages
        )


def group(
    key,
    *,
    symbol="SOUN",
):
    return {
        "client_order_id": key,
        "combo_type": "NORMAL",
        "orders": [
            {
                "client_order_id": (
                    key
                ),
                "symbol": symbol,
            }
        ],
    }


def reader(
    pages,
    **kwargs,
):
    client = FakeTradeClient(
        pages
    )

    result = (
        WebullStrictBrokerHistoryReader(
            trade_client=client,
            account_id="sandbox-1",
            **kwargs,
        )
    )

    return result, client


def test_history_reader_paginates_until_empty_page():
    history, client = reader({
        None: [
            group("order-1"),
            group("order-2"),
        ],
        "order-2": [
            group("order-3"),
        ],
        "order-3": [],
    })

    payload = (
        history.get_history_payload(
            start_date="2026-08-01",
            end_date="2026-08-18",
        )
    )

    assert [
        item[
            "client_order_id"
        ]
        for item in payload
    ] == [
        "order-1",
        "order-2",
        "order-3",
    ]

    assert [
        call[
            "last_client_order_id"
        ]
        for call
        in client.order_v3.calls
    ] == [
        None,
        "order-2",
        "order-3",
    ]


def test_exact_duplicate_across_pages_is_deduplicated():
    history, _ = reader({
        None: [
            group("order-1"),
            group("order-2"),
        ],
        "order-2": [
            group("order-2"),
            group("order-3"),
        ],
        "order-3": [],
    })

    payload = (
        history.get_history_payload(
            start_date="2026-08-01",
            end_date="2026-08-18",
        )
    )

    assert len(payload) == 3

    assert [
        item[
            "client_order_id"
        ]
        for item in payload
    ] == [
        "order-1",
        "order-2",
        "order-3",
    ]


def test_conflicting_duplicate_fails_closed():
    changed = group(
        "order-2",
        symbol="BBAI",
    )

    history, _ = reader({
        None: [
            group("order-1"),
            group("order-2"),
        ],
        "order-2": [
            changed,
            group("order-3"),
        ],
    })

    with pytest.raises(
        WebullBrokerHistoryError,
        match=(
            "HISTORY_DUPLICATE_GROUP_CONFLICT"
        ),
    ):
        history.get_history_payload(
            start_date="2026-08-01",
            end_date="2026-08-18",
        )


def test_nonadvancing_cursor_fails_closed():
    history, _ = reader({
        None: [
            group("order-1"),
        ],
        "order-1": [
            group("order-1"),
        ],
    })

    with pytest.raises(
        WebullBrokerHistoryError,
        match=(
            "HISTORY_CURSOR_DID_NOT_ADVANCE"
        ),
    ):
        history.get_history_payload(
            start_date="2026-08-01",
            end_date="2026-08-18",
        )


def test_missing_group_cursor_fails_closed():
    history, _ = reader({
        None: [
            {
                "combo_type": "NORMAL",
                "orders": [
                    {
                        "symbol": "SOUN",
                    }
                ],
            }
        ],
    })

    with pytest.raises(
        WebullBrokerHistoryError,
        match=(
            "HISTORY_GROUP_CURSOR_MISSING"
        ),
    ):
        history.get_history_payload(
            start_date="2026-08-01",
            end_date="2026-08-18",
        )


def test_nested_single_client_id_can_supply_cursor():
    history, _ = reader({
        None: [
            {
                "combo_type": "NORMAL",
                "orders": [
                    {
                        "client_order_id": (
                            "order-1"
                        ),
                        "symbol": "SOUN",
                    }
                ],
            }
        ],
        "order-1": [],
    })

    payload = (
        history.get_history_payload(
            start_date="2026-08-01",
            end_date="2026-08-18",
        )
    )

    assert len(payload) == 1


def test_invalid_same_day_range_fails_before_network():
    history, client = reader({
        None: [],
    })

    with pytest.raises(
        WebullBrokerHistoryError,
        match="HISTORY_DATE_RANGE_INVALID",
    ):
        history.get_history_payload(
            start_date="2026-08-18",
            end_date="2026-08-18",
        )

    assert (
        client.order_v3.calls
        == []
    )


def test_more_than_two_year_range_fails_closed():
    history, client = reader({
        None: [],
    })

    with pytest.raises(
        WebullBrokerHistoryError,
        match=(
            "HISTORY_DATE_RANGE_TOO_LARGE"
        ),
    ):
        history.get_history_payload(
            start_date="2024-08-17",
            end_date="2026-08-18",
        )

    assert (
        client.order_v3.calls
        == []
    )


def test_page_size_above_webull_limit_rejected():
    with pytest.raises(
        WebullBrokerHistoryError,
        match="HISTORY_PAGE_SIZE_INVALID",
    ):
        WebullStrictBrokerHistoryReader(
            trade_client=FakeTradeClient(
                {}
            ),
            account_id="sandbox-1",
            page_size=101,
        )


def test_max_pages_guard_fails_closed():
    history, _ = reader(
        {
            None: [
                group("order-1"),
            ],
            "order-1": [
                group("order-2"),
            ],
        },
        max_pages=2,
    )

    with pytest.raises(
        WebullBrokerHistoryError,
        match="HISTORY_MAX_PAGES_EXCEEDED",
    ):
        history.get_history_payload(
            start_date="2026-08-01",
            end_date="2026-08-18",
        )
