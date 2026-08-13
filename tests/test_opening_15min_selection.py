from trading_bot.alpaca_client import AlpacaClient


def test_opening_15min_selects_0930_not_0945(
    monkeypatch,
):
    client = AlpacaClient()

    def fake_request(*, params, label):
        return {
            "bars": {
                "TEST": [
                    {
                        "t": "2026-08-12T13:45:00Z",
                        "o": 9.50,
                        "h": 9.60,
                        "l": 9.20,
                        "c": 9.30,
                        "v": 2000,
                    },
                    {
                        "t": "2026-08-12T13:30:00Z",
                        "o": 10.00,
                        "h": 10.10,
                        "l": 9.50,
                        "c": 9.60,
                        "v": 1000,
                    },
                ]
            }
        }

    monkeypatch.setattr(
        client,
        "_request",
        fake_request,
    )

    result = client.get_opening_15min_bars(
        symbols_csv="TEST",
        date_str="2026-08-12",
        feed="iex",
    )

    bar = result["TEST"]

    assert bar is not None
    assert (
        bar["t"]
        == "2026-08-12T13:30:00Z"
    )
    assert float(bar["l"]) == 9.50


def test_opening_15min_returns_none_without_0930(
    monkeypatch,
):
    client = AlpacaClient()

    def fake_request(*, params, label):
        return {
            "bars": {
                "TEST": [
                    {
                        "t": "2026-08-12T13:45:00Z",
                        "o": 9.50,
                        "h": 9.60,
                        "l": 9.20,
                        "c": 9.30,
                        "v": 2000,
                    },
                ]
            }
        }

    monkeypatch.setattr(
        client,
        "_request",
        fake_request,
    )

    result = client.get_opening_15min_bars(
        symbols_csv="TEST",
        date_str="2026-08-12",
        feed="iex",
    )

    assert result["TEST"] is None
