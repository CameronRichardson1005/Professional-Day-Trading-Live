from types import SimpleNamespace

import trading_bot.bot as bot_module

from trading_bot.bot import TradingBot
from trading_bot.dashboard_exporter import (
    DashboardExporter,
)


def finding(
    *,
    dimension="SYMBOL",
    key="OPEN",
    expectancy=2.5,
):
    return SimpleNamespace(
        dimension=dimension,
        key=key,
        closed_trades=6,
        win_rate_pct=66.666667,
        expectancy_per_trade=expectancy,
        average_return_pct=1.4,
        realized_pnl=expectancy * 6,
        sample_label="SMALL SAMPLE",
    )


def evaluation():
    return SimpleNamespace(
        total_orders=15,
        closed_trades=12,
        evidence_status="EARLY",
        evidence_message=(
            "Fewer than 20 closed trades are available."
        ),
        parameter_changes_allowed=False,
        strongest_cohort=finding(
            key="OPEN",
            expectancy=2.5,
        ),
        weakest_cohort=finding(
            dimension="REWARD/RISK",
            key="<1.50",
            expectancy=-1.0,
        ),
    )


def test_dashboard_evaluation_final_session_only(
    monkeypatch,
):
    bot = object.__new__(TradingBot)

    monkeypatch.setattr(
        bot_module,
        "load_fibonacci_paper_evaluation",
        lambda: evaluation(),
    )

    assert (
        bot._dashboard_paper_evaluation(
            source="LIVE_FIBONACCI"
        )
        is None
    )

    result = bot._dashboard_paper_evaluation(
        source="LIVE_FIBONACCI_FINAL"
    )

    assert result is not None
    assert result["totalOrders"] == 15
    assert result["closedTrades"] == 12
    assert result["evidenceStatus"] == "EARLY"

    assert (
        result["parameterChangesAllowed"]
        is False
    )

    assert (
        result["strongestCohort"]["key"]
        == "OPEN"
    )
    assert (
        result["weakestCohort"]["dimension"]
        == "REWARD/RISK"
    )

    assert result["simulationOnly"] is True
    assert result["brokerSubmitted"] is False


def test_dashboard_evaluation_supports_no_rankings(
    monkeypatch,
):
    bot = object.__new__(TradingBot)

    empty = evaluation()
    empty = SimpleNamespace(
        **{
            **empty.__dict__,
            "closed_trades": 0,
            "evidence_status": "NO DATA",
            "strongest_cohort": None,
            "weakest_cohort": None,
        }
    )

    monkeypatch.setattr(
        bot_module,
        "load_fibonacci_paper_evaluation",
        lambda: empty,
    )

    result = bot._dashboard_paper_evaluation(
        source="LIVE_FIBONACCI_FINAL"
    )

    assert result is not None
    assert result["evidenceStatus"] == "NO DATA"
    assert result["strongestCohort"] is None
    assert result["weakestCohort"] is None


def test_dashboard_evaluation_failure_is_nonfatal(
    monkeypatch,
):
    bot = object.__new__(TradingBot)

    def fail():
        raise RuntimeError("ledger unavailable")

    monkeypatch.setattr(
        bot_module,
        "load_fibonacci_paper_evaluation",
        fail,
    )

    result = bot._dashboard_paper_evaluation(
        source="LIVE_FIBONACCI_FINAL"
    )

    assert result is None


def test_exporter_includes_paper_evaluation():
    evaluation_payload = {
        "totalOrders": 0,
        "closedTrades": 0,
        "evidenceStatus": "NO DATA",
        "parameterChangesAllowed": False,
        "strongestCohort": None,
        "weakestCohort": None,
        "simulationOnly": True,
        "brokerSubmitted": False,
    }

    payload = DashboardExporter.build_payload(
        date_str="2026-08-09",
        source="LIVE_FIBONACCI_FINAL",
        stocks={},
        processed_bars={},
        data_feed="iex",
        paper_evaluation=evaluation_payload,
    )

    assert (
        payload["paperEvaluation"]
        == evaluation_payload
    )


def test_exporter_omits_paper_evaluation_when_missing():
    payload = DashboardExporter.build_payload(
        date_str="2026-08-09",
        source="LIVE_FIBONACCI_FINAL",
        stocks={},
        processed_bars={},
        data_feed="iex",
    )

    assert "paperEvaluation" not in payload
