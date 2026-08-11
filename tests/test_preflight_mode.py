import main as main_module

from trading_bot.bot import TradingBot


def test_preflight_succeeds_without_starting_workflows():
    events = []

    class FakeSheets:
        def test_connection(self):
            events.append("test_connection")
            return [
                "Orders",
                "Scanner Dashboard",
                "1 minute intervals",
            ]

    bot = object.__new__(TradingBot)
    bot.scanner_statistics = object()
    bot.sheets = None
    bot.tracker = None

    def refresh_symbols(date_str):
        events.append(("refresh", date_str))
        return ["BBAI", "OPEN"]

    def initialise_sheets():
        events.append("initialise_sheets")
        bot.sheets = FakeSheets()
        bot.tracker = object()

    bot.refresh_symbols_for_date = refresh_symbols
    bot.initialise_sheets = initialise_sheets

    assert bot.run_preflight("2026-07-27") is True
    assert events == [
        ("refresh", "2026-07-27"),
        "initialise_sheets",
        "test_connection",
    ]


def test_preflight_stops_when_scanner_is_unavailable():
    bot = object.__new__(TradingBot)
    bot.scanner_statistics = None

    bot.refresh_symbols_for_date = (
        lambda date_str: ["BBAI", "OPEN"]
    )

    def unexpected_initialisation():
        raise AssertionError(
            "Sheets should not be initialised."
        )

    bot.initialise_sheets = unexpected_initialisation

    assert bot.run_preflight("2026-07-27") is False


def test_preflight_stops_when_required_sheet_is_missing():
    class FakeSheets:
        def test_connection(self):
            return [
                "Orders",
                "1 minute intervals",
            ]

    bot = object.__new__(TradingBot)
    bot.scanner_statistics = object()
    bot.sheets = None
    bot.tracker = None

    bot.refresh_symbols_for_date = (
        lambda date_str: ["BBAI", "OPEN"]
    )

    def initialise_sheets():
        bot.sheets = FakeSheets()
        bot.tracker = object()

    bot.initialise_sheets = initialise_sheets

    assert bot.run_preflight("2026-07-27") is False


def test_main_dispatches_preflight_mode(monkeypatch):
    calls = []

    class FakeBot:
        def run_preflight(self, date_str=None):
            calls.append(date_str)
            return True

    monkeypatch.setattr(
        main_module,
        "TradingBot",
        FakeBot,
    )
    monkeypatch.setattr(
        main_module,
        "setup_logging",
        lambda: "test.log",
    )
    monkeypatch.setattr(
        main_module.sys,
        "argv",
        [
            "main.py",
            "preflight",
            "2026-07-27",
        ],
    )

    assert main_module.main() == 0
    assert calls == ["2026-07-27"]
