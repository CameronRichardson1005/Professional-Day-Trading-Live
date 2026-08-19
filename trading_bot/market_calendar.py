from __future__ import annotations

from datetime import date, timedelta


def nyse_trading_dates(
        start_date: date,
        end_date: date,
) -> list[date]:
    if end_date < start_date:
        raise ValueError(
            "Backtest end date cannot be before start date."
        )

    holidays = set()
    for year in range(
        start_date.year,
        end_date.year + 2,
    ):
        holidays.update(nyse_holidays(year))

    result = []
    current = start_date

    while current <= end_date:
        if (
            current.weekday() < 5
            and current not in holidays
        ):
            result.append(current)
        current += timedelta(days=1)

    return result


def nyse_holidays(year: int) -> set[date]:
    holidays = {
        _observed(date(year, 1, 1)),
        _nth_weekday(year, 1, 0, 3),
        _nth_weekday(year, 2, 0, 3),
        _good_friday(year),
        _last_weekday(year, 5, 0),
        _observed(date(year, 7, 4)),
        _nth_weekday(year, 9, 0, 1),
        _nth_weekday(year, 11, 3, 4),
        _observed(date(year, 12, 25)),
    }

    if year >= 2022:
        holidays.add(
            _observed(date(year, 6, 19))
        )

    holidays.update(
        _nyse_special_closures(year)
    )

    return holidays


def _nyse_special_closures(
        year: int,
) -> set[date]:
    """
    One-off full-day NYSE closures that are not part of
    the standard recurring holiday calendar.
    """
    closures = {
        2025: {
            date(2025, 1, 9),
        },
    }

    return set(
        closures.get(
            year,
            set(),
        )
    )


def _observed(value: date) -> date:
    if value.weekday() == 5:
        return value - timedelta(days=1)
    if value.weekday() == 6:
        return value + timedelta(days=1)
    return value


def _nth_weekday(
        year: int,
        month: int,
        weekday: int,
        occurrence: int,
) -> date:
    current = date(year, month, 1)
    offset = (weekday - current.weekday()) % 7
    return current + timedelta(
        days=offset + 7 * (occurrence - 1)
    )


def _last_weekday(
        year: int,
        month: int,
        weekday: int,
) -> date:
    if month == 12:
        current = date(year + 1, 1, 1)
    else:
        current = date(year, month + 1, 1)

    current -= timedelta(days=1)
    offset = (current.weekday() - weekday) % 7
    return current - timedelta(days=offset)


def _good_friday(year: int) -> date:
    # Anonymous Gregorian computus for Easter Sunday.
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    ell = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * ell) // 451
    month = (h + ell - 7 * m + 114) // 31
    day = ((h + ell - 7 * m + 114) % 31) + 1
    easter = date(year, month, day)
    return easter - timedelta(days=2)
