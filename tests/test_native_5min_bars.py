from trading_bot.alpaca_client import AlpacaClient


def test_native_5min_bars_use_alpaca_5min_and_sort():
    client = object.__new__(AlpacaClient)

    requests = []

    responses = [
        {
            "bars": {
                "OPEN": [
                    {
                        "t": "2026-08-11T14:00:00Z",
                        "o": 4.20,
                        "h": 4.30,
                        "l": 4.18,
                        "c": 4.28,
                        "v": 1000,
                    },
                ],
            },
            "next_page_token": "page-2",
        },
        {
            "bars": {
                "OPEN": [
                    {
                        "t": "2026-08-11T13:55:00Z",
                        "o": 4.10,
                        "h": 4.22,
                        "l": 4.08,
                        "c": 4.20,
                        "v": 900,
                    },
                ],
            },
        },
    ]

    def fake_request(*, params, label):
        requests.append(
            {
                "params": dict(params),
                "label": label,
            }
        )
        return responses.pop(0)

    client._request = fake_request

    bars = client.get_historical_5min_bars(
        symbols_csv="OPEN",
        start_iso="2026-08-11T13:45:00Z",
        end_iso="2026-08-11T15:00:00Z",
        feed="iex",
    )

    assert len(requests) == 2

    assert requests[0]["params"]["timeframe"] == "5Min"
    assert requests[0]["params"]["feed"] == "iex"

    assert requests[1]["params"]["page_token"] == "page-2"

    assert [
        bar["t"]
        for bar in bars["OPEN"]
    ] == [
        "2026-08-11T13:55:00Z",
        "2026-08-11T14:00:00Z",
    ]
