import pytest

from trading_bot.alpaca_client import AlpacaClient


def make_bar():
    return {
        "o": 10.0,
        "h": 10.5,
        "l": 9.5,
        "c": 10.0,
        "t": "2026-07-23T13:30:00Z",
        "v": 1_000_000,
    }


def test_market_data_uses_requested_symbols():
    client = object.__new__(AlpacaClient)
    captured = {}

    def fake_request(params, label):
        captured["params"] = params
        return {
            "bars": {
                "AAA": [make_bar()],
                "BBB": [make_bar()],
            },
        }

    client._request = fake_request

    results = client.get_1min_bars(
        symbols_csv="AAA, BBB,AAA",
        start_iso="2026-07-27T13:30:00Z",
        end_iso="2026-07-27T13:31:00Z",
    )

    assert list(results) == ["AAA", "BBB"]
    assert results["AAA"] is not None
    assert results["BBB"] is not None
    assert captured["params"]["feed"] == "iex"


@pytest.mark.parametrize(
    ("symbols_csv", "expected"),
    [
        ("snap,pins", ["SNAP", "PINS"]),
        (" SNAP, SNAP ", ["SNAP"]),
    ],
)
def test_symbol_csv_normalisation(
        symbols_csv,
        expected,
):
    assert AlpacaClient._symbols_from_csv(
        symbols_csv
    ) == expected


def test_empty_symbol_csv_is_rejected():
    with pytest.raises(
            ValueError,
            match="At least one symbol",
    ):
        AlpacaClient._symbols_from_csv(" , ")
