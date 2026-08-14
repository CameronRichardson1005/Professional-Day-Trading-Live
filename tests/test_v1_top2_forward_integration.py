from datetime import (
    date,
    datetime,
    timedelta,
)
from pathlib import Path
from zoneinfo import ZoneInfo

import trading_bot.bot as bot_module

from trading_bot.bot import TradingBot
from trading_bot.models import Stock
from trading_bot.scanner import (
    StockScanner,
    StockStats,
)
from trading_bot.v1_top2_forward_validation import (
    load_forward_rows,
)


EASTERN = ZoneInfo(
    "America/New_York"
)

UTC = ZoneInfo(
    "UTC"
)


def stats(
    symbol,
    range_pct,
):
    return StockStats(
        symbol=symbol,
        valid_bars=30,
        avg_volume=1_000_000,
        avg_price=10.0,
        avg_range=1.0,
        avg_range_pct=range_pct,
    )


def full_session_bars():
    start = datetime(
        2026,
        8,
        14,
        9,
        30,
        tzinfo=EASTERN,
    )

    bars = []

    for offset in range(390):
        timestamp = (
            start
            + timedelta(
                minutes=offset
            )
        ).astimezone(
            UTC
        )

        bars.append({
            "t": (
                timestamp
                .isoformat()
                .replace(
                    "+00:00",
                    "Z",
                )
            ),
            "o": 10.20,
            "h": 10.20,
            "l": 10.20,
            "c": 10.20,
            "v": 100,
        })

    return bars


def stock(
    symbol,
):
    value = Stock(
        symbol=symbol
    )

    value.opening_bar = {
        "t": "2026-08-14T13:30:00Z",
        "o": 10.50,
        "h": 11.00,
        "l": 10.00,
        "c": 10.20,
        "v": 100000,
    }

    value.atr = 1.0

    return value


class FakeMarketData:
    def get_historical_1min_bars(
        self,
        *,
        symbols_csv,
        start_iso,
        end_iso,
        feed=None,
    ):
        del (
            start_iso,
            end_iso,
            feed,
        )

        return {
            symbol: full_session_bars()
            for symbol
            in symbols_csv.split(",")
        }


def make_bot():
    bot = TradingBot.__new__(
        TradingBot
    )

    bot.scanner = StockScanner(
        current_symbols=[
            "CORE",
        ]
    )

    bot.scanner_statistics = [
        stats(
            "FIRST",
            9.0,
        ),
        stats(
            "SECOND",
            7.0,
        ),
        stats(
            "THIRD",
            5.0,
        ),
    ]

    bot.symbol_reliability = None
    bot.scanner_data_source = "WEBULL"

    bot.stocks = {
        symbol: stock(
            symbol
        )
        for symbol in (
            "FIRST",
            "SECOND",
            "THIRD",
        )
    }

    bot._get_webull_strategy_market_data = (
        lambda:
        FakeMarketData()
    )

    return bot


def test_eod_shadow_writes_frozen_top2_top3_rows(
    tmp_path,
):
    bot = make_bot()

    path = (
        Path(tmp_path)
        / "forward.csv"
    )

    bot._record_v1_top2_forward_validation(
        date_str="2026-08-14",
        output_path=path,
    )

    rows = load_forward_rows(
        path
    )

    assert len(rows) == 3

    assert [
        row.rank
        for row in rows
    ] == [
        1,
        2,
        3,
    ]

    assert [
        row.top2_challenger
        for row in rows
    ] == [
        True,
        True,
        False,
    ]

    assert all(
        row.top3_baseline
        for row in rows
    )


def test_eod_shadow_requires_webull_scanner(
    tmp_path,
):
    bot = make_bot()

    bot.scanner_data_source = (
        "ALPACA"
    )

    try:
        bot._record_v1_top2_forward_validation(
            date_str="2026-08-14",
            output_path=(
                Path(tmp_path)
                / "forward.csv"
            ),
        )
    except RuntimeError as error:
        assert (
            "requires the production "
            "scanner source to be WEBULL"
            in str(error)
        )
    else:
        raise AssertionError(
            "Expected WEBULL-only "
            "forward validation guard."
        )


def test_shadow_failure_cannot_fail_eod_production(
    monkeypatch,
):
    bot = TradingBot.__new__(
        TradingBot
    )

    calls = []

    bot.write_webull_daily_pnl = (
        lambda *,
        date_str:
        calls.append(
            (
                "PNL",
                date_str,
            )
        )
    )

    def fail_shadow(
        *,
        date_str,
    ):
        calls.append(
            (
                "SHADOW",
                date_str,
            )
        )

        raise RuntimeError(
            "simulated research failure"
        )

    bot._record_v1_top2_forward_validation = (
        fail_shadow
    )

    monkeypatch.setattr(
        bot_module.time_module,
        "sleep",
        lambda seconds: None,
    )

    bot._run_production_eod_pnl(
        date_str="2026-08-14",
        eastern=EASTERN,
    )

    assert (
        "PNL",
        "2026-08-14",
    ) in calls

    assert (
        "SHADOW",
        "2026-08-14",
    ) in calls


def test_pnl_failure_still_attempts_shadow(
    monkeypatch,
):
    bot = TradingBot.__new__(
        TradingBot
    )

    calls = []

    def fail_pnl(
        *,
        date_str,
    ):
        calls.append(
            (
                "PNL",
                date_str,
            )
        )

        raise RuntimeError(
            "simulated P&L failure"
        )

    def record_shadow(
        *,
        date_str,
    ):
        calls.append(
            (
                "SHADOW",
                date_str,
            )
        )

    bot.write_webull_daily_pnl = (
        fail_pnl
    )

    bot._record_v1_top2_forward_validation = (
        record_shadow
    )

    monkeypatch.setattr(
        bot_module.time_module,
        "sleep",
        lambda seconds: None,
    )

    bot._run_production_eod_pnl(
        date_str="2026-08-14",
        eastern=EASTERN,
    )

    assert calls == [
        (
            "PNL",
            "2026-08-14",
        ),
        (
            "SHADOW",
            "2026-08-14",
        ),
    ]
