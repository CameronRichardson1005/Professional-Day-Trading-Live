from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .indicators import calculate_wilder_atr
from .manipulation_selling_pressure_runner import (
    bar_date_et,
)


def daily_bar_date(bar: dict) -> str:
    text = str(bar["t"]).strip()

    if text.endswith("Z"):
        text = text[:-1] + "+00:00"

    return (
        datetime
        .fromisoformat(text)
        .astimezone(
            ZoneInfo("America/New_York")
        )
        .strftime("%Y-%m-%d")
    )


def build_atr_by_date(
    *,
    daily_bars: list[dict],
    test_dates: list[str],
    period: int = 14,
) -> dict[str, float]:
    """
    Build Wilder ATR values using ONLY daily bars before
    each test date.

    This prevents look-ahead bias.
    """
    sorted_daily = sorted(
        daily_bars,
        key=lambda bar: str(bar["t"]),
    )

    result = {}

    for test_date in sorted(
        set(test_dates)
    ):
        prior = [
            bar
            for bar in sorted_daily
            if daily_bar_date(bar)
            < test_date
        ]

        if len(prior) < period + 1:
            continue

        atr = calculate_wilder_atr(
            bars=prior,
            period=period,
        )

        if atr is not None:
            result[test_date] = atr

    return result


def build_research_dataset(
    *,
    alpaca,
    symbols: list[str],
    start_date: str,
    end_date: str,
    feed: str,
) -> dict:
    """
    Fetch the historical data required for selling-pressure
    research.

    Data:
    - native 09:30 15Min opening candles
    - native 5Min intraday bars
    - historical daily bars for prior-session ATR14

    No Sheets writes.
    No Webull.
    No live strategy state.
    """
    symbols_csv = ",".join(symbols)

    start = datetime.strptime(
        start_date,
        "%Y-%m-%d",
    )

    end = datetime.strptime(
        end_date,
        "%Y-%m-%d",
    )

    history_start = (
        start - timedelta(days=220)
    ).strftime("%Y-%m-%d")

    opening_bars = (
        alpaca.get_historical_opening_15min_bars(
            symbols_csv=symbols_csv,
            start_date=history_start,
            end_date=end_date,
            feed=feed,
        )
    )

    eastern = ZoneInfo(
        "America/New_York"
    )
    utc = ZoneInfo("UTC")

    intraday_start = (
        datetime.strptime(
            start_date,
            "%Y-%m-%d",
        )
        .replace(
            hour=9,
            minute=45,
            tzinfo=eastern,
        )
        .astimezone(utc)
        .strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
    )

    intraday_end = (
        datetime.strptime(
            end_date,
            "%Y-%m-%d",
        )
        .replace(
            hour=16,
            minute=0,
            tzinfo=eastern,
        )
        .astimezone(utc)
        .strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
    )

    intraday_bars = (
        alpaca.get_historical_5min_bars(
            symbols_csv=symbols_csv,
            start_iso=intraday_start,
            end_iso=intraday_end,
            feed=feed,
        )
    )

    daily_bars = (
        alpaca.get_historical_daily_bars(
            symbols_csv=symbols_csv,
            start_date=history_start,
            end_date=end_date,
            feed=feed,
        )
    )

    atr_by_symbol = {}

    for symbol in symbols:
        test_dates = [
            bar_date_et(bar)
            for bar in opening_bars.get(
                symbol,
                [],
            )
            if (
                start_date
                <= bar_date_et(bar)
                <= end_date
            )
        ]

        atr_by_symbol[symbol] = (
            build_atr_by_date(
                daily_bars=daily_bars.get(
                    symbol,
                    [],
                ),
                test_dates=test_dates,
            )
        )

    return {
        "opening_bars": opening_bars,
        "intraday_bars": intraday_bars,
        "daily_bars": daily_bars,
        "atr_by_symbol": atr_by_symbol,
    }
