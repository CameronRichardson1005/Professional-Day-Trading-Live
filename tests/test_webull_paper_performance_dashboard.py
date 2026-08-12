from types import SimpleNamespace

from trading_bot.bot import TradingBot


def make_report():
    return SimpleNamespace(
        date="2026-08-07",
        orders_approved=5,
        trades_entered=4,
        open_trades=0,
        closed_trades=4,
        no_entry=1,
        target_exits=2,
        stop_exits=1,
        time_exits=1,
        profitable_trades=3,
        losing_trades=1,
        breakeven_trades=0,
        win_rate_pct=75.0,
        realized_pnl=8.42,
        average_pnl_per_trade=2.105,
        average_return_pct=1.84,
        average_winner=3.47,
        average_loser=-1.99,
        expectancy_per_trade=2.105,
        average_mfe_pct=3.4,
        average_mae_pct=-1.1,
        best_trade_symbol="OPEN",
        best_trade_pnl=4.50,
        worst_trade_symbol="SOUN",
        worst_trade_pnl=-1.99,
    )


def test_dashboard_performance_only_on_final_session(
    monkeypatch,
):
    bot = object.__new__(TradingBot)

    calls = []

    monkeypatch.setattr(
        "trading_bot.bot.load_webull_paper_daily_performance",
        lambda **kwargs: (
            calls.append(kwargs)
            or make_report()
        ),
    )

    result = bot._dashboard_paper_performance(
        date_str="2026-08-07",
        source="REPLAY",
    )

    assert result is None
    assert calls == []


def test_final_dashboard_contains_daily_performance(
    monkeypatch,
):
    bot = object.__new__(TradingBot)

    monkeypatch.setattr(
        "trading_bot.bot.load_webull_paper_daily_performance",
        lambda **kwargs: make_report(),
    )

    result = bot._dashboard_paper_performance(
        date_str="2026-08-07",
        source="LIVE_MANIPULATION",
    )

    assert result["ordersApproved"] == 5
    assert result["tradesEntered"] == 4
    assert result["closedTrades"] == 4
    assert result["winRatePct"] == 75.0
    assert result["realizedPnl"] == 8.42

    assert result["bestTrade"] == {
        "symbol": "OPEN",
        "pnl": 4.50,
    }

    assert result["worstTrade"] == {
        "symbol": "SOUN",
        "pnl": -1.99,
    }

    assert result["simulationOnly"] is True
    assert result["brokerSubmitted"] is False


def test_dashboard_performance_failure_is_nonfatal(
    monkeypatch,
):
    bot = object.__new__(TradingBot)

    def fail(**kwargs):
        raise RuntimeError("ledger unavailable")

    monkeypatch.setattr(
        "trading_bot.bot.load_webull_paper_daily_performance",
        fail,
    )

    result = bot._dashboard_paper_performance(
        date_str="2026-08-07",
        source="LIVE_MANIPULATION",
    )

    assert result is None
