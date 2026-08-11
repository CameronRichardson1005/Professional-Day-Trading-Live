from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from trading_bot.bot import TradingBot
from trading_bot.webull_trade_history import (
    WebullFill,
)


EASTERN = ZoneInfo("America/New_York")


class FakeHistoryClient:
    def get_recent_fills(self):
        return [
            WebullFill(
                symbol="MARA",
                side="BUY",
                quantity=20,
                price=9.65,
                filled_at=datetime(
                    2026,
                    8,
                    11,
                    9,
                    54,
                    tzinfo=EASTERN,
                ),
            ),
            WebullFill(
                symbol="MARA",
                side="SELL",
                quantity=20,
                price=9.80,
                filled_at=datetime(
                    2026,
                    8,
                    11,
                    10,
                    5,
                    tzinfo=EASTERN,
                ),
            ),
        ]


class FakeSheets:
    def __init__(self):
        self.trade_calls = []
        self.summary_calls = []

    def write_webull_trade_pnl(
        self,
        **kwargs,
    ):
        self.trade_calls.append(kwargs)

    def write_webull_pnl_summary(
        self,
        **kwargs,
    ):
        self.summary_calls.append(kwargs)


def test_write_webull_daily_pnl_uses_read_only_history():
    bot = object.__new__(TradingBot)

    sheets = FakeSheets()

    bot.trading_sheets = sheets
    bot.initialise_trading_sheets = (
        lambda: None
    )

    result = bot.write_webull_daily_pnl(
        date_str="2026-08-11",
        history_client=FakeHistoryClient(),
    )

    assert len(
        sheets.trade_calls
    ) == 1

    assert len(
        sheets.summary_calls
    ) == 1

    summary = result["summary"]

    assert summary.closed_trades == 1
    assert summary.winning_trades == 1
    assert summary.realized_pnl == 3.00
