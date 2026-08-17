from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import trading_bot.bot as bot_module

from trading_bot.bot import TradingBot
from trading_bot.config import (
    CANDIDATE_TICKERS,
    TICKERS,
)
from trading_bot.market_calendar import (
    nyse_trading_dates,
)
from trading_bot.scanner import StockStats
from trading_bot.webull_strategy_market_data import (
    WebullStrategyMarketData,
)


def _statistics():
    return [
        StockStats(
            symbol=CANDIDATE_TICKERS[index],
            valid_bars=30,
            avg_volume=(
                1_000_000
                + index * 100_000
            ),
            avg_price=10.0 + index,
            avg_range=1.0,
            avg_range_pct=(
                5.0 + index
            ),
        )
        for index in range(4)
    ]


class FakeWebull:
    def __init__(self):
        self.statistics_calls = 0
        self.reliability_calls = 0

    def get_scanner_statistics(
            self,
            **kwargs,
    ):
        self.statistics_calls += 1
        return _statistics()

    def get_opening_reliability(
            self,
            **kwargs,
    ):
        self.reliability_calls += 1
        return None


class FailingWebull:
    def get_scanner_statistics(
            self,
            **kwargs,
    ):
        raise RuntimeError(
            "CONTROLLED WEBULL FAILURE"
        )




def test_production_scanner_prefers_webull(
        monkeypatch,
):
    monkeypatch.setattr(
        bot_module,
        "MARKET_DATA_PROVIDER",
        "webull",
    )

    bot = TradingBot()

    webull = FakeWebull()

    bot.webull_strategy_market_data = (
        webull
    )

    selected = (
        bot.refresh_symbols_for_date(
            "2026-08-13"
        )
    )

    assert bot.scanner_data_source == "WEBULL"

    assert webull.statistics_calls == 1
    assert webull.reliability_calls == 1

    assert selected[:len(TICKERS)] == TICKERS

    assert len(selected) == (
        len(TICKERS)
        + bot.scanner.rules.candidate_limit
    )


def test_webull_failure_keeps_existing_symbols(
        monkeypatch,
):
    monkeypatch.setattr(
        bot_module,
        "MARKET_DATA_PROVIDER",
        "webull",
    )

    bot = TradingBot()

    original_symbols = list(
        bot.scanner.current_symbols
    )

    bot.webull_strategy_market_data = (
        FailingWebull()
    )

    selected = bot.refresh_symbols_for_date(
        "2026-08-13"
    )

    assert selected == original_symbols
    assert bot.scanner_data_source is None

def test_webull_native_opening_reliability(
        monkeypatch,
):
    adapter = WebullStrategyMarketData(
        market_data=None
    )

    trading_date = date(
        2026,
        8,
        13,
    )

    sessions = list(
        nyse_trading_dates(
            date(2026, 7, 20),
            date(2026, 8, 12),
        )
    )[-10:]

    eastern = ZoneInfo(
        "America/New_York"
    )

    bars = []

    # Deliberately omit one of ten expected sessions.
    for session in sessions[:-1]:
        session_date = (
            datetime.fromisoformat(
                session.isoformat()[:10]
            ).date()
        )

        timestamp = datetime.combine(
            session_date,
            time(
                hour=9,
                minute=30,
            ),
            tzinfo=eastern,
        )

        bars.append(
            {
                "t": (
                    timestamp
                    .astimezone(
                        ZoneInfo("UTC")
                    )
                    .isoformat()
                    .replace(
                        "+00:00",
                        "Z",
                    )
                ),
                "o": 10.0,
                "h": 11.0,
                "l": 9.0,
                "c": 10.5,
                "v": 1_000_000,
            }
        )

    monkeypatch.setattr(
        adapter,
        "_history",
        lambda **kwargs: bars,
    )

    results = (
        adapter.get_opening_reliability(
            symbols_csv="TEST",
            date_str=(
                trading_date.isoformat()
            ),
            lookback_days=10,
        )
    )

    assert len(results) == 1

    result = results[0]

    assert result.usable_days == 10
    assert result.total_bars == 9
    assert result.expected_bars == 10
    assert result.completeness == 0.9
