from trading_bot.webull_strategy_market_data import (
    WebullStrategyMarketData,
    _normalize_bar,
)


class FakeResponse:
    def __init__(
        self,
        payload,
        status_code=200,
    ):
        self.payload = payload
        self.status_code = status_code

    def json(self):
        return self.payload


class FakeMarketData:
    def __init__(
        self,
        by_symbol,
    ):
        self.by_symbol = by_symbol
        self.calls = []

    def get_history_bar(
        self,
        symbol,
        category,
        timespan,
        count="200",
        start_time=None,
        end_time=None,
    ):
        self.calls.append({
            "symbol": symbol,
            "category": category,
            "timespan": timespan,
            "count": count,
        })

        return FakeResponse(
            self.by_symbol.get(
                symbol,
                [],
            )
        )


def raw_bar(
    *,
    timestamp,
    open_price=10,
    high=11,
    low=9,
    close=10.5,
    volume=1000,
):
    return {
        "symbol": "TEST",
        "time": timestamp,
        "open": str(open_price),
        "high": str(high),
        "low": str(low),
        "close": str(close),
        "volume": str(volume),
        "trading_session": "RTH",
    }


def test_normalizes_real_webull_shape():
    result = _normalize_bar({
        "tickerId": "913257561",
        "symbol": "NVDA",
        "time": (
            "2026-08-13T19:59:00.000+0000"
        ),
        "open": "224.99",
        "close": "225.30",
        "high": "225.40",
        "low": "224.9701",
        "volume": "12994967",
        "trading_session": "RTH",
        "instrument_id": "913257561",
    })

    assert result == {
        "t": "2026-08-13T19:59:00Z",
        "o": 224.99,
        "h": 225.40,
        "l": 224.9701,
        "c": 225.30,
        "v": 12994967.0,
    }


def test_invalid_bar_is_rejected():
    result = _normalize_bar({
        "time": (
            "2026-08-13T19:59:00+00:00"
        ),
        "open": "10",
        "high": "8",
        "low": "9",
        "close": "10",
        "volume": "100",
    })

    assert result is None


def test_gets_0930_opening_bar():
    market = FakeMarketData({
        "AAA": [
            raw_bar(
                timestamp=(
                    "2026-08-13T13:30:00.000+0000"
                ),
                open_price=5,
                high=6,
                low=4,
                close=5.5,
            ),
            raw_bar(
                timestamp=(
                    "2026-08-13T13:45:00.000+0000"
                ),
            ),
        ]
    })

    adapter = WebullStrategyMarketData(
        market_data=market
    )

    result = (
        adapter.get_opening_15min_bars(
            symbols_csv="AAA",
            date_str="2026-08-13",
        )
    )

    assert result["AAA"] is not None

    assert (
        result["AAA"]["t"]
        == "2026-08-13T13:30:00Z"
    )

    assert result["AAA"]["o"] == 5.0
    assert result["AAA"]["h"] == 6.0


def test_missing_opening_bar_returns_none():
    adapter = WebullStrategyMarketData(
        market_data=FakeMarketData({
            "AAA": [
                raw_bar(
                    timestamp=(
                        "2026-08-13T14:00:00.000+0000"
                    )
                )
            ]
        })
    )

    result = (
        adapter.get_opening_15min_bars(
            symbols_csv="AAA",
            date_str="2026-08-13",
        )
    )

    assert result["AAA"] is None


def test_historical_five_minute_filter():
    market = FakeMarketData({
        "AAA": [
            raw_bar(
                timestamp=(
                    "2026-08-13T13:40:00.000+0000"
                ),
            ),
            raw_bar(
                timestamp=(
                    "2026-08-13T13:45:00.000+0000"
                ),
            ),
            raw_bar(
                timestamp=(
                    "2026-08-13T13:50:00.000+0000"
                ),
            ),
            raw_bar(
                timestamp=(
                    "2026-08-13T14:00:00.000+0000"
                ),
            ),
        ]
    })

    adapter = WebullStrategyMarketData(
        market_data=market
    )

    result = (
        adapter.get_historical_5min_bars(
            symbols_csv="AAA",
            start_iso=(
                "2026-08-13T13:45:00Z"
            ),
            end_iso=(
                "2026-08-13T13:50:00Z"
            ),
        )
    )

    assert [
        bar["t"]
        for bar in result["AAA"]
    ] == [
        "2026-08-13T13:45:00Z",
        "2026-08-13T13:50:00Z",
    ]


def test_historical_one_minute_filter():
    market = FakeMarketData({
        "AAA": [
            raw_bar(
                timestamp=(
                    "2026-08-13T13:45:00.000+0000"
                ),
            ),
            raw_bar(
                timestamp=(
                    "2026-08-13T13:46:00.000+0000"
                ),
            ),
        ]
    })

    adapter = WebullStrategyMarketData(
        market_data=market
    )

    result = (
        adapter.get_historical_1min_bars(
            symbols_csv="AAA",
            start_iso=(
                "2026-08-13T13:46:00Z"
            ),
            end_iso=(
                "2026-08-13T13:46:00Z"
            ),
        )
    )

    assert len(
        result["AAA"]
    ) == 1

    assert (
        result["AAA"][0]["t"]
        == "2026-08-13T13:46:00Z"
    )


def test_multiple_symbols_are_supported():
    market = FakeMarketData({
        "AAA": [],
        "BBB": [],
    })

    adapter = WebullStrategyMarketData(
        market_data=market
    )

    result = (
        adapter.get_opening_15min_bars(
            symbols_csv="AAA,BBB",
            date_str="2026-08-13",
        )
    )

    assert set(result) == {
        "AAA",
        "BBB",
    }

    assert len(
        market.calls
    ) == 2



def test_historical_opening_15min_bars_filters_date_and_clock(
        monkeypatch,
):
    adapter = WebullStrategyMarketData(
        market_data=None
    )

    bars = [
        {
            "t": "2026-08-10T13:30:00Z",
            "o": 10.0,
            "h": 10.5,
            "l": 9.9,
            "c": 10.1,
            "v": 1000,
        },
        # Same date, wrong 15-minute candle.
        {
            "t": "2026-08-10T13:45:00Z",
            "o": 10.1,
            "h": 10.6,
            "l": 10.0,
            "c": 10.4,
            "v": 2000,
        },
        {
            "t": "2026-08-11T13:30:00Z",
            "o": 10.2,
            "h": 10.7,
            "l": 10.0,
            "c": 10.3,
            "v": 3000,
        },
        # Outside requested range.
        {
            "t": "2026-08-12T13:30:00Z",
            "o": 10.3,
            "h": 10.8,
            "l": 10.1,
            "c": 10.4,
            "v": 4000,
        },
    ]

    calls = []

    def fake_history(**kwargs):
        calls.append(kwargs)
        return bars

    monkeypatch.setattr(
        adapter,
        "_history",
        fake_history,
    )

    result = (
        adapter
        .get_historical_opening_15min_bars(
            symbols_csv="TEST",
            start_date="2026-08-10",
            end_date="2026-08-11",
        )
    )

    assert [
        bar["t"]
        for bar in result["TEST"]
    ] == [
        "2026-08-10T13:30:00Z",
        "2026-08-11T13:30:00Z",
    ]

    assert len(calls) == 1
    assert calls[0]["symbol"] == "TEST"



def test_historical_one_minute_request_is_anchored():
    calls = []

    class Response:
        status_code = 200

        @staticmethod
        def json():
            return []

    class AnchoredMarketData:
        def get_history_bar(
            self,
            symbol,
            category,
            timespan,
            count="200",
            real_time_required=None,
            trading_sessions=None,
            start_time=None,
            end_time=None,
        ):
            calls.append({
                "symbol": symbol,
                "count": count,
                "start_time": start_time,
                "end_time": end_time,
            })

            return Response()

    adapter = WebullStrategyMarketData(
        market_data=AnchoredMarketData()
    )

    adapter.get_historical_1min_bars(
        symbols_csv="TEST",
        start_iso=(
            "2026-03-02T14:30:00Z"
        ),
        end_iso=(
            "2026-03-02T21:00:00Z"
        ),
    )

    assert len(calls) == 1

    assert (
        calls[0]["start_time"]
        == 1772461800000
    )

    assert (
        calls[0]["end_time"]
        == 1772485200000
    )

    assert (
        calls[0]["count"]
        == "1200"
    )


def test_historical_five_minute_request_is_anchored():
    calls = []

    class Response:
        status_code = 200

        @staticmethod
        def json():
            return []

    class AnchoredMarketData:
        def get_history_bar(
            self,
            symbol,
            category,
            timespan,
            count="200",
            real_time_required=None,
            trading_sessions=None,
            start_time=None,
            end_time=None,
        ):
            calls.append({
                "symbol": symbol,
                "count": count,
                "start_time": start_time,
                "end_time": end_time,
            })

            return Response()

    adapter = WebullStrategyMarketData(
        market_data=AnchoredMarketData()
    )

    adapter.get_historical_5min_bars(
        symbols_csv="TEST",
        start_iso=(
            "2026-03-02T14:30:00Z"
        ),
        end_iso=(
            "2026-03-02T21:00:00Z"
        ),
    )

    assert len(calls) == 1

    assert (
        calls[0]["start_time"]
        == 1772461800000
    )

    assert (
        calls[0]["end_time"]
        == 1772485200000
    )

    assert (
        calls[0]["count"]
        == "500"
    )


def test_historical_opening_bars_use_anchored_chunks():
    calls = []

    class Response:
        status_code = 200

        @staticmethod
        def json():
            return []

    class AnchoredMarketData:
        def get_history_bar(
            self,
            symbol,
            category,
            timespan,
            count="200",
            real_time_required=None,
            trading_sessions=None,
            start_time=None,
            end_time=None,
        ):
            calls.append({
                "symbol": symbol,
                "count": count,
                "start_time": start_time,
                "end_time": end_time,
            })

            return Response()

    adapter = WebullStrategyMarketData(
        market_data=AnchoredMarketData()
    )

    result = (
        adapter
        .get_historical_opening_15min_bars(
            symbols_csv="TEST",
            start_date="2026-03-02",
            end_date="2026-04-05",
        )
    )

    assert result == {
        "TEST": [],
    }

    # 35 calendar days:
    # Mar 2-Mar 31
    # Apr 1-Apr 5
    assert len(calls) == 2

    assert all(
        call["count"] == "1200"
        for call in calls
    )

    assert all(
        call["start_time"] is not None
        for call in calls
    )

    assert all(
        call["end_time"] is not None
        for call in calls
    )
