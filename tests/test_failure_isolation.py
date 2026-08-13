from types import SimpleNamespace

import pytest

import trading_bot.bot as bot_module
from trading_bot.bot import TradingBot


def test_ticker_failure_does_not_stop_remaining_tickers(
    monkeypatch,
):
    events = []
    bot = object.__new__(TradingBot)

    bot.stocks = {
        "FAIL": SimpleNamespace(
            symbol="FAIL",
            signal=None,
        ),
        "PASS": SimpleNamespace(
            symbol="PASS",
            signal=None,
        ),
    }

    class FakeWebullStrategyMarketData:
        def get_opening_15min_bars(
            self,
            symbols_csv,
            date_str,
        ):
            events.append("opening bars requested")
            return {
                "FAIL": {"test": "bar"},
                "PASS": {"test": "bar"},
            }

        def get_previous_day_ranges_all(
            self,
            symbols_csv,
            date_str,
        ):
            events.append("ATRs requested")
            return {
                "FAIL": 1.0,
                "PASS": 1.0,
            }

    class FakeStrategy:
        def evaluate(
            self,
            stock,
            opening_bar,
            atr,
        ):
            events.append(f"evaluated {stock.symbol}")

            if stock.symbol == "FAIL":
                raise RuntimeError(
                    "CONTROLLED TICKER FAILURE"
                )

            stock.signal = "INVEST"

    bot.webull_strategy_market_data = (
        FakeWebullStrategyMarketData()
    )
    bot.strategy = FakeStrategy()
    bot.symbols_csv = "FAIL,PASS"

    bot.calculate_strategy("2026-07-23")

    assert bot.stocks["FAIL"].signal == "NO INVEST"
    assert bot.stocks["PASS"].signal == "INVEST"
    assert events == [
        "opening bars requested",
        "ATRs requested",
        "evaluated FAIL",
        "evaluated PASS",
    ]


def test_orders_write_is_attempted_when_invest_write_fails():
    events = []
    bot = object.__new__(TradingBot)

    bot.stocks = {
        "OPEN": SimpleNamespace(
            symbol="OPEN",
            signal="INVEST",
        ),
    }

    bot.calculate_strategy = lambda date_str: events.append(
        "strategy calculated"
    )
    bot.initialise_sheets = lambda: events.append(
        "sheets initialised"
    )

    class FakeSheets:
        def write_strategy_results(
            self,
            date_str,
            stocks,
                sheet_name="Invest",
        ):
            events.append(f"{sheet_name} attempted")
            raise RuntimeError(
                "CONTROLLED INVEST FAILURE"
            )

        def write_orders(
            self,
            date_str,
            stocks,
                sheet_name="Orders",
        ):
            events.append(f"{sheet_name} attempted")

    bot.sheets = FakeSheets()

    with pytest.raises(
        RuntimeError,
        match="One or more strategy writes failed",
    ):
        bot.run_strategy_and_write(
            date_str="2026-07-23"
        )

    assert events == [
        "strategy calculated",
        "sheets initialised",
        "Invest attempted",
        "Orders attempted",
    ]
