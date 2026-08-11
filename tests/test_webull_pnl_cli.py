import sys
from types import SimpleNamespace

import main as main_module


def test_main_dispatches_webull_pnl(
    monkeypatch,
):
    calls = []

    class FakeBot:
        def write_webull_daily_pnl(
            self,
            date_str,
        ):
            calls.append(date_str)

            return {
                "summary": SimpleNamespace(
                    date=date_str,
                    closed_trades=2,
                    winning_trades=2,
                    losing_trades=0,
                    realized_pnl=12.0,
                )
            }

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
        sys,
        "argv",
        [
            "main.py",
            "webull-pnl",
            "2026-08-11",
        ],
    )

    assert main_module.main() == 0
    assert calls == [
        "2026-08-11",
    ]


def test_webull_pnl_requires_date(
    monkeypatch,
):
    class FakeBot:
        pass

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
        sys,
        "argv",
        [
            "main.py",
            "webull-pnl",
        ],
    )

    assert main_module.main() == 2
