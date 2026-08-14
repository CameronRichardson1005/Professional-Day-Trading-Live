from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from webull.data.common.category import Category
from webull.data.common.timespan import Timespan

from .indicators import calculate_wilder_atr
from .scanner import OpeningReliability, StockStats


EASTERN = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")


def _symbols_from_csv(
    symbols_csv: str,
) -> list[str]:
    symbols = []

    for raw in symbols_csv.split(","):
        symbol = raw.strip().upper()

        if symbol and symbol not in symbols:
            symbols.append(symbol)

    if not symbols:
        raise ValueError(
            "At least one symbol is required."
        )

    return symbols


def _parse_webull_time(
    value,
) -> datetime:
    text = str(value).strip()

    if not text:
        raise ValueError(
            "Webull bar timestamp is missing."
        )

    result = datetime.fromisoformat(
        text
    )

    if result.tzinfo is None:
        result = result.replace(
            tzinfo=UTC
        )

    return result


def _normalize_bar(
    raw: dict,
) -> dict | None:
    if not isinstance(raw, dict):
        return None

    try:
        timestamp = _parse_webull_time(
            raw["time"]
        )

        open_price = float(
            raw["open"]
        )

        high_price = float(
            raw["high"]
        )

        low_price = float(
            raw["low"]
        )

        close_price = float(
            raw["close"]
        )

        volume = float(
            raw.get(
                "volume",
                0,
            )
            or 0
        )

    except (
        KeyError,
        TypeError,
        ValueError,
    ):
        return None

    if min(
        open_price,
        high_price,
        low_price,
        close_price,
    ) <= 0:
        return None

    if high_price < low_price:
        return None

    if not (
        low_price
        <= open_price
        <= high_price
    ):
        return None

    if not (
        low_price
        <= close_price
        <= high_price
    ):
        return None

    if volume < 0:
        return None

    return {
        "t": (
            timestamp
            .astimezone(UTC)
            .isoformat()
            .replace(
                "+00:00",
                "Z",
            )
        ),
        "o": open_price,
        "h": high_price,
        "l": low_price,
        "c": close_price,
        "v": volume,
    }


class WebullStrategyMarketData:
    """
    Read-only Webull market-data adapter for
    Manipulation and Quick Flip.

    It deliberately returns Alpaca-compatible
    normalized OHLCV dictionaries so strategy
    calculations do not need to change.

    No order functionality exists here.
    """

    def __init__(
        self,
        *,
        market_data,
    ) -> None:
        self.market_data = market_data
        self.last_atr_diagnostics = {}

    def _history(
        self,
        *,
        symbol: str,
        timespan,
        count: int,
    ) -> list[dict]:
        response = (
            self.market_data
            .get_history_bar(
                symbol,
                Category.US_STOCK,
                timespan,
                count=str(count),
            )
        )

        status = getattr(
            response,
            "status_code",
            None,
        )

        if status != 200:
            raise RuntimeError(
                "Webull history request "
                f"failed with HTTP {status}."
            )

        try:
            payload = response.json()
        except Exception as error:
            raise RuntimeError(
                "Webull history returned "
                "invalid JSON."
            ) from error

        if not isinstance(
            payload,
            list,
        ):
            raise RuntimeError(
                "Webull history returned "
                "an unexpected response."
            )

        bars = []

        for raw in payload:
            bar = _normalize_bar(
                raw
            )

            if bar is not None:
                bars.append(
                    bar
                )

        bars.sort(
            key=lambda bar: bar["t"]
        )

        return bars

    def get_daily_history(
        self,
        *,
        symbols_csv: str,
        count: int = 400,
    ) -> dict[str, list[dict]]:
        """
        Fetch normalized Webull daily OHLCV history.

        This is read-only market data and performs no broker action.
        """
        if count < 1:
            raise ValueError(
                "count must be at least 1."
            )

        return {
            symbol: self._history(
                symbol=symbol,
                timespan=Timespan.D,
                count=count,
            )
            for symbol in _symbols_from_csv(
                symbols_csv
            )
        }

    @staticmethod
    def scanner_statistics_from_daily_history(
        *,
        daily_history: dict[
            str,
            list[dict],
        ],
        date_str: str,
        lookback_days: int = 30,
    ) -> list[StockStats]:
        """
        Reproduce the Alpaca scanner-statistics methodology from
        already-fetched normalized daily bars.

        Only bars strictly before date_str are eligible.
        The most recent `lookback_days` valid sessions are used.
        """
        if lookback_days < 1:
            raise ValueError(
                "lookback_days must be at least 1."
            )

        trading_date = (
            datetime.strptime(
                date_str,
                "%Y-%m-%d",
            ).date()
        )

        statistics = []

        for symbol, bars in (
            daily_history.items()
        ):
            prior = []

            for bar in bars:
                try:
                    timestamp = (
                        datetime.fromisoformat(
                            str(
                                bar["t"]
                            ).replace(
                                "Z",
                                "+00:00",
                            )
                        )
                    )

                    volume = float(
                        bar["v"]
                    )

                    open_price = float(
                        bar["o"]
                    )

                    high = float(
                        bar["h"]
                    )

                    low = float(
                        bar["l"]
                    )

                    close = float(
                        bar["c"]
                    )

                except (
                    KeyError,
                    TypeError,
                    ValueError,
                ):
                    continue

                if timestamp.date() >= trading_date:
                    continue

                if volume < 0:
                    continue

                if min(
                    open_price,
                    high,
                    low,
                    close,
                ) <= 0:
                    continue

                if high < low:
                    continue

                prior.append(
                    (
                        timestamp,
                        volume,
                        close,
                        high - low,
                    )
                )

            prior.sort(
                key=lambda row: row[0]
            )

            selected = prior[
                -lookback_days:
            ]

            if not selected:
                continue

            bar_count = len(
                selected
            )

            avg_volume = sum(
                row[1]
                for row in selected
            ) / bar_count

            avg_price = sum(
                row[2]
                for row in selected
            ) / bar_count

            avg_range = sum(
                row[3]
                for row in selected
            ) / bar_count

            avg_range_pct = (
                (
                    avg_range
                    / avg_price
                )
                * 100.0
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
                    avg_range_pct=(
                        avg_range_pct
                    ),
                )
            )

        return statistics

    def get_scanner_statistics(
        self,
        *,
        symbols_csv: str,
        date_str: str,
        lookback_days: int = 30,
        feed: str | None = None,
    ) -> list[StockStats]:
        """
        Webull implementation of scanner statistics.

        The method intentionally mirrors Alpaca's 30-valid-session
        scanner methodology for research comparisons.
        """
        del feed

        history = self.get_daily_history(
            symbols_csv=symbols_csv,
            count=max(
                120,
                lookback_days * 4,
            ),
        )

        return (
            self.scanner_statistics_from_daily_history(
                daily_history=history,
                date_str=date_str,
                lookback_days=lookback_days,
            )
        )

    def test_connection(
        self,
        symbols_csv: str,
    ) -> dict[str, dict | None]:
        """
        Verify read-only Webull historical market-data access.

        Returns the latest normalized daily bar available for each
        requested symbol. No brokerage functionality is involved.
        """
        history = self.get_daily_history(
            symbols_csv=symbols_csv,
            count=5,
        )

        return {
            symbol: (
                bars[-1]
                if bars
                else None
            )
            for symbol, bars
            in history.items()
        }

    def get_opening_reliability(
        self,
        *,
        symbols_csv: str,
        date_str: str,
        lookback_days: int = 10,
        feed: str | None = None,
    ) -> list[OpeningReliability]:
        """
        Measure availability of Webull's native completed
        09:30 15-minute opening candle over recent NYSE sessions.

        This intentionally differs from the old Alpaca/IEX
        minute-completeness measurement. Production strategies
        consume Webull native timeframe bars, so reliability is
        measured against the native opening bar actually required.
        """
        del feed

        if lookback_days < 1:
            raise ValueError(
                "lookback_days must be at least 1."
            )

        from .market_calendar import (
            nyse_trading_dates,
        )

        trading_date = (
            datetime.strptime(
                date_str,
                "%Y-%m-%d",
            ).date()
        )

        end_date = (
            trading_date
            - timedelta(days=1)
        )

        start_date = (
            end_date
            - timedelta(
                days=max(
                    lookback_days * 3,
                    21,
                )
            )
        )

        sessions = list(
            nyse_trading_dates(
                start_date,
                end_date,
            )
        )

        expected_dates = [
            session.isoformat()[:10]
            for session in sessions
        ][-lookback_days:]

        expected_set = set(
            expected_dates
        )

        results = []

        for symbol in _symbols_from_csv(
            symbols_csv
        ):
            bars = self._history(
                symbol=symbol,
                timespan=Timespan.M15,
                count=1000,
            )

            observed_dates = set()

            for bar in bars:
                try:
                    timestamp = (
                        datetime
                        .fromisoformat(
                            str(
                                bar["t"]
                            ).replace(
                                "Z",
                                "+00:00",
                            )
                        )
                        .astimezone(
                            EASTERN
                        )
                    )
                except ValueError:
                    continue

                day = (
                    timestamp
                    .date()
                    .isoformat()
                )

                if day not in expected_set:
                    continue

                if (
                    timestamp.hour == 9
                    and timestamp.minute == 30
                ):
                    observed_dates.add(
                        day
                    )

            results.append(
                OpeningReliability(
                    symbol=symbol,
                    usable_days=len(
                        expected_dates
                    ),
                    total_bars=len(
                        observed_dates
                    ),
                    expected_bars=len(
                        expected_dates
                    ),
                )
            )

        return results

    def get_historical_opening_15min_bars(
        self,
        *,
        symbols_csv: str,
        start_date: str,
        end_date: str,
        feed: str | None = None,
    ) -> dict[str, list[dict]]:
        """
        Return Webull native 09:30 ET 15-minute opening bars
        within the requested inclusive date range.

        This is read-only historical market data.
        """
        del feed

        start = datetime.strptime(
            start_date,
            "%Y-%m-%d",
        ).date()

        end = datetime.strptime(
            end_date,
            "%Y-%m-%d",
        ).date()

        if end < start:
            raise ValueError(
                "Historical opening-bar end date "
                "cannot be before start date."
            )

        results = {}

        for symbol in _symbols_from_csv(
            symbols_csv
        ):
            # 1000 is already exercised by the Webull
            # reliability path in this project and is ample
            # for the selling-pressure lookback requirement.
            bars = self._history(
                symbol=symbol,
                timespan=Timespan.M15,
                count=1000,
            )

            opening_bars = []

            for bar in bars:
                try:
                    timestamp = (
                        datetime
                        .fromisoformat(
                            str(
                                bar["t"]
                            ).replace(
                                "Z",
                                "+00:00",
                            )
                        )
                        .astimezone(
                            EASTERN
                        )
                    )

                except (
                    TypeError,
                    ValueError,
                ):
                    continue

                if not (
                    start
                    <= timestamp.date()
                    <= end
                ):
                    continue

                if (
                    timestamp.hour == 9
                    and timestamp.minute == 30
                ):
                    opening_bars.append(
                        bar
                    )

            opening_bars.sort(
                key=lambda bar: bar["t"]
            )

            results[symbol] = (
                opening_bars
            )

        return results

    def get_opening_15min_bars(
        self,
        *,
        symbols_csv: str,
        date_str: str,
        feed: str | None = None,
    ) -> dict[
        str,
        dict | None,
    ]:
        del feed

        trading_date = (
            datetime.strptime(
                date_str,
                "%Y-%m-%d",
            ).date()
        )

        results = {}

        for symbol in _symbols_from_csv(
            symbols_csv
        ):
            bars = self._history(
                symbol=symbol,
                timespan=Timespan.M15,
                count=200,
            )

            opening = None

            for bar in bars:
                timestamp = (
                    datetime
                    .fromisoformat(
                        str(
                            bar["t"]
                        ).replace(
                            "Z",
                            "+00:00",
                        )
                    )
                    .astimezone(
                        EASTERN
                    )
                )

                if (
                    timestamp.date()
                    == trading_date
                    and timestamp.hour
                    == 9
                    and timestamp.minute
                    == 30
                ):
                    opening = bar
                    break

            results[symbol] = opening

        return results

    def get_previous_day_ranges_all(
        self,
        *,
        symbols_csv: str,
        date_str: str,
        feed: str | None = None,
    ) -> dict[
        str,
        float | None,
    ]:
        del feed

        trading_date = (
            datetime.strptime(
                date_str,
                "%Y-%m-%d",
            ).date()
        )

        results = {}
        self.last_atr_diagnostics = {}

        for symbol in _symbols_from_csv(
            symbols_csv
        ):
            bars = self._history(
                symbol=symbol,
                timespan=Timespan.D,
                count=200,
            )

            prior = []

            for bar in bars:
                timestamp = (
                    datetime
                    .fromisoformat(
                        str(
                            bar["t"]
                        ).replace(
                            "Z",
                            "+00:00",
                        )
                    )
                )

                if (
                    timestamp.date()
                    < trading_date
                ):
                    prior.append(
                        bar
                    )

            prior.sort(
                key=lambda bar: bar["t"]
            )

            if len(prior) < 15:
                results[symbol] = None

                self.last_atr_diagnostics[
                    symbol
                ] = {
                    "status": (
                        "INSUFFICIENT_HISTORY"
                    ),
                    "valid_daily_bars": (
                        len(prior)
                    ),
                    "required_daily_bars": 15,
                }

                continue

            try:
                atr = calculate_wilder_atr(
                    prior,
                    period=14,
                )

            except Exception as error:
                results[symbol] = None

                self.last_atr_diagnostics[
                    symbol
                ] = {
                    "status": "ERROR",
                    "error": str(error),
                }

                continue

            results[symbol] = atr

            self.last_atr_diagnostics[
                symbol
            ] = {
                "status": "OK",
                "valid_daily_bars": (
                    len(prior)
                ),
                "required_daily_bars": 15,
            }

        return results

    def _historical_intraday(
        self,
        *,
        symbols_csv: str,
        start_iso: str,
        end_iso: str,
        timespan,
        count: int,
    ) -> dict[
        str,
        list[dict],
    ]:
        start = datetime.fromisoformat(
            start_iso.replace(
                "Z",
                "+00:00",
            )
        )

        end = datetime.fromisoformat(
            end_iso.replace(
                "Z",
                "+00:00",
            )
        )

        if start.tzinfo is None:
            start = start.replace(
                tzinfo=UTC
            )

        if end.tzinfo is None:
            end = end.replace(
                tzinfo=UTC
            )

        results = {}

        for symbol in _symbols_from_csv(
            symbols_csv
        ):
            bars = self._history(
                symbol=symbol,
                timespan=timespan,
                count=count,
            )

            selected = []

            for bar in bars:
                timestamp = (
                    datetime
                    .fromisoformat(
                        str(
                            bar["t"]
                        ).replace(
                            "Z",
                            "+00:00",
                        )
                    )
                )

                if (
                    start
                    <= timestamp
                    <= end
                ):
                    selected.append(
                        bar
                    )

            results[symbol] = selected

        return results

    def get_historical_5min_bars(
        self,
        *,
        symbols_csv: str,
        start_iso: str,
        end_iso: str,
        feed: str | None = None,
    ) -> dict[
        str,
        list[dict],
    ]:
        del feed

        return self._historical_intraday(
            symbols_csv=symbols_csv,
            start_iso=start_iso,
            end_iso=end_iso,
            timespan=Timespan.M5,
            count=500,
        )

    def get_historical_1min_bars(
        self,
        *,
        symbols_csv: str,
        start_iso: str,
        end_iso: str,
        feed: str | None = None,
    ) -> dict[
        str,
        list[dict],
    ]:
        del feed

        return self._historical_intraday(
            symbols_csv=symbols_csv,
            start_iso=start_iso,
            end_iso=end_iso,
            timespan=Timespan.M1,
            count=1000,
        )
