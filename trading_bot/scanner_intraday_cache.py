from __future__ import annotations

import json
import time as time_module
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo


EASTERN = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")

DEFAULT_CHUNK_SESSIONS = 3


@dataclass(frozen=True)
class IntradayCacheSummary:
    symbols: int
    trading_sessions: int
    requests: int
    sessions_already_cached: int
    sessions_downloaded: int
    sessions_missing: tuple[
        tuple[str, str],
        ...,
    ]


def _normalized_symbols(
    symbols: Iterable[str],
) -> list[str]:
    return sorted({
        str(symbol)
        .strip()
        .upper()
        for symbol in symbols
        if str(symbol).strip()
    })


def _session_path(
    *,
    cache_dir: Path,
    symbol: str,
    date_str: str,
) -> Path:
    return (
        cache_dir
        / symbol
        / f"{date_str}.json"
    )


def load_cached_minute_session(
    *,
    cache_dir: Path,
    symbol: str,
    date_str: str,
) -> list[dict] | None:
    path = _session_path(
        cache_dir=cache_dir,
        symbol=symbol,
        date_str=date_str,
    )

    if not path.exists():
        return None

    try:
        payload = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )
    except (
        OSError,
        json.JSONDecodeError,
    ):
        return None

    if not isinstance(
        payload,
        list,
    ):
        return None

    result = [
        dict(bar)
        for bar in payload
        if isinstance(
            bar,
            dict,
        )
    ]

    result.sort(
        key=lambda bar: str(
            bar.get(
                "t",
                "",
            )
        )
    )

    return result


def _save_cached_minute_session(
    *,
    cache_dir: Path,
    symbol: str,
    date_str: str,
    bars: list[dict],
) -> None:
    path = _session_path(
        cache_dir=cache_dir,
        symbol=symbol,
        date_str=date_str,
    )

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary = path.with_suffix(
        ".json.tmp"
    )

    temporary.write_text(
        json.dumps(
            bars,
            separators=(
                ",",
                ":",
            ),
        ),
        encoding="utf-8",
    )

    temporary.replace(
        path
    )


def _bar_date_et(
    bar: dict,
) -> str | None:
    try:
        text = str(
            bar["t"]
        ).strip()

        if text.endswith("Z"):
            text = (
                text[:-1]
                + "+00:00"
            )

        timestamp = (
            datetime
            .fromisoformat(text)
        )

        if timestamp.tzinfo is None:
            timestamp = (
                timestamp.replace(
                    tzinfo=UTC
                )
            )

        return (
            timestamp
            .astimezone(
                EASTERN
            )
            .date()
            .isoformat()
        )

    except (
        KeyError,
        TypeError,
        ValueError,
    ):
        return None


def split_minute_bars_by_date(
    bars: Iterable[dict],
) -> dict[
    str,
    list[dict],
]:
    grouped: dict[
        str,
        list[dict],
    ] = {}

    for bar in bars:
        if not isinstance(
            bar,
            dict,
        ):
            continue

        date_str = _bar_date_et(
            bar
        )

        if date_str is None:
            continue

        grouped.setdefault(
            date_str,
            [],
        ).append(
            dict(bar)
        )

    for date_bars in (
        grouped.values()
    ):
        date_bars.sort(
            key=lambda bar: str(
                bar["t"]
            )
        )

    return grouped


def _session_window(
    first_session: date,
    last_session: date,
) -> tuple[
    datetime,
    datetime,
]:
    start = datetime.combine(
        first_session,
        time(
            hour=9,
            minute=30,
        ),
        tzinfo=EASTERN,
    ).astimezone(
        UTC
    )

    end = datetime.combine(
        last_session,
        time(
            hour=16,
            minute=0,
        ),
        tzinfo=EASTERN,
    ).astimezone(
        UTC
    )

    return (
        start,
        end,
    )


def cache_webull_minute_history(
    *,
    market_data,
    symbols: Iterable[str],
    trading_dates: Iterable[date],
    cache_dir: Path,
    chunk_sessions: int = (
        DEFAULT_CHUNK_SESSIONS
    ),
    request_delay_seconds: float = 0.25,
) -> IntradayCacheSummary:
    """
    Cache regular-session Webull 1-minute history.

    Sessions are fetched in groups of at most three. Three
    standard NYSE sessions contain 1,170 minute bars, which fits
    inside the Webull 1,200-bar request maximum.

    Existing valid JSON sessions are reused and never downloaded
    again.

    This function performs read-only market-data requests only.
    """
    if (
        chunk_sessions < 1
        or chunk_sessions > 3
    ):
        raise ValueError(
            "chunk_sessions must be "
            "between 1 and 3."
        )

    if request_delay_seconds < 0:
        raise ValueError(
            "request_delay_seconds "
            "cannot be negative."
        )

    normalized_symbols = (
        _normalized_symbols(
            symbols
        )
    )

    sessions = sorted(
        set(
            trading_dates
        )
    )

    cache_dir = Path(
        cache_dir
    )

    requests = 0
    already_cached = 0
    downloaded = 0

    missing: list[
        tuple[str, str]
    ] = []

    total_work = (
        len(normalized_symbols)
        * len(sessions)
    )

    completed_work = 0

    for symbol in (
        normalized_symbols
    ):
        for offset in range(
            0,
            len(sessions),
            chunk_sessions,
        ):
            chunk = sessions[
                offset:
                offset
                + chunk_sessions
            ]

            if not chunk:
                continue

            uncached_dates = []

            for session in chunk:
                date_str = (
                    session.isoformat()
                )

                cached = (
                    load_cached_minute_session(
                        cache_dir=cache_dir,
                        symbol=symbol,
                        date_str=date_str,
                    )
                )

                if cached is None:
                    uncached_dates.append(
                        session
                    )
                else:
                    already_cached += 1
                    completed_work += 1

            if not uncached_dates:
                continue

            start, end = (
                _session_window(
                    chunk[0],
                    chunk[-1],
                )
            )

            response = (
                market_data
                .get_historical_1min_bars(
                    symbols_csv=symbol,
                    start_iso=(
                        start.strftime(
                            "%Y-%m-%dT%H:%M:%SZ"
                        )
                    ),
                    end_iso=(
                        end.strftime(
                            "%Y-%m-%dT%H:%M:%SZ"
                        )
                    ),
                )
            )

            requests += 1

            grouped = (
                split_minute_bars_by_date(
                    response.get(
                        symbol,
                        [],
                    )
                )
            )

            for session in (
                uncached_dates
            ):
                date_str = (
                    session.isoformat()
                )

                bars = grouped.get(
                    date_str,
                    [],
                )

                if not bars:
                    missing.append(
                        (
                            symbol,
                            date_str,
                        )
                    )
                    completed_work += 1
                    continue

                _save_cached_minute_session(
                    cache_dir=cache_dir,
                    symbol=symbol,
                    date_str=date_str,
                    bars=bars,
                )

                downloaded += 1
                completed_work += 1

            print(
                "Webull intraday cache: "
                f"{completed_work}/{total_work} "
                "symbol-session(s)"
            )

            if (
                request_delay_seconds
                > 0
            ):
                time_module.sleep(
                    request_delay_seconds
                )

    return IntradayCacheSummary(
        symbols=len(
            normalized_symbols
        ),
        trading_sessions=len(
            sessions
        ),
        requests=requests,
        sessions_already_cached=(
            already_cached
        ),
        sessions_downloaded=(
            downloaded
        ),
        sessions_missing=tuple(
            missing
        ),
    )
