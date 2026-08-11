import pytest

from trading_bot.alpaca_client import AlpacaClient


def make_daily_bar(
        close=10.0,
        volume=1_000_000,
        high=None,
        low=None,
):
    return {
        "o": close,
        "h": close + 0.5 if high is None else high,
        "l": close - 0.5 if low is None else low,
        "c": close,
        "t": "2026-07-23T04:00:00Z",
        "v": volume,
    }


def test_scanner_statistics_are_calculated():
    client = object.__new__(AlpacaClient)
    captured = {}

    def fake_request(params, label):
        captured["params"] = params
        captured["label"] = label

        return {
            "bars": {
                "SNAP": [
                    make_daily_bar()
                    for _ in range(30)
                ],
            },
        }

    client._request = fake_request

    statistics = client.get_scanner_statistics(
        symbols_csv="snap",
        date_str="2026-07-27",
    )

    assert len(statistics) == 1

    stats = statistics[0]

    assert stats.symbol == "SNAP"
    assert stats.valid_bars == 30
    assert stats.avg_volume == 1_000_000
    assert stats.avg_price == 10.0
    assert stats.avg_range == 1.0
    assert stats.avg_range_pct == 10.0

    assert captured["params"]["symbols"] == "SNAP"
    assert captured["params"]["timeframe"] == "1Day"
    assert captured["params"]["sort"] == "desc"
    assert captured["params"]["feed"] == "iex"
    assert captured["params"]["end"].startswith(
        "2026-07-26"
    )
    assert captured["label"] == (
        "Scanner daily bars fetch"
    )


def test_invalid_scanner_bars_are_excluded():
    client = object.__new__(AlpacaClient)

    client._request = lambda params, label: {
        "bars": {
            "SNAP": [
                make_daily_bar(volume="invalid"),
                make_daily_bar(high=8.0, low=9.0),
                make_daily_bar(volume=750_000),
            ],
            "PINS": [],
        },
    }

    statistics = client.get_scanner_statistics(
        symbols_csv="SNAP,PINS",
        date_str="2026-07-27",
    )

    assert len(statistics) == 1
    assert statistics[0].symbol == "SNAP"
    assert statistics[0].valid_bars == 1
    assert statistics[0].avg_volume == 750_000


def test_scanner_statistics_respect_lookback():
    client = object.__new__(AlpacaClient)

    client._request = lambda params, label: {
        "bars": {
            "SNAP": [
                make_daily_bar(
                    close=10.0,
                    volume=1_000_000,
                ),
                make_daily_bar(
                    close=20.0,
                    volume=2_000_000,
                ),
                make_daily_bar(
                    close=30.0,
                    volume=100_000_000,
                ),
            ],
        },
    }

    statistics = client.get_scanner_statistics(
        symbols_csv="SNAP",
        date_str="2026-07-27",
        lookback_days=2,
    )

    stats = statistics[0]

    assert stats.valid_bars == 2
    assert stats.avg_volume == 1_500_000
    assert stats.avg_price == 15.0
    assert stats.avg_range == 1.0
    assert stats.avg_range_pct == pytest.approx(
        6.6666666667
    )
