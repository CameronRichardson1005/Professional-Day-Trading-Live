from datetime import date, datetime
from zoneinfo import ZoneInfo

from trading_bot.scanner_data_quality import (
    analyze_minute_session,
)


UTC = ZoneInfo("UTC")


def complete_session():
    start = datetime(
        2026,
        3,
        2,
        14,
        30,
        tzinfo=UTC,
    )

    return [
        {
            "t": (
                start
                .replace(
                    second=0,
                    microsecond=0,
                )
                .isoformat()
            ),
            "o": 10,
            "h": 10,
            "l": 10,
            "c": 10,
        }
        for start in (
            start
            + __import__(
                "datetime"
            ).timedelta(
                minutes=offset
            )
            for offset in range(390)
        )
    ]


def remove_timestamp(
    bars,
    timestamp,
):
    return [
        bar
        for bar in bars
        if (
            datetime.fromisoformat(
                str(
                    bar["t"]
                )
            )
            != timestamp
        )
    ]


def test_complete_session_is_clean():
    quality = analyze_minute_session(
        session=date(
            2026,
            3,
            2,
        ),
        bars=complete_session(),
    )

    assert (
        quality.observed_regular_minutes
        == 390
    )

    assert quality.missing_total == 0
    assert (
        quality.quick_flip_signal_clean
        is True
    )
    assert (
        quality.post_opening_outcome_clean
        is True
    )


def test_opening_gap_does_not_dirty_quick_flip_monitor():
    bars = remove_timestamp(
        complete_session(),
        datetime(
            2026,
            3,
            2,
            14,
            35,
            tzinfo=UTC,
        ),
    )

    quality = analyze_minute_session(
        session=date(
            2026,
            3,
            2,
        ),
        bars=bars,
    )

    assert (
        quality.missing_opening_minutes
        == 1
    )

    assert (
        quality.missing_quick_flip_minutes
        == 0
    )

    assert (
        quality.quick_flip_signal_clean
        is True
    )

    assert (
        quality.post_opening_outcome_clean
        is True
    )


def test_quick_flip_window_gap_marks_signal_partial():
    bars = remove_timestamp(
        complete_session(),
        datetime(
            2026,
            3,
            2,
            15,
            17,
            tzinfo=UTC,
        ),
    )

    quality = analyze_minute_session(
        session=date(
            2026,
            3,
            2,
        ),
        bars=bars,
    )

    assert (
        quality.missing_quick_flip_minutes
        == 1
    )

    assert (
        quality.quick_flip_signal_clean
        is False
    )

    assert (
        quality.post_opening_outcome_clean
        is False
    )


def test_afternoon_gap_keeps_signal_clean_but_outcome_partial():
    bars = remove_timestamp(
        complete_session(),
        datetime(
            2026,
            3,
            2,
            19,
            0,
            tzinfo=UTC,
        ),
    )

    quality = analyze_minute_session(
        session=date(
            2026,
            3,
            2,
        ),
        bars=bars,
    )

    assert (
        quality.missing_post_1100_minutes
        == 1
    )

    assert (
        quality.quick_flip_signal_clean
        is True
    )

    assert (
        quality.post_opening_outcome_clean
        is False
    )


def test_missing_after_fill_only_counts_later_gaps():
    bars = complete_session()

    bars = remove_timestamp(
        bars,
        datetime(
            2026,
            3,
            2,
            15,
            0,
            tzinfo=UTC,
        ),
    )

    bars = remove_timestamp(
        bars,
        datetime(
            2026,
            3,
            2,
            19,
            0,
            tzinfo=UTC,
        ),
    )

    quality = analyze_minute_session(
        session=date(
            2026,
            3,
            2,
        ),
        bars=bars,
    )

    missing = (
        quality.missing_at_or_after(
            datetime(
                2026,
                3,
                2,
                16,
                0,
                tzinfo=UTC,
            )
        )
    )

    assert len(missing) == 1

    assert missing[0] == datetime(
        2026,
        3,
        2,
        19,
        0,
        tzinfo=UTC,
    )
