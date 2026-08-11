from datetime import UTC, datetime
from types import SimpleNamespace

import trading_bot.bot as bot_module

from trading_bot.bot import TradingBot


def make_portfolio():
    return SimpleNamespace(
        starting_cash=10_000.0,
        cash=9_965.0,
        buying_power=9_965.0,
        open_cost_basis=40.0,
        market_value=42.0,
        realized_pnl=5.0,
        unrealized_pnl=2.0,
        total_pnl=7.0,
        equity=10_007.0,
        open_position_count=1,
        closed_position_count=1,
        pending_order_count=1,
        no_entry_count=1,
        overdrawn=False,
        open_positions=(
            SimpleNamespace(
                paper_order_id="paper-open",
                symbol="BBAI",
                quantity=10,
                fill_price=4.0,
                cost_basis=40.0,
                mark_price=4.2,
                mark_status="MARKED",
                market_value=42.0,
                unrealized_pnl=2.0,
                unrealized_return_pct=5.0,
                filled_at=datetime(
                    2026,
                    8,
                    7,
                    14,
                    1,
                    tzinfo=UTC,
                ),
                target_price=4.5,
                stop_price=3.8,
            ),
        ),
        closed_positions=(
            SimpleNamespace(
                paper_order_id="paper-closed",
                symbol="OPEN",
                quantity=10,
                fill_price=4.0,
                exit_price=4.5,
                realized_pnl=5.0,
                return_pct=12.5,
                exit_reason="TARGET",
                filled_at=datetime(
                    2026,
                    8,
                    7,
                    14,
                    0,
                    tzinfo=UTC,
                ),
                closed_at=datetime(
                    2026,
                    8,
                    7,
                    14,
                    5,
                    tzinfo=UTC,
                ),
            ),
        ),
    )


def test_dashboard_portfolio_only_for_live_fibonacci():
    bot = object.__new__(TradingBot)
    bot._webull_paper_portfolio_snapshot = (
        make_portfolio()
    )

    assert (
        bot._dashboard_paper_portfolio(
            date_str="2026-08-07",
            source="REPLAY",
        )
        is None
    )

    assert (
        bot._dashboard_paper_portfolio(
            date_str="2026-08-07",
            source="LIVE_MANIPULATION",
        )
        is None
    )


def test_dashboard_portfolio_contains_account_state():
    bot = object.__new__(TradingBot)
    bot._webull_paper_portfolio_snapshot = (
        make_portfolio()
    )

    result = bot._dashboard_paper_portfolio(
        date_str="2026-08-07",
        source="LIVE_FIBONACCI",
    )

    assert result["startingCash"] == 10_000
    assert result["cash"] == 9_965
    assert result["buyingPower"] == 9_965
    assert result["marketValue"] == 42
    assert result["realizedPnl"] == 5
    assert result["unrealizedPnl"] == 2
    assert result["totalPnl"] == 7
    assert result["equity"] == 10_007

    assert result["simulationOnly"] is True
    assert result["brokerSubmitted"] is False

    assert result["openPositions"][0]["symbol"] == "BBAI"
    assert result["openPositions"][0]["markPrice"] == 4.2

    assert (
        result["closedPositions"][0]["exitReason"]
        == "TARGET"
    )


def test_final_dashboard_uses_same_portfolio_shape():
    bot = object.__new__(TradingBot)
    bot._webull_paper_portfolio_snapshot = (
        make_portfolio()
    )

    result = bot._dashboard_paper_portfolio(
        date_str="2026-08-07",
        source="LIVE_FIBONACCI_FINAL",
    )

    assert result is not None
    assert result["equity"] == 10_007
    assert result["brokerSubmitted"] is False


def test_dashboard_portfolio_reconstructs_if_snapshot_missing(
    monkeypatch,
):
    bot = object.__new__(TradingBot)

    store = object()

    bot.webull_paper_lifecycle_tracker = (
        SimpleNamespace(
            store=store,
        )
    )

    seen = {}

    def load_portfolio(*, store):
        seen["store"] = store
        return make_portfolio()

    monkeypatch.setattr(
        bot_module,
        "load_webull_paper_portfolio",
        load_portfolio,
    )

    result = bot._dashboard_paper_portfolio(
        date_str="2026-08-07",
        source="LIVE_FIBONACCI",
    )

    assert seen["store"] is store
    assert result["equity"] == 10_007


def test_dashboard_portfolio_failure_is_nonfatal(
    monkeypatch,
):
    bot = object.__new__(TradingBot)

    bot.webull_paper_lifecycle_tracker = None

    def fail(**kwargs):
        raise RuntimeError("ledger unavailable")

    monkeypatch.setattr(
        bot_module,
        "load_webull_paper_portfolio",
        fail,
    )

    result = bot._dashboard_paper_portfolio(
        date_str="2026-08-07",
        source="LIVE_FIBONACCI",
    )

    assert result is None


def test_dashboard_portfolio_includes_risk_status(
    monkeypatch,
):
    bot = object.__new__(TradingBot)
    bot._webull_paper_portfolio_snapshot = (
        make_portfolio()
    )

    store = object()
    bot.webull_paper_lifecycle_tracker = (
        SimpleNamespace(store=store)
    )

    seen = {}

    def load_risk(*, date_str, store):
        seen["date_str"] = date_str
        seen["store"] = store

        return SimpleNamespace(
            trading_allowed=False,
            reason="PAPER_DAILY_LOSS_LIMIT_REACHED",
            available_for_new_orders=9_950.0,
            pending_reserved_cash=0.0,
            daily_realized_pnl=-50.0,
            max_daily_loss=50.0,
            remaining_daily_loss=0.0,
        )

    monkeypatch.setattr(
        bot_module,
        "load_webull_paper_risk_status",
        load_risk,
    )

    result = bot._dashboard_paper_portfolio(
        date_str="2026-08-07",
        source="LIVE_FIBONACCI",
    )

    assert seen["date_str"] == "2026-08-07"
    assert seen["store"] is store

    assert result["risk"] == {
        "tradingAllowed": False,
        "reason": "PAPER_DAILY_LOSS_LIMIT_REACHED",
        "availableForNewOrders": 9_950.0,
        "pendingReservedCash": 0.0,
        "dailyRealizedPnl": -50.0,
        "maxDailyLoss": 50.0,
        "remainingDailyLoss": 0.0,
        "simulationOnly": True,
        "brokerSubmitted": False,
    }


def test_dashboard_risk_failure_is_nonfatal(
    monkeypatch,
):
    bot = object.__new__(TradingBot)
    bot._webull_paper_portfolio_snapshot = (
        make_portfolio()
    )

    bot.webull_paper_lifecycle_tracker = (
        SimpleNamespace(store=object())
    )

    def fail(**kwargs):
        raise RuntimeError("risk unavailable")

    monkeypatch.setattr(
        bot_module,
        "load_webull_paper_risk_status",
        fail,
    )

    result = bot._dashboard_paper_portfolio(
        date_str="2026-08-07",
        source="LIVE_FIBONACCI",
    )

    assert result is not None
    assert result["risk"] is None
    assert result["simulationOnly"] is True
    assert result["brokerSubmitted"] is False
