from types import SimpleNamespace

from trading_bot.bot import TradingBot


class CaptureTradingSheets:
    def __init__(self):
        self.date_str = None
        self.previews = None

    def write_trade_previews_today(
        self,
        *,
        date_str,
        previews,
        sheet_name="Trade Previews",
    ):
        self.date_str = date_str
        self.previews = list(previews)


def build_bot():
    bot = object.__new__(TradingBot)

    bot.trading_sheets = CaptureTradingSheets()
    bot.initialise_trading_sheets = lambda: None

    bot.stocks = {}
    bot.quick_flip_webull_previews = []
    bot.quick_flip_results = {}

    bot.live_committed_policy_manipulation_funded = False
    bot.live_committed_policy_quick_flip_funded = False

    return bot


def test_manipulation_preview_failure_reaches_trade_previews():
    bot = build_bot()

    bot.stocks = {
        "SOXL": SimpleNamespace(
            symbol="SOXL",
            webull_preview={
                "status": "PREVIEW FAILED",
                "symbol": "SOXL",
                "submitted": False,
                "error": (
                    "SOXL has insufficient remaining account "
                    "exposure allowance for one share."
                ),
            },
        ),
    }

    bot.write_trade_previews_dashboard(
        date_str="2026-08-19",
    )

    assert len(bot.trading_sheets.previews) == 1

    preview = bot.trading_sheets.previews[0]

    assert preview["strategy"] == "Manipulation"
    assert preview["symbol"] == "SOXL"
    assert preview["status"] == "PREVIEW FAILED"


def test_quick_flip_preview_failure_is_not_duplicated_as_blocked():
    bot = build_bot()

    bot.quick_flip_webull_previews = [
        {
            "status": "PREVIEW FAILED",
            "symbol": "OPEN",
            "submitted": False,
            "error": "Example preview failure.",
        },
    ]

    bot.quick_flip_results = {
        "OPEN": SimpleNamespace(
            signal=SimpleNamespace(
                signal="INVEST",
            ),
        ),
    }

    bot.write_trade_previews_dashboard(
        date_str="2026-08-19",
    )

    assert len(bot.trading_sheets.previews) == 1

    preview = bot.trading_sheets.previews[0]

    assert preview["strategy"] == "Quick Flip"
    assert preview["symbol"] == "OPEN"
    assert preview["status"] == "PREVIEW FAILED"
