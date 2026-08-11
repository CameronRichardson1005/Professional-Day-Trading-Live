from types import SimpleNamespace

from trading_bot.sheets_client import SheetsClient


def group(
    *,
    key,
    win_rate_pct=50.0,
    realized_pnl=3.0,
):
    return SimpleNamespace(
        key=key,
        approved_orders=2,
        entered_trades=2,
        closed_trades=2,
        no_entry=0,
        wins=1,
        losses=1,
        breakeven=0,
        target_exits=1,
        stop_exits=1,
        time_exits=0,
        win_rate_pct=win_rate_pct,
        realized_pnl=realized_pnl,
        average_pnl_per_trade=1.5,
        average_return_pct=1.2,
        expectancy_per_trade=1.5,
        average_mfe_pct=3.5,
        average_mae_pct=-1.5,
        sample_label="VERY SMALL SAMPLE",
    )


def report():
    return SimpleNamespace(
        by_symbol=(group(key="OPEN"),),
        by_entry_time=(
            group(key="10:00-10:14 ET"),
        ),
        by_reward_risk=(
            group(key="2.00-2.49"),
        ),
        by_impulse_atr=(
            group(key="0.75-0.99 ATR"),
        ),
        by_pullback_volume=(
            group(key="0.50-0.74"),
        ),
        by_confirmation_time=(
            group(key="10:00-10:14 ET"),
        ),
    )


def test_write_paper_analytics_uses_dedicated_sheet():
    client = object.__new__(SheetsClient)

    worksheet = object()
    seen = {}

    def get_or_create_worksheet(
        *,
        title,
        rows,
        cols,
    ):
        seen["title"] = title
        seen["rows"] = rows
        seen["cols"] = cols
        return worksheet

    client.get_or_create_worksheet = (
        get_or_create_worksheet
    )
    client._replace_date_rows = (
        lambda **kwargs: seen.update(kwargs)
    )

    client.write_paper_analytics(
        date_str="2026-08-08",
        report=report(),
    )

    assert seen["title"] == "Paper Analytics"
    assert seen["sheet_name"] == "Paper Analytics"
    assert seen["date_str"] == "2026-08-08"
    assert seen["last_column"] == "W"
    assert len(seen["columns"]) == 23

    rows = seen["replacement_rows"]

    assert len(rows) == 6
    assert {
        row[1]
        for row in rows
    } == {
        "SYMBOL",
        "ENTRY TIME",
        "REWARD/RISK",
        "IMPULSE ATR",
        "PULLBACK VOLUME",
        "CONFIRMATION TIME",
    }

    symbol = next(
        row
        for row in rows
        if row[1] == "SYMBOL"
    )

    assert symbol[0] == "2026-08-08"
    assert symbol[2] == "OPEN"
    assert symbol[5] == 2
    assert symbol[7] == 1
    assert symbol[8] == 1
    assert symbol[13] == 50.0
    assert symbol[14] == 3.0
    assert symbol[20] == "VERY SMALL SAMPLE"
    assert symbol[21] == "YES"
    assert symbol[22] == "NO"


def test_write_paper_analytics_blanks_missing_metrics():
    client = object.__new__(SheetsClient)

    seen = {}

    client.get_or_create_worksheet = (
        lambda **kwargs: object()
    )
    client._replace_date_rows = (
        lambda **kwargs: seen.update(kwargs)
    )

    empty_group = group(
        key="UNAVAILABLE",
        win_rate_pct=None,
        realized_pnl=0.0,
    )

    empty_group = SimpleNamespace(
        **{
            **empty_group.__dict__,
            "average_pnl_per_trade": None,
            "average_return_pct": None,
            "expectancy_per_trade": None,
            "average_mfe_pct": None,
            "average_mae_pct": None,
        }
    )

    empty_report = SimpleNamespace(
        by_symbol=(empty_group,),
        by_entry_time=(),
        by_reward_risk=(),
        by_impulse_atr=(),
        by_pullback_volume=(),
        by_confirmation_time=(),
    )

    client.write_paper_analytics(
        date_str="2026-08-08",
        report=empty_report,
    )

    row = seen["replacement_rows"][0]

    assert row[13] == ""
    assert row[14] == 0.0
    assert row[15] == ""
    assert row[16] == ""
    assert row[17] == ""
    assert row[18] == ""
    assert row[19] == ""



def test_finalise_strategy_workbook_writes_paper_evaluation(
    monkeypatch,
):
    from trading_bot.bot import TradingBot

    bot = object.__new__(TradingBot)

    seen = {}

    bot.sheets = SimpleNamespace(
        write_paper_performance=lambda **kwargs: None,
        write_paper_analytics=lambda **kwargs: None,
        write_paper_evaluation=(
            lambda **kwargs: seen.update(kwargs)
        ),
        write_paper_portfolio=lambda **kwargs: None,
        finalise_daily_workbook=lambda **kwargs: None,
    )

    monkeypatch.setattr(
        "trading_bot.bot.load_webull_paper_daily_performance",
        lambda **kwargs: SimpleNamespace(
            date=kwargs["date_str"],
        ),
    )

    monkeypatch.setattr(
        "trading_bot.bot.load_webull_paper_analytics",
        lambda: SimpleNamespace(),
    )

    expected = SimpleNamespace(
        evidence_status="NO DATA",
    )

    monkeypatch.setattr(
        "trading_bot.bot.load_fibonacci_paper_evaluation",
        lambda: expected,
    )

    monkeypatch.setattr(
        "trading_bot.bot.load_webull_paper_portfolio",
        lambda **kwargs: SimpleNamespace(),
    )

    monkeypatch.setattr(
        "trading_bot.bot.load_webull_paper_risk_status",
        lambda **kwargs: SimpleNamespace(),
    )

    bot.finalise_strategy_workbook(
        date_str="2026-08-09",
    )

    assert seen["date_str"] == "2026-08-09"
    assert seen["evaluation"] is expected
