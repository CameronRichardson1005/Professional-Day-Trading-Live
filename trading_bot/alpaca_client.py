import requests
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from typing import Any
from .indicators import calculate_wilder_atr

from .config import (
    API_KEY,
    API_SECRET,
    BASE_URL,
    MARKET_DATA_FEED,
)
from .scanner import OpeningReliability, StockStats
from .utils import call_with_retries


class AlpacaClient:
    STOCK_DATA_FEEDS = {"iex", "sip"}

    def __init__(self) -> None:
        self.base_url = BASE_URL

        self.headers = {
            "accept": "application/json",
            "APCA-API-KEY-ID": API_KEY,
            "APCA-API-SECRET-KEY": API_SECRET,
        }

    def _request(
            self,
            params: dict[str, Any],
            label: str,
    ) -> dict[str, Any]:
        response = call_with_retries(
            requests.get,
            self.base_url,
            headers=self.headers,
            params=params,
            timeout=15,
            label=label,
        )

        response.raise_for_status()

        try:
            data = response.json()
        except ValueError as error:
            raise RuntimeError(
                f"{label} returned invalid JSON."
            ) from error

        if not isinstance(data, dict):
            raise RuntimeError(
                f"{label} returned an unexpected response."
            )

        if "bars" not in data:
            message = data.get("message", "No bars object returned")
            raise RuntimeError(f"{label} failed: {message}")

        return data

    @staticmethod
    def _validate_feed(feed: str) -> str:
        normalised = feed.strip().lower()

        if normalised not in AlpacaClient.STOCK_DATA_FEEDS:
            raise ValueError(
                "Stock data feed must be 'iex' or 'sip'."
            )

        return normalised

    @staticmethod
    def _symbols_from_csv(
            symbols_csv: str,
    ) -> list[str]:
        symbols = []

        for raw_symbol in symbols_csv.split(","):
            symbol = raw_symbol.strip().upper()

            if symbol and symbol not in symbols:
                symbols.append(symbol)

        if not symbols:
            raise ValueError(
                "At least one symbol is required."
            )

        return symbols

    @staticmethod
    def _is_valid_bar(bar: Any) -> bool:
        if not isinstance(bar, dict):
            return False

        required_fields = ("o", "h", "l", "c", "t")

        if any(field not in bar for field in required_fields):
            return False

        try:
            open_price = float(bar["o"])
            high_price = float(bar["h"])
            low_price = float(bar["l"])
            close_price = float(bar["c"])
        except (TypeError, ValueError):
            return False

        if min(
                open_price,
                high_price,
                low_price,
                close_price,
        ) <= 0:
            return False

        if high_price < low_price:
            return False

        if not low_price <= open_price <= high_price:
            return False

        if not low_price <= close_price <= high_price:
            return False

        return True

    def _first_valid_bar(
            self,
            bars: Any,
            symbol: str,
            label: str,
    ) -> dict | None:
        if not isinstance(bars, list):
            print(f"{symbol}: malformed {label} response")
            return None

        for bar in bars:
            if self._is_valid_bar(bar):
                return bar

        print(f"{symbol}: no valid {label} bar")
        return None

    def get_1min_bars(
        self,
        symbols_csv: str,
        start_iso: str,
        end_iso: str,
        feed: str = MARKET_DATA_FEED,
    ) -> dict[str, dict | None]:
        feed = self._validate_feed(feed)
        params = {
            "symbols": symbols_csv,
            "timeframe": "1Min",
            "start": start_iso,
            "end": end_iso,
            "adjustment": "raw",
            "feed": feed,
            "currency": "usd",
            "limit": 1000,
            "sort": "desc",
        }

        data = self._request(
            params=params,
            label="1-minute bars fetch",
        )

        bars_by_symbol = data.get("bars", {})

        return {
            symbol: self._first_valid_bar(
                bars=bars_by_symbol.get(symbol, []),
                symbol=symbol,
                label="1-minute",
            )
            for symbol in self._symbols_from_csv(symbols_csv)
        }

    def get_historical_1min_bars(
        self,
        symbols_csv: str,
        start_iso: str,
        end_iso: str,
        feed: str = MARKET_DATA_FEED,
    ) -> dict[str, list[dict]]:
        """
        Fetch all valid historical one-minute bars in
        chronological order, following Alpaca pagination.
        """
        symbols = self._symbols_from_csv(symbols_csv)
        feed = self._validate_feed(feed)

        base_params = {
            "symbols": symbols_csv,
            "timeframe": "1Min",
            "start": start_iso,
            "end": end_iso,
            "adjustment": "raw",
            "feed": feed,
            "currency": "usd",
            "limit": 1000,
            "sort": "desc",
        }

        results = {
            symbol: []
            for symbol in symbols
        }

        page_token = None

        while True:
            params = dict(base_params)

            if page_token:
                params["page_token"] = page_token

            data = self._request(
                params=params,
                label="Historical replay bars fetch",
            )

            bars_by_symbol = data.get("bars", {})

            if not isinstance(bars_by_symbol, dict):
                raise RuntimeError(
                    "Malformed historical replay response."
                )

            for symbol in symbols:
                raw_bars = bars_by_symbol.get(symbol, [])

                if not isinstance(raw_bars, list):
                    print(
                        f"{symbol}: malformed historical "
                        "replay response"
                    )
                    continue

                results[symbol].extend(
                    bar
                    for bar in raw_bars
                    if self._is_valid_bar(bar)
                )

            page_token = data.get("next_page_token")

            if not page_token:
                break

        for bars in results.values():
            bars.sort(
                key=lambda bar: str(bar["t"])
            )

        return results

    def get_historical_5min_bars(
            self,
            symbols_csv: str,
            start_iso: str,
            end_iso: str,
            feed: str = MARKET_DATA_FEED,
    ) -> dict[str, list[dict]]:
        """
        Fetch valid native Alpaca five-minute bars in
        chronological order, following Alpaca pagination.

        These are authoritative 5Min bars from Alpaca.
        They are not reconstructed from one-minute data.
        """
        symbols = self._symbols_from_csv(symbols_csv)
        feed = self._validate_feed(feed)

        base_params = {
            "symbols": symbols_csv,
            "timeframe": "5Min",
            "start": start_iso,
            "end": end_iso,
            "adjustment": "raw",
            "feed": feed,
            "currency": "usd",
            "limit": 1000,
            "sort": "desc",
        }

        results = {
            symbol: []
            for symbol in symbols
        }

        page_token = None

        while True:
            params = dict(base_params)

            if page_token:
                params["page_token"] = page_token

            data = self._request(
                params=params,
                label="Historical 5-minute bars fetch",
            )

            bars_by_symbol = data.get("bars", {})

            if not isinstance(bars_by_symbol, dict):
                raise RuntimeError(
                    "Malformed historical 5-minute response."
                )

            for symbol in symbols:
                raw_bars = bars_by_symbol.get(
                    symbol,
                    [],
                )

                if not isinstance(raw_bars, list):
                    print(
                        f"{symbol}: malformed historical "
                        "5-minute response"
                    )
                    continue

                results[symbol].extend(
                    bar
                    for bar in raw_bars
                    if self._is_valid_bar(bar)
                )

            page_token = data.get(
                "next_page_token"
            )

            if not page_token:
                break

        for bars in results.values():
            bars.sort(
                key=lambda bar: str(bar["t"])
            )

        return results

    def get_opening_15min_bars(
            self,
            symbols_csv: str,
            date_str: str,
            feed: str = MARKET_DATA_FEED,
    ) -> dict[str, dict | None]:
        feed = self._validate_feed(feed)
        eastern = ZoneInfo("America/New_York")
        utc = ZoneInfo("UTC")

        trading_date = datetime.strptime(
            date_str,
            "%Y-%m-%d",
        ).date()

        opening_start = datetime.combine(
            trading_date,
            time(hour=9, minute=30),
            tzinfo=eastern,
        ).astimezone(utc)

        opening_end = datetime.combine(
            trading_date,
            time(hour=9, minute=45),
            tzinfo=eastern,
        ).astimezone(utc)

        params = {
            "symbols": symbols_csv,
            "timeframe": "15Min",
            "start": opening_start.strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
            "end": opening_end.strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
            "adjustment": "raw",
            "feed": feed,
            "currency": "usd",
            "limit": 1000,
            "sort": "desc",
        }

        data = self._request(
            params=params,
            label="Opening 15-minute bars fetch",
        )

        bars_by_symbol = data.get("bars", {})

        return {
            symbol: self._first_valid_bar(
                bars=bars_by_symbol.get(symbol, []),
                symbol=symbol,
                label="opening 15-minute",
            )
            for symbol in self._symbols_from_csv(symbols_csv)
        }

    def get_previous_day_ranges_all(
        self,
        symbols_csv: str,
        date_str: str,
        feed: str = MARKET_DATA_FEED,
    ) -> dict[str, float | None]:
        """
        Request daily bars for all symbols and calculate
        Wilder's 14-period ATR for each symbol.
        """
        feed = self._validate_feed(feed)

        end_date = datetime.strptime(
            date_str,
            "%Y-%m-%d",
        ) - timedelta(days=1)

        start_date = end_date - timedelta(days=180)

        base_params = {
            "symbols": symbols_csv,
            "timeframe": "1Day",
            "start": start_date.strftime("%Y-%m-%dT00:00:00Z"),
            "end": end_date.strftime("%Y-%m-%dT23:59:59Z"),
            "adjustment": "raw",
            "feed": feed,
            "currency": "usd",
            "limit": 10_000,
            "sort": "asc",
        }

        symbols = self._symbols_from_csv(symbols_csv)
        bars_by_symbol = {
            symbol: []
            for symbol in symbols
        }
        page_token = None

        while True:
            params = dict(base_params)
            if page_token:
                params["page_token"] = page_token

            data = self._request(
                params=params,
                label="ATR daily bars fetch",
            )
            page_bars = data.get("bars", {})
            if not isinstance(page_bars, dict):
                raise RuntimeError(
                    "Malformed ATR daily bars response."
                )

            for symbol in symbols:
                raw_bars = page_bars.get(symbol, [])
                if isinstance(raw_bars, list):
                    bars_by_symbol[symbol].extend(
                        raw_bars
                    )

            page_token = data.get("next_page_token")
            if not page_token:
                break

        results: dict[str, float | None] = {}
        self.last_atr_diagnostics = {}

        for symbol in symbols:
            raw_bars = bars_by_symbol.get(symbol, [])

            valid_bars = [
                bar
                for bar in raw_bars
                if self._is_valid_bar(bar)
            ]

            if len(valid_bars) < 15:
                self.last_atr_diagnostics[symbol] = {
                    "status": "INSUFFICIENT_HISTORY",
                    "valid_daily_bars": len(valid_bars),
                    "required_daily_bars": 15,
                    "first_bar": (
                        str(valid_bars[0]["t"])
                        if valid_bars
                        else ""
                    ),
                    "last_bar": (
                        str(valid_bars[-1]["t"])
                        if valid_bars
                        else ""
                    ),
                }
                print(
                    f"{symbol}: insufficient valid daily bars "
                    f"for ATR ({len(valid_bars)} returned)"
                )
                results[symbol] = None
                continue

            try:
                results[symbol] = calculate_wilder_atr(
                    bars=valid_bars,
                    period=14,
                )
                self.last_atr_diagnostics[symbol] = {
                    "status": "AVAILABLE",
                    "valid_daily_bars": len(valid_bars),
                    "required_daily_bars": 15,
                    "first_bar": str(
                        valid_bars[0]["t"]
                    ),
                    "last_bar": str(
                        valid_bars[-1]["t"]
                    ),
                }
            except Exception as error:
                print(f"{symbol}: ATR calculation failed: {error}")
                results[symbol] = None
                self.last_atr_diagnostics[symbol] = {
                    "status": "CALCULATION_FAILED",
                    "valid_daily_bars": len(valid_bars),
                    "required_daily_bars": 15,
                    "first_bar": str(
                        valid_bars[0]["t"]
                    ),
                    "last_bar": str(
                        valid_bars[-1]["t"]
                    ),
                    "error": str(error),
                }

        return results

    def get_historical_daily_bars(
            self,
            symbols_csv: str,
            start_date: str,
            end_date: str,
            feed: str = MARKET_DATA_FEED,
    ) -> dict[str, list[dict]]:
        symbols = self._symbols_from_csv(symbols_csv)
        feed = self._validate_feed(feed)
        base_params = {
            "symbols": symbols_csv,
            "timeframe": "1Day",
            "start": f"{start_date}T00:00:00Z",
            "end": f"{end_date}T23:59:59Z",
            "adjustment": "raw",
            "feed": feed,
            "currency": "usd",
            "limit": 10_000,
            "sort": "asc",
        }
        results = {
            symbol: []
            for symbol in symbols
        }
        page_token = None

        while True:
            params = dict(base_params)
            if page_token:
                params["page_token"] = page_token
            data = self._request(
                params=params,
                label="Benchmark daily bars fetch",
            )
            page_bars = data.get("bars", {})
            if not isinstance(page_bars, dict):
                raise RuntimeError(
                    "Malformed benchmark daily bars response."
                )

            for symbol in symbols:
                raw_bars = page_bars.get(symbol, [])
                if isinstance(raw_bars, list):
                    results[symbol].extend(
                        bar
                        for bar in raw_bars
                        if self._is_valid_bar(bar)
                    )

            page_token = data.get("next_page_token")
            if not page_token:
                break

        for bars in results.values():
            bars.sort(key=lambda bar: str(bar["t"]))
        return results

    def get_opening_reliability(
            self,
            symbols_csv: str,
            date_str: str,
            lookback_days: int = 10,
            feed: str = MARKET_DATA_FEED,
    ) -> list[OpeningReliability]:
        """
        Measure genuine 09:30-09:44 opening-bar completeness
        across recent trading sessions.
        """
        feed = self._validate_feed(feed)
        symbols = self._symbols_from_csv(symbols_csv)

        end_date = datetime.strptime(
            date_str,
            "%Y-%m-%d",
        ).date() - timedelta(days=1)

        start_date = end_date - timedelta(
            days=max(lookback_days * 3, 21)
        )

        eastern = ZoneInfo("America/New_York")
        utc = ZoneInfo("UTC")

        start_dt = datetime.combine(
            start_date,
            time(hour=9, minute=30),
            tzinfo=eastern,
        ).astimezone(utc)

        end_dt = datetime.combine(
            end_date,
            time(hour=9, minute=44, second=59),
            tzinfo=eastern,
        ).astimezone(utc)

        bars_by_symbol = self.get_historical_1min_bars(
            symbols_csv=symbols_csv,
            start_iso=start_dt.strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
            end_iso=end_dt.strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
            feed=feed,
        )

        results: list[OpeningReliability] = []

        for symbol in symbols:
            bars_by_day: dict[str, set[str]] = {}

            for bar in bars_by_symbol.get(symbol, []):
                raw_timestamp = str(bar.get("t", ""))

                try:
                    timestamp = datetime.fromisoformat(
                        raw_timestamp.replace("Z", "+00:00")
                    ).astimezone(eastern)
                except ValueError:
                    continue

                if not (
                    timestamp.hour == 9
                    and 30 <= timestamp.minute <= 44
                ):
                    continue

                day = timestamp.date().isoformat()
                bars_by_day.setdefault(day, set()).add(
                    timestamp.strftime("%H:%M")
                )

            recent_days = sorted(
                bars_by_day,
                reverse=True,
            )[:lookback_days]

            total_bars = sum(
                min(len(bars_by_day[day]), 15)
                for day in recent_days
            )

            usable_days = len(recent_days)

            results.append(
                OpeningReliability(
                    symbol=symbol,
                    usable_days=usable_days,
                    total_bars=total_bars,
                    expected_bars=usable_days * 15,
                )
            )

        return results

    def get_scanner_statistics(
            self,
            symbols_csv: str,
            date_str: str,
            lookback_days: int = 30,
            feed: str = MARKET_DATA_FEED,
    ) -> list[StockStats]:
        if lookback_days < 1:
            raise ValueError(
                "lookback_days must be at least 1."
            )

        symbols = self._symbols_from_csv(symbols_csv)
        feed = self._validate_feed(feed)

        end_date = datetime.strptime(
            date_str,
            "%Y-%m-%d",
        ) - timedelta(days=1)

        start_date = end_date - timedelta(
            days=lookback_days * 3
        )

        params = {
            "symbols": ",".join(symbols),
            "timeframe": "1Day",
            "start": start_date.strftime(
                "%Y-%m-%dT00:00:00Z"
            ),
            "end": end_date.strftime(
                "%Y-%m-%dT23:59:59Z"
            ),
            "adjustment": "raw",
            "feed": feed,
            "currency": "usd",
            "limit": 10000,
            "sort": "desc",
        }

        data = self._request(
            params=params,
            label="Scanner daily bars fetch",
        )

        bars_by_symbol = data.get("bars", {})
        statistics = []

        for symbol in symbols:
            selected_bars = []

            for bar in bars_by_symbol.get(symbol, []):
                if not self._is_valid_bar(bar):
                    continue

                try:
                    volume = float(bar["v"])
                except (KeyError, TypeError, ValueError):
                    continue

                if volume < 0:
                    continue

                selected_bars.append((bar, volume))

                if len(selected_bars) == lookback_days:
                    break

            if not selected_bars:
                continue

            bar_count = len(selected_bars)

            avg_volume = sum(
                volume
                for _, volume in selected_bars
            ) / bar_count

            avg_price = sum(
                float(bar["c"])
                for bar, _ in selected_bars
            ) / bar_count

            avg_range = sum(
                float(bar["h"]) - float(bar["l"])
                for bar, _ in selected_bars
            ) / bar_count

            avg_range_pct = (
                (avg_range / avg_price) * 100
                if avg_price
                else 0.0
            )

            statistics.append(
                StockStats(
                    symbol=symbol,
                    valid_bars=bar_count,
                    avg_volume=avg_volume,
                    avg_price=avg_price,
                    avg_range=avg_range,
                    avg_range_pct=avg_range_pct,
                )
            )

        return statistics

    def test_connection(
        self,
        symbols_csv: str,
        feed: str = MARKET_DATA_FEED,
    ) -> dict[str, dict | None]:
        """
        Request recent daily bars to verify authentication
        and Alpaca market-data access.
        """
        end_time = datetime.now()
        start_time = end_time - timedelta(days=7)

        feed = self._validate_feed(feed)

        params = {
            "symbols": symbols_csv,
            "timeframe": "1Day",
            "start": start_time.strftime("%Y-%m-%dT00:00:00Z"),
            "end": end_time.strftime("%Y-%m-%dT23:59:59Z"),
            "adjustment": "raw",
            "feed": feed,
            "currency": "usd",
            "limit": 1000,
            "sort": "desc",
        }

        data = self._request(
            params=params,
            label="Alpaca connection test",
        )

        bars_by_symbol = data.get("bars", {})

        return {
            symbol: (bars_by_symbol.get(symbol) or [None])[0]
            for symbol in self._symbols_from_csv(symbols_csv)
        }
