from datetime import date
from pathlib import Path

import pytest

from trading_bot.scanner_intraday_cache import (
    cache_webull_minute_history,
    load_cached_minute_session,
    split_minute_bars_by_date,
)


def minute_bar(
    timestamp,
):
    return {
        "t": timestamp,
        "o": 10.0,
        "h": 10.1,
        "l": 9.9,
        "c": 10.0,
        "v": 1000,
    }


def test_split_minute_bars_uses_new_york_date():
    result = (
        split_minute_bars_by_date([
            minute_bar(
                "2026-03-02T14:30:00Z"
            ),
            minute_bar(
                "2026-03-03T14:30:00Z"
            ),
        ])
    )

    assert sorted(
        result
    ) == [
        "2026-03-02",
        "2026-03-03",
    ]


def test_cache_fetches_three_sessions_in_one_request(
    tmp_path,
):
    calls = []

    class FakeMarketData:
        def get_historical_1min_bars(
            self,
            *,
            symbols_csv,
            start_iso,
            end_iso,
        ):
            calls.append({
                "symbol": symbols_csv,
                "start": start_iso,
                "end": end_iso,
            })

            return {
                symbols_csv: [
                    minute_bar(
                        "2026-03-02T14:30:00Z"
                    ),
                    minute_bar(
                        "2026-03-03T14:30:00Z"
                    ),
                    minute_bar(
                        "2026-03-04T14:30:00Z"
                    ),
                ]
            }

    summary = cache_webull_minute_history(
        market_data=FakeMarketData(),
        symbols=["TEST"],
        trading_dates=[
            date(
                2026,
                3,
                2,
            ),
            date(
                2026,
                3,
                3,
            ),
            date(
                2026,
                3,
                4,
            ),
        ],
        cache_dir=tmp_path,
        request_delay_seconds=0,
    )

    assert summary.requests == 1
    assert (
        summary.sessions_downloaded
        == 3
    )

    assert (
        summary.sessions_missing
        == ()
    )

    assert len(calls) == 1

    for date_str in (
        "2026-03-02",
        "2026-03-03",
        "2026-03-04",
    ):
        cached = (
            load_cached_minute_session(
                cache_dir=tmp_path,
                symbol="TEST",
                date_str=date_str,
            )
        )

        assert cached is not None
        assert len(cached) == 1


def test_cache_reuses_existing_sessions(
    tmp_path,
):
    class FakeMarketData:
        def __init__(self):
            self.calls = 0

        def get_historical_1min_bars(
            self,
            *,
            symbols_csv,
            start_iso,
            end_iso,
        ):
            self.calls += 1

            return {
                symbols_csv: [
                    minute_bar(
                        "2026-03-02T14:30:00Z"
                    ),
                ]
            }

    market = FakeMarketData()

    dates = [
        date(
            2026,
            3,
            2,
        ),
    ]

    first = cache_webull_minute_history(
        market_data=market,
        symbols=["TEST"],
        trading_dates=dates,
        cache_dir=tmp_path,
        request_delay_seconds=0,
    )

    second = cache_webull_minute_history(
        market_data=market,
        symbols=["TEST"],
        trading_dates=dates,
        cache_dir=tmp_path,
        request_delay_seconds=0,
    )

    assert first.requests == 1
    assert second.requests == 0
    assert (
        second.sessions_already_cached
        == 1
    )

    assert market.calls == 1


def test_cache_rejects_more_than_three_sessions_per_request(
    tmp_path,
):
    with pytest.raises(
        ValueError,
        match="between 1 and 3",
    ):
        cache_webull_minute_history(
            market_data=None,
            symbols=["TEST"],
            trading_dates=[],
            cache_dir=Path(
                tmp_path
            ),
            chunk_sessions=4,
            request_delay_seconds=0,
        )
