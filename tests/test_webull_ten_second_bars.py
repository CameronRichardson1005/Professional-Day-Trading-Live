from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from trading_bot.webull_ten_second_bars import (
    TenSecondBarAggregator,
    WebullTradeTick,
    ten_second_bucket,
    tick_from_webull_message,
)


EASTERN = ZoneInfo("America/New_York")


def tick(
    *,
    timestamp_ms,
    price,
    volume,
    symbol="TEST",
):
    return WebullTradeTick(
        symbol=symbol,
        timestamp_ms=timestamp_ms,
        price=price,
        volume=volume,
        trading_session="RTH",
    )


def test_parse_webull_tick_dictionary():
    parsed = tick_from_webull_message({
        "symbol": "NVDA",
        "timestamp": 1786646509182,
        "price": 225.64,
        "volume": 900,
        "trading_session": "RTH",
        "side": "N",
    })

    assert parsed.symbol == "NVDA"
    assert parsed.timestamp_ms == (
        1786646509182
    )
    assert parsed.price == 225.64
    assert parsed.volume == 900
    assert parsed.trading_session == "RTH"
    assert parsed.side == "N"


def test_epoch_milliseconds_convert_to_eastern():
    parsed = tick_from_webull_message({
        "symbol": "NVDA",
        "timestamp": 1786646509182,
        "price": 225.64,
        "volume": 900,
    })

    assert (
        parsed.timestamp
        .tzinfo
        is not None
    )

    assert (
        parsed.timestamp
        .strftime("%H:%M:%S")
        == "14:41:49"
    )


def test_bucket_rounds_down_to_ten_seconds():
    timestamp = datetime(
        2026,
        8,
        13,
        14,
        41,
        49,
        500000,
        tzinfo=EASTERN,
    )

    bucket = ten_second_bucket(
        timestamp
    )

    assert bucket.second == 40
    assert bucket.microsecond == 0


def test_same_bucket_builds_ohlcv():
    aggregator = (
        TenSecondBarAggregator()
    )

    base = 1786646500000

    assert aggregator.add_tick(
        tick(
            timestamp_ms=base + 100,
            price=10.00,
            volume=100,
        )
    ) is None

    assert aggregator.add_tick(
        tick(
            timestamp_ms=base + 200,
            price=10.20,
            volume=200,
        )
    ) is None

    assert aggregator.add_tick(
        tick(
            timestamp_ms=base + 300,
            price=9.90,
            volume=300,
        )
    ) is None

    bar = aggregator.flush(
        "TEST"
    )

    assert bar is not None
    assert bar.open == 10.00
    assert bar.high == 10.20
    assert bar.low == 9.90
    assert bar.close == 9.90
    assert bar.volume == 600
    assert bar.trades == 3


def test_next_bucket_emits_completed_bar():
    aggregator = (
        TenSecondBarAggregator()
    )

    # Exact bucket boundaries keep this
    # test independent of the current date.
    first = int(
        datetime(
            2026,
            8,
            13,
            10,
            0,
            1,
            tzinfo=EASTERN,
        ).timestamp()
        * 1000
    )

    second = int(
        datetime(
            2026,
            8,
            13,
            10,
            0,
            11,
            tzinfo=EASTERN,
        ).timestamp()
        * 1000
    )

    aggregator.add_tick(
        tick(
            timestamp_ms=first,
            price=10,
            volume=100,
        )
    )

    completed = (
        aggregator.add_tick(
            tick(
                timestamp_ms=second,
                price=11,
                volume=200,
            )
        )
    )

    assert completed is not None
    assert completed.open == 10
    assert completed.close == 10
    assert completed.volume == 100
    assert completed.trades == 1

    current = aggregator.flush(
        "TEST"
    )

    assert current is not None
    assert current.open == 11


def test_symbols_are_aggregated_independently():
    aggregator = (
        TenSecondBarAggregator()
    )

    timestamp = int(
        datetime(
            2026,
            8,
            13,
            10,
            0,
            1,
            tzinfo=EASTERN,
        ).timestamp()
        * 1000
    )

    aggregator.add_tick(
        tick(
            symbol="AAA",
            timestamp_ms=timestamp,
            price=5,
            volume=10,
        )
    )

    aggregator.add_tick(
        tick(
            symbol="BBB",
            timestamp_ms=timestamp,
            price=20,
            volume=30,
        )
    )

    aaa = aggregator.flush(
        "AAA"
    )

    bbb = aggregator.flush(
        "BBB"
    )

    assert aaa.open == 5
    assert bbb.open == 20


def test_invalid_tick_rejected():
    with pytest.raises(
        ValueError
    ):
        tick_from_webull_message({
            "symbol": "NVDA",
            "timestamp": 1786646509182,
            "price": 0,
            "volume": 100,
        })
