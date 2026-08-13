from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable

import requests


ALPACA_NEWS_URL = (
    "https://data.alpaca.markets/v1beta1/news"
)


@dataclass(frozen=True)
class MomentumCatalystArticle:
    symbol: str
    created_at: str
    headline: str
    source: str
    summary: str
    url: str


class MomentumCatalystError(
    RuntimeError
):
    pass


class AlpacaMomentumCatalystClient:
    """
    Read-only Alpaca/Benzinga news adapter for
    Momentum Pullback catalyst research.

    This class does not place, preview, modify,
    or submit orders.
    """

    def __init__(
        self,
        *,
        alpaca,
        http_get=requests.get,
        timeout: int = 15,
    ) -> None:
        if timeout <= 0:
            raise ValueError(
                "timeout must be positive."
            )

        self.alpaca = alpaca
        self.http_get = http_get
        self.timeout = timeout

    def get_articles(
        self,
        *,
        symbols: Iterable[str],
        start: datetime,
        end: datetime | None = None,
        limit: int = 50,
    ) -> list[
        MomentumCatalystArticle
    ]:
        clean_symbols = tuple(
            dict.fromkeys(
                str(symbol)
                .strip()
                .upper()
                for symbol in symbols
                if str(symbol).strip()
            )
        )

        if not clean_symbols:
            return []

        if limit < 1:
            raise ValueError(
                "limit must be positive."
            )

        params: dict[str, Any] = {
            "symbols": ",".join(
                clean_symbols
            ),
            "start": (
                start.isoformat()
            ),
            "sort": "desc",
            "limit": limit,
            "include_content": "false",
        }

        if end is not None:
            params["end"] = (
                end.isoformat()
            )

        articles = []
        page_token = None

        while True:
            request_params = dict(
                params
            )

            if page_token:
                request_params[
                    "page_token"
                ] = page_token

            try:
                response = (
                    self.http_get(
                        ALPACA_NEWS_URL,
                        headers=(
                            self.alpaca.headers
                        ),
                        params=(
                            request_params
                        ),
                        timeout=(
                            self.timeout
                        ),
                    )
                )
            except Exception as error:
                raise (
                    MomentumCatalystError(
                        "Alpaca news request failed."
                    )
                ) from error

            status = getattr(
                response,
                "status_code",
                None,
            )

            if status != 200:
                raise (
                    MomentumCatalystError(
                        "Alpaca news request failed "
                        f"with HTTP {status}."
                    )
                )

            try:
                payload = (
                    response.json()
                )
            except Exception as error:
                raise (
                    MomentumCatalystError(
                        "Alpaca news returned "
                        "invalid JSON."
                    )
                ) from error

            if not isinstance(
                payload,
                dict,
            ):
                raise (
                    MomentumCatalystError(
                        "Alpaca news returned "
                        "an unexpected response."
                    )
                )

            raw_articles = (
                payload.get(
                    "news",
                    [],
                )
            )

            if not isinstance(
                raw_articles,
                list,
            ):
                raise (
                    MomentumCatalystError(
                        "Alpaca news returned "
                        "malformed article data."
                    )
                )

            for raw in raw_articles:
                if not isinstance(
                    raw,
                    dict,
                ):
                    continue

                raw_symbols = (
                    raw.get(
                        "symbols",
                        [],
                    )
                )

                if not isinstance(
                    raw_symbols,
                    list,
                ):
                    raw_symbols = []

                article_symbols = {
                    str(symbol)
                    .strip()
                    .upper()
                    for symbol in raw_symbols
                    if str(symbol).strip()
                }

                headline = str(
                    raw.get(
                        "headline",
                        "",
                    )
                ).strip()

                if not headline:
                    continue

                for symbol in clean_symbols:
                    if (
                        symbol
                        not in article_symbols
                    ):
                        continue

                    articles.append(
                        MomentumCatalystArticle(
                            symbol=symbol,
                            created_at=str(
                                raw.get(
                                    "created_at",
                                    "",
                                )
                            ).strip(),
                            headline=headline,
                            source=str(
                                raw.get(
                                    "source",
                                    "",
                                )
                            ).strip(),
                            summary=str(
                                raw.get(
                                    "summary",
                                    "",
                                )
                            ).strip(),
                            url=str(
                                raw.get(
                                    "url",
                                    "",
                                )
                            ).strip(),
                        )
                    )

            page_token = (
                payload.get(
                    "next_page_token"
                )
            )

            if not page_token:
                break

        articles.sort(
            key=lambda item: (
                item.created_at,
                item.symbol,
                item.headline,
            ),
            reverse=True,
        )

        return articles

    def get_articles_by_symbol(
        self,
        *,
        symbols: Iterable[str],
        start: datetime,
        end: datetime | None = None,
        limit: int = 50,
    ) -> dict[
        str,
        list[
            MomentumCatalystArticle
        ],
    ]:
        clean_symbols = tuple(
            dict.fromkeys(
                str(symbol)
                .strip()
                .upper()
                for symbol in symbols
                if str(symbol).strip()
            )
        )

        results = {
            symbol: []
            for symbol in clean_symbols
        }

        articles = self.get_articles(
            symbols=clean_symbols,
            start=start,
            end=end,
            limit=limit,
        )

        for article in articles:
            if article.symbol in results:
                results[
                    article.symbol
                ].append(
                    article
                )

        return results
