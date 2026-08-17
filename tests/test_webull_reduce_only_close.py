import stat

from datetime import UTC, datetime

import pytest

from trading_bot.webull_account_parser import (
    ParsedWebullPosition,
)
from trading_bot.webull_execution import (
    WebullExecutionError,
    WebullTradeIntent,
)
from trading_bot.webull_reduce_only_close import (
    WebullReduceOnlyCloseError,
    WebullReduceOnlyCloseLedger,
    build_reduce_only_close_intent,
    select_reduce_only_position,
)


NOW = datetime(
    2026,
    8,
    17,
    20,
    0,
    tzinfo=UTC,
)


def position(
    *,
    symbol="SOUN",
    quantity=3.0,
    market_price=7.00,
):
    return ParsedWebullPosition(
        symbol=symbol,
        quantity=quantity,
        market_price=market_price,
        market_value=round(
            quantity * market_price,
            2,
        ),
    )


def test_existing_trade_intent_remains_buy_only():
    with pytest.raises(
        WebullExecutionError,
        match="ONLY_BUY_INTENTS_SUPPORTED",
    ):
        WebullTradeIntent(
            client_order_id="sell-not-allowed",
            strategy_name="QUICK_FLIP",
            symbol="SOUN",
            side="SELL",
            quantity=1,
            limit_price=7.00,
            created_at=NOW,
        )


def test_reduce_only_close_builds_sell_payload():
    intent = build_reduce_only_close_intent(
        client_order_id="close-1",
        positions=(position(),),
        symbol="soun",
        quantity=2,
        limit_price=6.90,
        created_at=NOW,
    )

    assert intent.side == "SELL"

    assert (
        intent.confirmed_position_quantity
        == 3.0
    )

    assert intent.broker_payload() == {
        "combo_type": "NORMAL",
        "client_order_id": "close-1",
        "symbol": "SOUN",
        "instrument_type": "EQUITY",
        "market": "US",
        "order_type": "LIMIT",
        "limit_price": "6.9000",
        "quantity": "2",
        "support_trading_session": "CORE",
        "side": "SELL",
        "time_in_force": "DAY",
        "entrust_type": "QTY",
    }


def test_close_cannot_exceed_confirmed_position():
    with pytest.raises(
        WebullReduceOnlyCloseError,
        match="CLOSE_QUANTITY_EXCEEDS_POSITION",
    ):
        build_reduce_only_close_intent(
            client_order_id="close-1",
            positions=(position(quantity=1),),
            symbol="SOUN",
            quantity=2,
            limit_price=6.90,
            created_at=NOW,
        )


def test_close_requires_existing_long_position():
    with pytest.raises(
        WebullReduceOnlyCloseError,
        match="LONG_POSITION_NOT_FOUND",
    ):
        build_reduce_only_close_intent(
            client_order_id="close-1",
            positions=(),
            symbol="SOUN",
            quantity=1,
            limit_price=6.90,
            created_at=NOW,
        )


def test_duplicate_symbol_positions_fail_closed():
    with pytest.raises(
        WebullReduceOnlyCloseError,
        match="DUPLICATE_POSITION_RECORD",
    ):
        select_reduce_only_position(
            positions=(
                position(quantity=1),
                position(quantity=2),
            ),
            symbol="SOUN",
        )


def test_close_ledger_round_trip(tmp_path):
    ledger = WebullReduceOnlyCloseLedger(
        tmp_path / "close.json",
        clock=lambda: NOW,
    )

    intent = build_reduce_only_close_intent(
        client_order_id="close-1",
        positions=(position(),),
        symbol="SOUN",
        quantity=1,
        limit_price=6.90,
        created_at=NOW,
    )

    saved = ledger.add_intent(intent)

    assert saved.status == "PREPARED"
    assert saved.side == "SELL"
    assert saved.quantity == 1
    assert saved.confirmed_position_quantity == 3.0

    loaded = ledger.load()

    assert loaded["close-1"] == saved

    permissions = stat.S_IMODE(
        (tmp_path / "close.json")
        .stat()
        .st_mode
    )

    assert permissions == 0o600


def test_duplicate_close_id_rejected(tmp_path):
    ledger = WebullReduceOnlyCloseLedger(
        tmp_path / "close.json",
        clock=lambda: NOW,
    )

    intent = build_reduce_only_close_intent(
        client_order_id="close-1",
        positions=(position(),),
        symbol="SOUN",
        quantity=1,
        limit_price=6.90,
        created_at=NOW,
    )

    ledger.add_intent(intent)

    with pytest.raises(
        WebullReduceOnlyCloseError,
        match="DUPLICATE_CLIENT_ORDER_ID",
    ):
        ledger.add_intent(intent)


def test_close_broker_state_is_durable(tmp_path):
    ledger = WebullReduceOnlyCloseLedger(
        tmp_path / "close.json",
        clock=lambda: NOW,
    )

    intent = build_reduce_only_close_intent(
        client_order_id="close-1",
        positions=(position(),),
        symbol="SOUN",
        quantity=1,
        limit_price=6.90,
        created_at=NOW,
    )

    ledger.add_intent(intent)

    result = ledger.record_broker_state(
        client_order_id="close-1",
        broker_status="FILLED",
        status="FILLED",
        broker_order_id="broker-close-1",
        filled_quantity=1.0,
        average_fill_price=6.91,
    )

    assert result.status == "FILLED"
    assert result.broker_status == "FILLED"
    assert result.filled_quantity == 1.0
    assert result.average_fill_price == 6.91

    reloaded = ledger.load()["close-1"]

    assert reloaded == result
