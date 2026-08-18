from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from trading_bot.webull_strict_daily_pnl import (
    WebullStrictDailyPnlError,
    WebullStrictDailyRealizedPnlProvider,
)


EASTERN = ZoneInfo(
    "America/New_York"
)


def milliseconds(
    *,
    day,
    hour=10,
):
    value = datetime(
        2026,
        8,
        day,
        hour,
        0,
        tzinfo=EASTERN,
    )

    return int(
        value.timestamp()
        * 1000
    )


def order_group(
    key,
    *,
    symbol="SOUN",
    side,
    quantity,
    price,
    day,
    status="FILLED",
):
    return {
        "client_order_id": key,
        "orders": [
            {
                "client_order_id": key,
                "symbol": symbol,
                "side": side,
                "status": status,
                "filled_quantity": (
                    str(quantity)
                ),
                "filled_price": (
                    str(price)
                ),
                "filled_time": (
                    milliseconds(
                        day=day
                    )
                ),
            }
        ],
    }


class FakeHistoryReader:
    def __init__(
        self,
        payload,
        *,
        error=None,
    ):
        self.payload = payload
        self.error = error
        self.calls = []

    def get_history_payload(
        self,
        *,
        start_date,
        end_date,
    ):
        self.calls.append({
            "start_date": start_date,
            "end_date": end_date,
        })

        if self.error is not None:
            raise self.error

        return self.payload


def provider(
    payload,
    *,
    trading_date="2026-08-18",
    history_start="2026-08-01",
):
    reader = FakeHistoryReader(
        payload
    )

    result = (
        WebullStrictDailyRealizedPnlProvider(
            history_reader=reader,
            trading_date_provider=(
                lambda: trading_date
            ),
            history_start_date=(
                history_start
            ),
        )
    )

    return result, reader


def test_overnight_fifo_realized_loss():
    pnl, reader = provider([
        order_group(
            "buy-1",
            side="BUY",
            quantity=10,
            price=10.0,
            day=17,
        ),
        order_group(
            "sell-1",
            side="SELL",
            quantity=10,
            price=9.5,
            day=18,
        ),
    ])

    assert pnl() == -5.0

    assert reader.calls == [
        {
            "start_date": (
                "2026-08-01"
            ),
            "end_date": (
                "2026-08-19"
            ),
        }
    ]


def test_profitable_realized_trade():
    pnl, _ = provider([
        order_group(
            "buy-1",
            side="BUY",
            quantity=5,
            price=10.0,
            day=17,
        ),
        order_group(
            "sell-1",
            side="SELL",
            quantity=5,
            price=11.0,
            day=18,
        ),
    ])

    assert pnl() == 5.0


def test_cancelled_partial_fill_is_included():
    pnl, _ = provider([
        order_group(
            "buy-1",
            side="BUY",
            quantity=2,
            price=10.0,
            day=17,
            status="CANCELLED",
        ),
        order_group(
            "sell-1",
            side="SELL",
            quantity=2,
            price=9.0,
            day=18,
        ),
    ])

    assert pnl() == -2.0


def test_future_day_fill_does_not_change_target_pnl():
    pnl, _ = provider([
        order_group(
            "buy-1",
            side="BUY",
            quantity=1,
            price=10.0,
            day=17,
        ),
        order_group(
            "sell-1",
            side="SELL",
            quantity=1,
            price=9.0,
            day=18,
        ),
        order_group(
            "buy-future",
            side="BUY",
            quantity=100,
            price=1.0,
            day=19,
        ),
    ])

    assert pnl() == -1.0


def test_unmatched_sell_fails_closed():
    pnl, _ = provider([
        order_group(
            "sell-1",
            side="SELL",
            quantity=1,
            price=10.0,
            day=18,
        ),
    ])

    with pytest.raises(
        WebullStrictDailyPnlError,
        match=(
            "^STRICT_PNL_CALCULATION_FAILED$"
        ),
    ):
        pnl()


def test_malformed_positive_fill_fails_closed():
    payload = [
        {
            "client_order_id": (
                "bad-1"
            ),
            "orders": [
                {
                    "client_order_id": (
                        "bad-1"
                    ),
                    "symbol": "SOUN",
                    "side": "BUY",
                    "status": "FILLED",
                    "filled_quantity": "1",
                    "filled_time": (
                        milliseconds(
                            day=18
                        )
                    ),
                }
            ],
        }
    ]

    pnl, _ = provider(
        payload
    )

    with pytest.raises(
        WebullStrictDailyPnlError,
        match=(
            "^STRICT_PNL_HISTORY_INVALID$"
        ),
    ):
        pnl()


def test_history_reader_failure_fails_closed():
    reader = FakeHistoryReader(
        [],
        error=RuntimeError(
            "simulated"
        ),
    )

    pnl = (
        WebullStrictDailyRealizedPnlProvider(
            history_reader=reader,
            trading_date_provider=(
                lambda: "2026-08-18"
            ),
            history_start_date=(
                "2026-08-01"
            ),
        )
    )

    with pytest.raises(
        WebullStrictDailyPnlError,
        match=(
            "^STRICT_PNL_HISTORY_UNAVAILABLE$"
        ),
    ):
        pnl()


def test_history_start_date_is_explicit_and_enforced():
    pnl, reader = provider(
        [],
        trading_date="2026-08-18",
        history_start="2026-08-19",
    )

    with pytest.raises(
        WebullStrictDailyPnlError,
        match=(
            "^STRICT_PNL_DATE_BEFORE_HISTORY_START$"
        ),
    ):
        pnl()

    assert reader.calls == []


def test_invalid_trading_date_fails_before_history():
    pnl, reader = provider(
        [],
        trading_date="not-a-date",
    )

    with pytest.raises(
        WebullStrictDailyPnlError,
        match=(
            "^STRICT_PNL_TRADING_DATE_INVALID$"
        ),
    ):
        pnl()

    assert reader.calls == []


def test_invalid_history_reader_is_rejected():
    with pytest.raises(
        WebullStrictDailyPnlError,
        match=(
            "^STRICT_PNL_HISTORY_READER_INVALID$"
        ),
    ):
        WebullStrictDailyRealizedPnlProvider(
            history_reader=object(),
            trading_date_provider=(
                lambda: "2026-08-18"
            ),
            history_start_date=(
                "2026-08-01"
            ),
        )


def test_invalid_date_provider_is_rejected():
    with pytest.raises(
        WebullStrictDailyPnlError,
        match=(
            "^STRICT_PNL_DATE_PROVIDER_INVALID$"
        ),
    ):
        WebullStrictDailyRealizedPnlProvider(
            history_reader=(
                FakeHistoryReader([])
            ),
            trading_date_provider=None,
            history_start_date=(
                "2026-08-01"
            ),
        )


def test_invalid_history_start_date_is_rejected():
    with pytest.raises(
        WebullStrictDailyPnlError,
        match=(
            "^STRICT_PNL_HISTORY_START_DATE_INVALID$"
        ),
    ):
        WebullStrictDailyRealizedPnlProvider(
            history_reader=(
                FakeHistoryReader([])
            ),
            trading_date_provider=(
                lambda: "2026-08-18"
            ),
            history_start_date="bad",
        )
