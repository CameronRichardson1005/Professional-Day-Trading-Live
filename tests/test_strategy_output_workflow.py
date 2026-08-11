from types import SimpleNamespace

from trading_bot.bot import TradingBot
from trading_bot.models import Stock


def make_bot():
    bot = object.__new__(TradingBot)
    bot.stocks = {
        "OPEN": Stock(symbol="OPEN"),
        "PLTR": Stock(symbol="PLTR"),
    }
    bot.sheets = None
    return bot


def test_current_invest_symbols_returns_only_invest():
    bot = make_bot()

    bot.stocks["OPEN"].signal = "INVEST"
    bot.stocks["PLTR"].signal = "NO INVEST"

    assert bot.current_invest_symbols() == ["OPEN"]


def test_signal_signature_is_stable_and_invest_only():
    bot = make_bot()

    stock = bot.stocks["OPEN"]
    stock.signal = "INVEST"
    stock.strategy_name = "FIBONACCI_61_8"
    stock.limit_buy = 10.50
    stock.limit_sell = 11.25
    stock.trading_stop_loss = 10.20
    stock.confirmation_time = "10:08"

    first = bot.current_signal_signature()
    second = bot.current_signal_signature()

    assert first == second
    assert len(first) == 1
    assert first[0][0] == "OPEN"


def test_evaluation_does_not_write_external_outputs():
    bot = make_bot()
    events = []

    bot.calculate_strategy = (
        lambda date_str: events.append("calculate")
    )
    bot.stocks["OPEN"].signal = "INVEST"

    result = bot.evaluate_active_strategy(
        date_str="2026-08-03",
    )

    assert result == ["OPEN"]
    assert events == ["calculate"]


def test_publish_writes_invest_then_previews_then_orders():
    bot = make_bot()
    events = []

    bot.sheets = SimpleNamespace(
        write_strategy_results=lambda **kwargs: (
            events.append("invest")
        ),
        write_orders=lambda **kwargs: (
            events.append("orders")
        ),
    )

    bot.initialise_sheets = (
        lambda: events.append("initialise")
    )
    bot.prepare_webull_previews = (
        lambda: events.append("previews") or []
    )

    bot.publish_current_strategy_results(
        date_str="2026-08-03",
    )

    assert events == [
        "initialise",
        "invest",
        "previews",
        "orders",
    ]


def test_finalisation_is_separate(monkeypatch):
    bot = make_bot()
    events = []

    monkeypatch.setattr(
        "trading_bot.bot.load_webull_paper_daily_performance",
        lambda **kwargs: SimpleNamespace(
            date=kwargs["date_str"],
        ),
    )

    monkeypatch.setattr(
        "trading_bot.bot.load_webull_paper_analytics",
        lambda **kwargs: SimpleNamespace(),
    )

    bot.sheets = SimpleNamespace(
        write_paper_performance=lambda **kwargs: (
            events.append("paper-performance")
        ),
        write_paper_analytics=lambda **kwargs: (
            events.append("paper-analytics")
        ),
        finalise_daily_workbook=lambda **kwargs: (
            events.append("finalise")
        ),
    )

    bot.finalise_strategy_workbook("2026-08-03")

    assert events == [
        "paper-performance",
        "paper-analytics",
        "finalise",
    ]


def test_compatibility_workflow_can_skip_finalisation():
    bot = make_bot()
    events = []

    bot.evaluate_active_strategy = (
        lambda **kwargs: events.append("evaluate")
    )
    bot.publish_current_strategy_results = (
        lambda **kwargs: events.append("publish")
    )
    bot.finalise_strategy_workbook = (
        lambda **kwargs: events.append("finalise")
    )

    bot.run_strategy_and_write(
        date_str="2026-08-03",
        finalise=False,
    )

    assert events == [
        "evaluate",
        "publish",
    ]
