import pytest

import trading_bot.alpaca_client as alpaca_module

from trading_bot.alpaca_client import (
    AlpacaClient,
)


def test_alpaca_client_can_be_constructed_without_credentials(
        monkeypatch,
):
    monkeypatch.setattr(
        alpaca_module,
        "API_KEY",
        "",
    )
    monkeypatch.setattr(
        alpaca_module,
        "API_SECRET",
        "",
    )

    client = AlpacaClient()

    assert client.configured is False


def test_alpaca_request_fails_cleanly_without_credentials(
        monkeypatch,
):
    monkeypatch.setattr(
        alpaca_module,
        "API_KEY",
        "",
    )
    monkeypatch.setattr(
        alpaca_module,
        "API_SECRET",
        "",
    )

    client = AlpacaClient()

    with pytest.raises(
        RuntimeError,
        match="Alpaca market data is not configured",
    ):
        client._request(
            params={},
            label="controlled test",
        )


def test_alpaca_client_reports_configured_with_credentials(
        monkeypatch,
):
    monkeypatch.setattr(
        alpaca_module,
        "API_KEY",
        "test-key",
    )
    monkeypatch.setattr(
        alpaca_module,
        "API_SECRET",
        "test-secret",
    )

    client = AlpacaClient()

    assert client.configured is True
