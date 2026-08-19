from datetime import date

from trading_bot.market_calendar import (
    nyse_trading_dates,
)


def test_january_9_2025_is_not_a_trading_session():
    sessions = nyse_trading_dates(
        date(2025, 1, 8),
        date(2025, 1, 10),
    )

    assert sessions == [
        date(2025, 1, 8),
        date(2025, 1, 10),
    ]


def test_corrected_research_window_has_500_sessions():
    sessions = nyse_trading_dates(
        date(2024, 8, 16),
        date(2026, 8, 14),
    )

    assert len(sessions) == 500
    assert sessions[0] == date(2024, 8, 16)
    assert sessions[-1] == date(2026, 8, 14)
    assert date(2025, 1, 9) not in sessions
