from trading_bot.stream_client import AlpacaStockStream


def test_stream_accepts_bar():
    stream = AlpacaStockStream(
        symbols=["OPEN"],
        feed="iex",
    )

    accepted = stream.process_message(
        {
            "T": "b",
            "S": "OPEN",
            "o": 4.10,
            "h": 4.20,
            "l": 4.05,
            "c": 4.15,
            "v": 1000,
            "t": "2026-07-28T13:30:00Z",
        }
    )

    assert accepted is True
    assert len(stream.bars_for_symbol("OPEN")) == 1


def test_updated_bar_replaces_original_bar():
    stream = AlpacaStockStream(
        symbols=["OPEN"],
        feed="iex",
    )

    stream.process_message(
        {
            "T": "b",
            "S": "OPEN",
            "o": 4.10,
            "h": 4.20,
            "l": 4.05,
            "c": 4.15,
            "v": 1000,
            "t": "2026-07-28T13:30:00Z",
        }
    )

    stream.process_message(
        {
            "T": "u",
            "S": "OPEN",
            "o": 4.10,
            "h": 4.25,
            "l": 4.05,
            "c": 4.22,
            "v": 1250,
            "t": "2026-07-28T13:30:00Z",
        }
    )

    bars = stream.bars_for_symbol("OPEN")

    assert len(bars) == 1
    assert bars[0]["h"] == 4.25
    assert bars[0]["c"] == 4.22
    assert bars[0]["v"] == 1250


def test_stream_ignores_unknown_symbol():
    stream = AlpacaStockStream(
        symbols=["OPEN"],
        feed="iex",
    )

    accepted = stream.process_message(
        {
            "T": "b",
            "S": "AAPL",
            "o": 100.0,
            "h": 101.0,
            "l": 99.0,
            "c": 100.5,
            "t": "2026-07-28T13:30:00Z",
        }
    )

    assert accepted is False
    assert stream.bars_for_symbol("OPEN") == []


def test_stream_rejects_invalid_feed():
    try:
        AlpacaStockStream(
            symbols=["OPEN"],
            feed="invalid",
        )
    except ValueError as error:
        assert "iex" in str(error)
    else:
        raise AssertionError(
            "Invalid WebSocket feed was accepted."
        )


def test_snapshot_is_independent_copy():
    stream = AlpacaStockStream(
        symbols=["OPEN"],
        feed="iex",
    )

    stream.process_message(
        {
            "T": "b",
            "S": "OPEN",
            "o": 4.10,
            "h": 4.20,
            "l": 4.05,
            "c": 4.15,
            "v": 1000,
            "t": "2026-07-28T13:30:00Z",
        }
    )

    snapshot = stream.snapshot()

    snapshot["OPEN"][0]["h"] = 999.0

    assert (
        stream.bars_for_symbol("OPEN")[0]["h"]
        == 4.20
    )


def test_updated_bar_is_visible_in_snapshot():
    stream = AlpacaStockStream(
        symbols=["OPEN"],
        feed="iex",
    )

    stream.process_message(
        {
            "T": "b",
            "S": "OPEN",
            "o": 4.10,
            "h": 4.20,
            "l": 4.05,
            "c": 4.15,
            "v": 1000,
            "t": "2026-07-28T13:30:00Z",
        }
    )

    stream.process_message(
        {
            "T": "u",
            "S": "OPEN",
            "o": 4.10,
            "h": 4.30,
            "l": 4.05,
            "c": 4.25,
            "v": 1400,
            "t": "2026-07-28T13:30:00Z",
        }
    )

    snapshot = stream.snapshot()

    assert len(snapshot["OPEN"]) == 1
    assert snapshot["OPEN"][0]["h"] == 4.30
    assert snapshot["OPEN"][0]["c"] == 4.25
    assert snapshot["OPEN"][0]["v"] == 1400
