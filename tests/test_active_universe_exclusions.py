import trading_bot.config as config


def test_mara_and_lcid_are_excluded_from_active_candidate_universe():
    excluded = {
        "MARA",
        "LCID",
    }

    assert excluded.isdisjoint(
        set(config.CANDIDATE_TICKERS)
    )


def test_mara_and_lcid_are_excluded_from_runtime_tickers():
    if not hasattr(config, "TICKERS"):
        return

    excluded = {
        "MARA",
        "LCID",
    }

    assert excluded.isdisjoint(
        set(config.TICKERS)
    )
