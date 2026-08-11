from types import SimpleNamespace

import trading_bot.bot as bot_module

from trading_bot.bot import TradingBot
from trading_bot.dashboard_exporter import (
    DashboardExporter,
)


def group(key):
    return SimpleNamespace(
        key=key,
        approved_orders=3,
        entered_trades=2,
        closed_trades=2,
        no_entry=1,
        wins=1,
        losses=1,
        breakeven=0,
        target_exits=1,
        stop_exits=1,
        time_exits=0,
        win_rate_pct=50.0,
        realized_pnl=3.0,
        average_pnl_per_trade=1.5,
        average_return_pct=1.2,
        expectancy_per_trade=1.5,
        average_mfe_pct=3.4,
        average_mae_pct=-1.2,
        sample_label="VERY SMALL SAMPLE",
    )


def report():
    return SimpleNamespace(
        total_orders=3,
        entered_trades=2,
        closed_trades=2,
        open_trades=0,
        no_entry=1,
        realized_pnl=3.0,
        win_rate_pct=50.0,
        average_return_pct=1.2,
        expectancy_per_trade=1.5,
        by_symbol=(group("OPEN"),),
        by_entry_time=(
            group("10:00-10:14 ET"),
        ),
        by_reward_risk=(
            group("2.00-2.49"),
        ),
        by_impulse_atr=(
            group("0.75-0.99 ATR"),
        ),
        by_pullback_volume=(
            group("0.50-0.74"),
        ),
        by_confirmation_time=(
            group("10:00-10:14 ET"),
        ),
    )


def test_dashboard_analytics_final_session_only(
    monkeypatch,
):
    bot = object.__new__(TradingBot)

    monkeypatch.setattr(
        bot_module,
        "load_webull_paper_analytics",
        lambda: report(),
    )

    assert (
        bot._dashboard_paper_analytics(
            source="LIVE_FIBONACCI"
        )
        is None
    )

    result = bot._dashboard_paper_analytics(
        source="LIVE_FIBONACCI_FINAL"
    )

    assert result is not None
    assert result["totalOrders"] == 3
    assert result["closedTrades"] == 2
    assert result["realizedPnl"] == 3.0
    assert result["winRatePct"] == 50.0

    assert result["bySymbol"][0]["key"] == "OPEN"
    assert (
        result["bySymbol"][0]["sampleLabel"]
        == "VERY SMALL SAMPLE"
    )

    assert (
        result["byRewardRisk"][0]["key"]
        == "2.00-2.49"
    )
    assert (
        result["byImpulseAtr"][0]["key"]
        == "0.75-0.99 ATR"
    )
    assert (
        result["byPullbackVolume"][0]["key"]
        == "0.50-0.74"
    )

    assert result["simulationOnly"] is True
    assert result["brokerSubmitted"] is False


def test_dashboard_analytics_failure_is_nonfatal(
    monkeypatch,
):
    bot = object.__new__(TradingBot)

    def fail():
        raise RuntimeError("ledger unavailable")

    monkeypatch.setattr(
        bot_module,
        "load_webull_paper_analytics",
        fail,
    )

    result = bot._dashboard_paper_analytics(
        source="LIVE_FIBONACCI_FINAL"
    )

    assert result is None


def test_exporter_includes_paper_analytics():
    analytics = {
        "totalOrders": 3,
        "closedTrades": 2,
        "bySymbol": [],
        "simulationOnly": True,
        "brokerSubmitted": False,
    }

    payload = DashboardExporter.build_payload(
        date_str="2026-08-08",
        source="LIVE_FIBONACCI_FINAL",
        stocks={},
        processed_bars={},
        data_feed="iex",
        paper_analytics=analytics,
    )

    assert payload["paperAnalytics"] == analytics


def test_exporter_omits_paper_analytics_when_missing():
    payload = DashboardExporter.build_payload(
        date_str="2026-08-08",
        source="LIVE_FIBONACCI_FINAL",
        stocks={},
        processed_bars={},
        data_feed="iex",
    )

    assert "paperAnalytics" not in payload
