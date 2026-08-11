import sys

import main as main_module


def run_main(monkeypatch, *arguments):
    monkeypatch.setattr(
        sys,
        "argv",
        ["main.py", "market-day", *arguments],
    )
    return main_module.main()


def test_market_day_accepts_normal_trading_day(
        monkeypatch,
):
    assert run_main(
        monkeypatch,
        "2026-07-28",
    ) == 0


def test_market_day_rejects_weekend(
        monkeypatch,
):
    assert run_main(
        monkeypatch,
        "2026-08-01",
    ) == 2


def test_market_day_rejects_market_holiday(
        monkeypatch,
):
    assert run_main(
        monkeypatch,
        "2026-12-25",
    ) == 2


def test_market_day_rejects_invalid_date(
        monkeypatch,
):
    assert run_main(
        monkeypatch,
        "not-a-date",
    ) == 1
