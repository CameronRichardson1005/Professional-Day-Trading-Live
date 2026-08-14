from datetime import date
from pathlib import Path
from types import SimpleNamespace

import trading_bot.market_calendar as calendar_module
import trading_bot.scanner_intraday_cache as cache_module
import trading_bot.scanner_master_dataset as master_module
from trading_bot.bot import TradingBot
from trading_bot.config import (
    CANDIDATE_TICKERS,
    TICKERS,
)


def test_realized_research_uses_full_production_universe(
    monkeypatch,
    tmp_path,
):
    bot = object.__new__(
        TradingBot
    )

    scanner_path = (
        Path(tmp_path)
        / "scanner.csv"
    )

    scanner_path.write_text(
        (
            "date,source,model,rank,"
            "selected,symbol,score\n"
        ),
        encoding="utf-8",
    )

    scanner_calls = []

    def fake_scanner_research(
        start_date_str,
        end_date_str,
        data_feed,
    ):
        scanner_calls.append(
            (
                start_date_str,
                end_date_str,
                data_feed,
            )
        )

        return {
            "output_path": str(
                scanner_path
            ),
        }

    bot.run_scanner_research = (
        fake_scanner_research
    )

    market_calls = []

    class FakeWebull:
        def get_historical_opening_15min_bars(
            self,
            *,
            symbols_csv,
            start_date,
            end_date,
        ):
            market_calls.append(
                (
                    "opening",
                    symbols_csv,
                    start_date,
                    end_date,
                )
            )
            return {}

        def get_daily_history(
            self,
            *,
            symbols_csv,
            count,
        ):
            market_calls.append(
                (
                    "daily",
                    symbols_csv,
                    count,
                )
            )
            return {}

    webull = FakeWebull()

    bot._get_webull_strategy_market_data = (
        lambda: webull
    )

    monkeypatch.setattr(
        calendar_module,
        "nyse_trading_dates",
        lambda start, end: [
            date(
                2026,
                8,
                13,
            )
        ],
    )

    cache_symbols = []

    def fake_cache(
        *,
        market_data,
        symbols,
        trading_dates,
        cache_dir,
    ):
        assert market_data is webull

        cache_symbols.extend(
            symbols
        )

        return SimpleNamespace(
            requests=0,
            sessions_already_cached=(
                len(symbols)
            ),
            sessions_downloaded=0,
            sessions_missing=(),
        )

    monkeypatch.setattr(
        cache_module,
        "cache_webull_minute_history",
        fake_cache,
    )

    monkeypatch.setattr(
        cache_module,
        "load_cached_minute_session",
        lambda **kwargs: [],
    )

    monkeypatch.setattr(
        master_module,
        "load_webull_scanner_index",
        lambda path: {},
    )

    monkeypatch.setattr(
        master_module,
        "build_atr_history",
        lambda **kwargs: {},
    )

    master_symbols = []

    def fake_build_master_rows(
        *,
        trading_dates,
        symbols,
        scanner_index,
        opening_history,
        atr_history,
        minute_loader,
    ):
        master_symbols.extend(
            symbols
        )

        return [
            {
                "evaluation_status": "OK",
            }
        ]

    monkeypatch.setattr(
        master_module,
        "build_master_rows",
        fake_build_master_rows,
    )

    written = []

    monkeypatch.setattr(
        master_module,
        "write_master_csv",
        lambda *,
        rows,
        output_path: written.append(
            (
                rows,
                output_path,
            )
        ),
    )

    result = (
        bot.run_scanner_realized_research(
            "2026-08-13",
            "2026-08-13",
            data_feed="iex",
        )
    )

    expected = sorted(
        set(TICKERS)
        | set(CANDIDATE_TICKERS)
    )

    assert cache_symbols == expected
    assert master_symbols == expected

    assert scanner_calls == [
        (
            "2026-08-13",
            "2026-08-13",
            "iex",
        )
    ]

    opening_call = next(
        call
        for call in market_calls
        if call[0] == "opening"
    )

    daily_call = next(
        call
        for call in market_calls
        if call[0] == "daily"
    )

    assert (
        opening_call[1].split(",")
        == expected
    )

    assert (
        daily_call[1].split(",")
        == expected
    )

    assert result["symbols"] == len(
        expected
    )

    assert result["rows"] == 1

    assert written

    assert (
        written[0][1].name
        == (
            "scanner_realized_master_"
            "2026-08-13_to_"
            "2026-08-13.csv"
        )
    )
