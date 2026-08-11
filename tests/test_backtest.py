import csv

from datetime import date

import main as main_module

from trading_bot.backtest import (
    BacktestRecord,
    BacktestReport,
    ReplaySession,
    market_regimes_by_date,
    weekday_dates,
)
from trading_bot.bot import TradingBot
from trading_bot.models import Stock
from trading_bot.replay import ReplaySummary


def record(
        *,
        date_str: str,
        symbol: str,
        outcome: str,
        return_pct: float | None,
        bars_processed: int = 15,
        missing_bars: int = 0,
        signal: str = "INVEST",
        atr_available: bool = True,
) -> BacktestRecord:
    return BacktestRecord(
        date=date_str,
        symbol=symbol,
        data_feed="iex",
        bars_processed=bars_processed,
        missing_bars=missing_bars,
        missing_timestamps="",
        missing_bar_classification="COMPLETE",
        atr_available=atr_available,
        atr_status=(
            "AVAILABLE"
            if atr_available
            else "INSUFFICIENT_HISTORY"
        ),
        atr_daily_bars=30 if atr_available else 0,
        green_minutes=6,
        red_minutes=9,
        new_highs=2,
        new_lows=4,
        candle_range=0.4,
        atr=1.0,
        candle_atr_ratio=0.4,
        is_manipulation=True,
        is_red=True,
        signal=signal,
        outcome=outcome,
        entry_price=10.0,
        exit_price=(
            10.0 * (1 + return_pct / 100)
            if return_pct is not None
            else None
        ),
        stop_loss=9.1,
        trading_stop_loss=9.0,
        pnl_per_share=(
            return_pct / 10
            if return_pct is not None
            else None
        ),
        return_pct=return_pct,
        gross_pnl_per_share=(
            return_pct / 10
            if return_pct is not None
            else None
        ),
        costs_per_share=0.0,
        exit_reason="",
        spy_regime="BULL",
        qqq_regime="BEAR",
        detail="test",
    )


def test_backtest_metrics_cover_outcomes_and_data_quality():
    report = BacktestReport(
        start_date="2026-07-20",
        end_date="2026-07-24",
    )
    report.records = [
        record(
            date_str="2026-07-20",
            symbol="AAA",
            outcome="WIN",
            return_pct=4.0,
        ),
        record(
            date_str="2026-07-21",
            symbol="AAA",
            outcome="LOSS",
            return_pct=-2.0,
        ),
        record(
            date_str="2026-07-22",
            symbol="AAA",
            outcome="STILL OPEN",
            return_pct=None,
        ),
        record(
            date_str="2026-07-23",
            symbol="BBB",
            outcome="NO ENTRY",
            return_pct=None,
        ),
        record(
            date_str="2026-07-24",
            symbol="BBB",
            outcome="",
            return_pct=None,
            bars_processed=12,
            missing_bars=3,
            signal="NO INVEST",
            atr_available=False,
        ),
        record(
            date_str="2026-07-24",
            symbol="CCC",
            outcome="",
            return_pct=None,
            signal="NO INVEST",
            atr_available=False,
        ),
    ]

    metrics = report.overall_metrics()

    assert metrics.invest_signals == 4
    assert metrics.wins == 1
    assert metrics.losses == 1
    assert metrics.unresolved == 1
    assert metrics.no_entry == 1
    assert metrics.win_rate_pct == 50.0
    assert metrics.average_return_pct == 1.0
    assert metrics.total_return_pct == 2.0
    assert metrics.profit_factor == 2.0
    assert metrics.max_drawdown_pct_points == 2.0
    assert metrics.missing_bars == 3
    assert metrics.incomplete_ticker_days == 1
    assert metrics.atr_unavailable_ticker_days == 1


def test_backtest_writes_detail_and_summary_csv(tmp_path):
    report = BacktestReport(
        start_date="2026-07-23",
        end_date="2026-07-23",
    )
    report.records = [
        record(
            date_str="2026-07-23",
            symbol="TEST",
            outcome="WIN",
            return_pct=4.0,
        )
    ]

    (
        detail_path,
        summary_path,
        missing_path,
        robustness_path,
        atr_path,
        split_path,
    ) = report.write_csv(tmp_path)

    with detail_path.open(
        newline="",
        encoding="utf-8",
    ) as detail_file:
        detail_rows = list(
            csv.DictReader(detail_file)
        )

    with summary_path.open(
        newline="",
        encoding="utf-8",
    ) as summary_file:
        summary_rows = list(
            csv.DictReader(summary_file)
        )

    assert detail_rows[0]["symbol"] == "TEST"
    assert detail_rows[0]["outcome"] == "WIN"
    assert summary_rows[0]["scope"] == "OVERALL"
    assert summary_rows[0]["wins"] == "1"
    assert summary_rows[1]["scope"] == "TICKER"
    assert summary_rows[1]["symbol"] == "TEST"
    assert missing_path.exists()
    assert robustness_path.exists()
    assert atr_path.exists()
    assert split_path.exists()


def test_backtest_writes_exact_missing_bar_diagnostic(
        tmp_path,
):
    report = BacktestReport(
        start_date="2026-07-23",
        end_date="2026-07-23",
        data_feed="iex",
    )
    missing = record(
        date_str="2026-07-23",
        symbol="TEST",
        outcome="",
        return_pct=None,
        bars_processed=14,
        missing_bars=1,
        signal="NO INVEST",
    )
    report.records = [
        BacktestRecord(
            **{
                **missing.__dict__,
                "data_feed": "iex",
                "missing_timestamps": (
                    "2026-07-23 09:44 ET"
                ),
                "missing_bar_classification": (
                    "NO_VALID_IEX_BAR_RETURNED"
                ),
            }
        )
    ]

    _, _, missing_path, _, _, _ = report.write_csv(
        tmp_path
    )
    with missing_path.open(
        newline="",
        encoding="utf-8",
    ) as missing_file:
        rows = list(csv.DictReader(missing_file))

    assert rows[0]["missing_timestamp"] == (
        "2026-07-23 09:44 ET"
    )
    assert rows[0]["classification"] == (
        "NO_VALID_IEX_BAR_RETURNED"
    )


def test_robustness_report_compares_filters():
    report = BacktestReport(
        start_date="2026-07-20",
        end_date="2026-07-24",
    )
    report.records = [
        record(
            date_str="2026-07-20",
            symbol="AAA",
            outcome="WIN",
            return_pct=2.0,
        ),
        record(
            date_str="2026-07-21",
            symbol="BBB",
            outcome="LOSS",
            return_pct=-1.0,
        ),
    ]

    rows = {
        row["variant"]: row
        for row in report.robustness_comparisons()
    }

    assert rows["BASELINE"]["invest_signals"] == 2
    assert rows["EXCLUDE_AAA"]["invest_signals"] == 1
    assert (
        rows["MIN_CANDLE_ATR_RATIO_0.40"]
        ["invest_signals"]
        == 2
    )


def test_weekday_dates_excludes_weekend():
    assert weekday_dates(
        date(2026, 7, 24),
        date(2026, 7, 27),
    ) == [
        date(2026, 7, 24),
        date(2026, 7, 27),
    ]


def test_main_dispatches_backtest_mode(
        monkeypatch,
):
    events = []

    class FakeBot:
        def run_backtest(
                self,
                start_date,
                end_date,
                output_directory,
                data_feed,
                slippage_bps,
                commission_per_share,
                train_fraction,
        ):
            events.append(
                (
                    start_date,
                    end_date,
                    output_directory,
                    data_feed,
                    slippage_bps,
                    commission_per_share,
                    train_fraction,
                )
            )

    monkeypatch.setattr(
        main_module,
        "TradingBot",
        FakeBot,
    )
    monkeypatch.setattr(
        main_module,
        "setup_logging",
        lambda: "logs/test.log",
    )
    monkeypatch.setattr(
        main_module.sys,
        "argv",
        [
            "main.py",
            "backtest",
            "2026-07-13",
            "2026-07-24",
            "--output",
            "custom-reports",
            "--feed",
            "iex",
        ],
    )

    assert main_module.main() == 0
    assert events == [
        (
            "2026-07-13",
            "2026-07-24",
            "custom-reports",
            "iex",
            0.0,
            0.0,
            0.70,
        ),
    ]


def test_range_backtest_isolates_failed_date(
        tmp_path,
):
    bot = object.__new__(TradingBot)
    calls = []

    def fake_run_replay(
            date_str,
            speed,
            publish_dashboard,
            data_feed,
            slippage_bps,
            commission_per_share,
    ):
        calls.append(
            (
                date_str,
                speed,
                publish_dashboard,
                data_feed,
                slippage_bps,
                commission_per_share,
            )
        )

        if date_str == "2026-07-21":
            raise RuntimeError("temporary API error")

        stock = Stock(symbol="TEST")
        stock.signal = "INVEST"
        stock.outcome = {
            "status": "WIN",
            "returnPct": 2.0,
        }

        return ReplaySession(
            date=date_str,
            stocks={"TEST": stock},
            summary=ReplaySummary(
                processed_bars={"TEST": 15},
                missing_bars={"TEST": 0},
            ),
        )

    bot.run_replay = fake_run_replay

    report = TradingBot.run_backtest(
        bot,
        start_date="2026-07-20",
        end_date="2026-07-22",
        output_directory=tmp_path,
    )

    assert len(report.records) == 2
    assert report.failed_sessions == [
        (
            "2026-07-21",
            "temporary API error",
        )
    ]
    assert calls == [
        ("2026-07-20", 0, False, "iex", 0.0, 0.0),
        ("2026-07-21", 0, False, "iex", 0.0, 0.0),
        ("2026-07-22", 0, False, "iex", 0.0, 0.0),
    ]


def test_weekday_dates_excludes_nyse_holidays():
    assert weekday_dates(
        date(2026, 4, 2),
        date(2026, 4, 6),
    ) == [
        date(2026, 4, 2),
        date(2026, 4, 6),
    ]


def test_market_regime_uses_only_prior_sessions():
    bars = {
        "SPY": [
            {
                "t": f"2026-01-{day:02d}T05:00:00Z",
                "c": float(day),
            }
            for day in range(1, 22)
        ],
        "QQQ": [],
    }
    regimes = market_regimes_by_date(
        bars,
        [date(2026, 1, 22)],
    )

    assert regimes["2026-01-22"]["SPY"] == "BULL"
    assert regimes["2026-01-22"]["QQQ"] == "UNAVAILABLE"


def test_chronological_split_never_mixes_dates():
    report = BacktestReport(
        start_date="2026-07-20",
        end_date="2026-07-23",
        train_fraction=0.5,
    )
    report.records = [
        record(
            date_str=f"2026-07-{day}",
            symbol="AAA",
            outcome="WIN",
            return_pct=1.0,
        )
        for day in range(20, 24)
    ]

    rows = report.chronological_split_rows()
    train = next(
        row
        for row in rows
        if row["split"] == "TRAIN"
        and row["variant"] == "BASELINE"
    )
    test = next(
        row
        for row in rows
        if row["split"] == "TEST"
        and row["variant"] == "BASELINE"
    )

    assert train["split_end"] < test["split_start"]
