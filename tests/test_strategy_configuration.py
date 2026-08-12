import trading_bot.config as config


def test_real_order_submission_is_disabled():
    assert config.REAL_ORDER_SUBMISSION_ENABLED is False


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




def test_manipulation_strategy_name():
    assert (
        config.MANIPULATION_STRATEGY_NAME
        == "MANIPULATION_OPENING_15M"
    )


def test_quick_flip_monitoring_configuration():
    assert config.QUICK_FLIP_MONITOR_START == "09:45"
    assert config.QUICK_FLIP_MONITOR_CUTOFF == "11:00"
    assert (
        config.QUICK_FLIP_MONITOR_INTERVAL_SECONDS
        == 60
    )
