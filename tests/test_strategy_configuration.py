import importlib

import pytest

import trading_bot.config as config


def test_supported_strategies_preserve_manipulation_and_fibonacci():
    assert "MANIPULATION_OPENING_15M" in (
        config.SUPPORTED_STRATEGIES
    )
    assert "FIBONACCI_61_8" in config.SUPPORTED_STRATEGIES


def test_active_strategy_is_supported():
    assert config.ACTIVE_STRATEGY in config.SUPPORTED_STRATEGIES


def test_real_order_submission_is_disabled():
    assert config.REAL_ORDER_SUBMISSION_ENABLED is False


def test_invalid_active_strategy_is_rejected(monkeypatch):
    monkeypatch.setenv(
        "ACTIVE_STRATEGY",
        "UNSUPPORTED_STRATEGY",
    )

    with pytest.raises(
        RuntimeError,
        match="ACTIVE_STRATEGY must be one of",
    ):
        importlib.reload(config)

    monkeypatch.setenv(
        "ACTIVE_STRATEGY",
        "MANIPULATION_OPENING_15M",
    )
    importlib.reload(config)


def test_dashboard_uses_cloudflare_only():
    assert (
        config.DASHBOARD_URL
        == (
            "https://cameron-trading-desk."
            "cameron-richardson.workers.dev"
            "/api/sessions/latest"
        )
    )
    assert "chatgpt.site" not in config.DASHBOARD_URL.lower()


def test_fibonacci_monitoring_configuration():
    assert config.FIBONACCI_MONITOR_START == "09:45"
    assert config.FIBONACCI_MONITOR_CUTOFF == "11:00"
    assert config.FIBONACCI_MONITOR_INTERVAL_SECONDS == 60
