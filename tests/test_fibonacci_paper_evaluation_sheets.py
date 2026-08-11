from types import SimpleNamespace

from trading_bot.sheets_client import SheetsClient


def finding(
    *,
    dimension="SYMBOL",
    key="OPEN",
    closed_trades=5,
    win_rate_pct=60.0,
    expectancy_per_trade=2.5,
    average_return_pct=1.4,
    realized_pnl=12.5,
):
    return SimpleNamespace(
        dimension=dimension,
        key=key,
        closed_trades=closed_trades,
        win_rate_pct=win_rate_pct,
        expectancy_per_trade=expectancy_per_trade,
        average_return_pct=average_return_pct,
        realized_pnl=realized_pnl,
        sample_label="SMALL SAMPLE",
    )


def evaluation(
    *,
    strongest=None,
    weakest=None,
):
    return SimpleNamespace(
        evidence_status="EARLY",
        evidence_message=(
            "Fewer than 20 closed trades are available."
        ),
        total_orders=14,
        closed_trades=10,
        strongest_cohort=strongest,
        weakest_cohort=weakest,
        parameter_changes_allowed=False,
    )


def test_write_paper_evaluation_uses_dedicated_sheet():
    client = object.__new__(SheetsClient)

    worksheet = object()
    seen = {}

    client.get_or_create_worksheet = (
        lambda **kwargs: (
            seen.update(kwargs),
            worksheet,
        )[1]
    )
    client._replace_date_rows = (
        lambda **kwargs: seen.update(kwargs)
    )

    client.write_paper_evaluation(
        date_str="2026-08-09",
        evaluation=evaluation(
            strongest=finding(),
            weakest=finding(
                dimension="REWARD/RISK",
                key="<1.50",
                win_rate_pct=20.0,
                expectancy_per_trade=-1.5,
                average_return_pct=-0.8,
                realized_pnl=-7.5,
            ),
        ),
    )

    assert seen["title"] == "Paper Evaluation"
    assert seen["sheet_name"] == "Paper Evaluation"
    assert seen["date_str"] == "2026-08-09"
    assert seen["last_column"] == "X"
    assert len(seen["columns"]) == 24

    row = seen["replacement_rows"][0]

    assert row[0] == "2026-08-09"
    assert row[1] == "EARLY"
    assert row[3] == 14
    assert row[4] == 10

    assert row[5] == "SYMBOL"
    assert row[6] == "OPEN"
    assert row[7] == 5
    assert row[8] == 60.0
    assert row[9] == 2.5
    assert row[10] == 1.4
    assert row[11] == 12.5
    assert row[12] == "SMALL SAMPLE"

    assert row[13] == "REWARD/RISK"
    assert row[14] == "<1.50"
    assert row[17] == -1.5
    assert row[19] == -7.5

    assert row[21] == "NO"
    assert row[22] == "YES"
    assert row[23] == "NO"


def test_write_paper_evaluation_blanks_unranked_cohorts():
    client = object.__new__(SheetsClient)

    seen = {}

    client.get_or_create_worksheet = (
        lambda **kwargs: object()
    )
    client._replace_date_rows = (
        lambda **kwargs: seen.update(kwargs)
    )

    client.write_paper_evaluation(
        date_str="2026-08-09",
        evaluation=evaluation(),
    )

    row = seen["replacement_rows"][0]

    assert row[5:13] == [""] * 8
    assert row[13:21] == [""] * 8
    assert row[21] == "NO"
    assert row[22] == "YES"
    assert row[23] == "NO"
