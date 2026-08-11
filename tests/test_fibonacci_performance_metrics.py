from trading_bot.bot import TradingBot


def make_bot():
    return object.__new__(TradingBot)


def test_performance_metrics_can_be_recorded():
    bot = make_bot()

    bot._set_fibonacci_performance_metric(
        "intraday_fetch_seconds",
        0.25,
    )

    assert (
        bot._fibonacci_performance_metrics[
            "intraday_fetch_seconds"
        ]
        == 0.25
    )


def test_performance_output_reports_cached_data(
        capsys,
):
    bot = make_bot()

    bot._fibonacci_performance_metrics = {
        "static_data_cached": True,
        "intraday_fetch_cached": True,
        "strategy_compute_seconds": 0.012,
        "strategy_evaluation_seconds": 0.034,
    }

    bot._print_fibonacci_cycle_performance(
        total_seconds=0.100,
        sheets_preview_seconds=0.020,
        dashboard_seconds=0.010,
    )

    output = capsys.readouterr().out

    assert "Static session data: cached" in output
    assert "Intraday Alpaca fetch: cached" in output
    assert "Fibonacci calculation: 0.012s" in output
    assert "Strategy evaluation total: 0.034s" in output
    assert "Sheets + Webull preview: 0.020s" in output
    assert "Dashboard upload: 0.010s" in output
    assert "Total cycle: 0.100s" in output
