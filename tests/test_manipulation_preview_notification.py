from unittest.mock import Mock

import trading_bot.bot as bot_module
from trading_bot.bot import TradingBot


def test_manipulation_preview_notification_runs_for_ready_preview(
    monkeypatch,
):
    run = Mock()

    monkeypatch.setattr(
        bot_module.subprocess,
        "run",
        run,
    )

    preview = {
        "status": "PREVIEW READY",
        "symbol": "OPEN",
        "quantity": 25,
        "limitBuy": 4.1234,
        "target": 4.4567,
        "tradingStopLoss": 3.9876,
    }

    TradingBot._notify_manipulation_preview(
        preview
    )

    run.assert_called_once()

    args = run.call_args.args[0]

    assert args[0] == "osascript"
    assert "Manipulation Webull Preview Ready" in args[2]
    assert "OPEN" in args[2]
    assert "25 shares" in args[2]
    assert "Entry $4.1234" in args[2]
    assert "Target $4.4567" in args[2]
    assert "Trading Stop $3.9876" in args[2]


def test_manipulation_notification_skips_failed_preview(
    monkeypatch,
):
    run = Mock()

    monkeypatch.setattr(
        bot_module.subprocess,
        "run",
        run,
    )

    TradingBot._notify_manipulation_preview(
        {
            "status": "PREVIEW FAILED",
            "symbol": "OPEN",
        }
    )

    run.assert_not_called()


def test_notification_failure_does_not_raise(
    monkeypatch,
):
    def fail(*args, **kwargs):
        raise RuntimeError(
            "controlled notification failure"
        )

    monkeypatch.setattr(
        bot_module.subprocess,
        "run",
        fail,
    )

    TradingBot._notify_manipulation_preview(
        {
            "status": "PREVIEW READY",
            "symbol": "OPEN",
            "quantity": 25,
            "limitBuy": 4.1234,
            "target": 4.4567,
            "tradingStopLoss": 3.9876,
        }
    )
