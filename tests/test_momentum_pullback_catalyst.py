from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from trading_bot.momentum_pullback_catalyst import (
    AlpacaMomentumCatalystClient,
    MomentumCatalystError,
)


UTC = ZoneInfo("UTC")


class FakeAlpaca:
    def __init__(self):
        self.headers = {
            "APCA-API-KEY-ID": "secret-key",
            "APCA-API-SECRET-KEY": (
                "secret-secret"
            ),
        }


class FakeResponse:
    def __init__(
        self,
        payload,
        status_code=200,
    ):
        self.payload = payload
        self.status_code = (
            status_code
        )

    def json(self):
        return self.payload


class FakeHttp:
    def __init__(
        self,
        responses,
    ):
        self.responses = list(
            responses
        )
        self.calls = []

    def __call__(
        self,
        url,
        *,
        headers,
        params,
        timeout,
    ):
        self.calls.append({
            "url": url,
            "headers": dict(
                headers
            ),
            "params": dict(
                params
            ),
            "timeout": timeout,
        })

        return self.responses.pop(
            0
        )


def test_empty_symbols_make_no_request():
    http = FakeHttp([])

    client = (
        AlpacaMomentumCatalystClient(
            alpaca=FakeAlpaca(),
            http_get=http,
        )
    )

    result = client.get_articles(
        symbols=[],
        start=datetime(
            2026,
            8,
            13,
            tzinfo=UTC,
        ),
    )

    assert result == []
    assert http.calls == []


def test_reads_articles_for_requested_symbols():
    http = FakeHttp([
        FakeResponse({
            "news": [
                {
                    "created_at": (
                        "2026-08-13T12:00:00Z"
                    ),
                    "headline": (
                        "TEST announces contract"
                    ),
                    "source": "benzinga",
                    "summary": "Summary",
                    "url": (
                        "https://example.com/a"
                    ),
                    "symbols": [
                        "TEST",
                        "OTHER",
                    ],
                }
            ],
            "next_page_token": None,
        })
    ])

    client = (
        AlpacaMomentumCatalystClient(
            alpaca=FakeAlpaca(),
            http_get=http,
        )
    )

    result = client.get_articles(
        symbols=[
            "test",
            "missing",
        ],
        start=datetime(
            2026,
            8,
            13,
            11,
            0,
            tzinfo=UTC,
        ),
    )

    assert len(result) == 1

    article = result[0]

    assert article.symbol == "TEST"
    assert (
        article.headline
        == "TEST announces contract"
    )
    assert (
        article.source
        == "benzinga"
    )

    call = http.calls[0]

    assert (
        call["params"]["symbols"]
        == "TEST,MISSING"
    )

    assert (
        call["params"][
            "include_content"
        ]
        == "false"
    )


def test_groups_articles_by_symbol():
    http = FakeHttp([
        FakeResponse({
            "news": [
                {
                    "created_at": (
                        "2026-08-13T12:00:00Z"
                    ),
                    "headline": "A headline",
                    "source": "benzinga",
                    "symbols": ["AAA"],
                },
                {
                    "created_at": (
                        "2026-08-13T12:01:00Z"
                    ),
                    "headline": "B headline",
                    "source": "benzinga",
                    "symbols": ["BBB"],
                },
            ],
            "next_page_token": None,
        })
    ])

    client = (
        AlpacaMomentumCatalystClient(
            alpaca=FakeAlpaca(),
            http_get=http,
        )
    )

    result = (
        client.get_articles_by_symbol(
            symbols=[
                "AAA",
                "BBB",
                "CCC",
            ],
            start=datetime(
                2026,
                8,
                13,
                tzinfo=UTC,
            ),
        )
    )

    assert len(
        result["AAA"]
    ) == 1

    assert len(
        result["BBB"]
    ) == 1

    assert (
        result["CCC"]
        == []
    )


def test_follows_pagination():
    http = FakeHttp([
        FakeResponse({
            "news": [
                {
                    "created_at": (
                        "2026-08-13T12:00:00Z"
                    ),
                    "headline": "First",
                    "source": "benzinga",
                    "symbols": ["AAA"],
                }
            ],
            "next_page_token": (
                "next-token"
            ),
        }),
        FakeResponse({
            "news": [
                {
                    "created_at": (
                        "2026-08-13T11:00:00Z"
                    ),
                    "headline": "Second",
                    "source": "benzinga",
                    "symbols": ["AAA"],
                }
            ],
            "next_page_token": None,
        }),
    ])

    client = (
        AlpacaMomentumCatalystClient(
            alpaca=FakeAlpaca(),
            http_get=http,
        )
    )

    result = client.get_articles(
        symbols=["AAA"],
        start=datetime(
            2026,
            8,
            13,
            tzinfo=UTC,
        ),
    )

    assert len(result) == 2
    assert len(http.calls) == 2

    assert (
        http.calls[1][
            "params"
        ]["page_token"]
        == "next-token"
    )


def test_http_error_does_not_expose_secrets():
    http = FakeHttp([
        FakeResponse(
            {
                "message": (
                    "secret-key"
                )
            },
            status_code=401,
        )
    ])

    client = (
        AlpacaMomentumCatalystClient(
            alpaca=FakeAlpaca(),
            http_get=http,
        )
    )

    with pytest.raises(
        MomentumCatalystError
    ) as caught:
        client.get_articles(
            symbols=["AAA"],
            start=datetime(
                2026,
                8,
                13,
                tzinfo=UTC,
            ),
        )

    message = str(
        caught.value
    )

    assert "401" in message
    assert (
        "secret-key"
        not in message
    )
    assert (
        "secret-secret"
        not in message
    )


def test_invalid_json_rejected():
    class InvalidResponse:
        status_code = 200

        def json(self):
            raise ValueError(
                "invalid"
            )

    client = (
        AlpacaMomentumCatalystClient(
            alpaca=FakeAlpaca(),
            http_get=lambda *args, **kwargs: (
                InvalidResponse()
            ),
        )
    )

    with pytest.raises(
        MomentumCatalystError
    ):
        client.get_articles(
            symbols=["AAA"],
            start=datetime(
                2026,
                8,
                13,
                tzinfo=UTC,
            ),
        )


def test_limit_must_be_positive():
    client = (
        AlpacaMomentumCatalystClient(
            alpaca=FakeAlpaca(),
        )
    )

    with pytest.raises(
        ValueError
    ):
        client.get_articles(
            symbols=["AAA"],
            start=datetime(
                2026,
                8,
                13,
                tzinfo=UTC,
            ),
            limit=0,
        )
