from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo


EASTERN = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")


def _normalize_timestamp(
    value: object,
) -> datetime:
    text = str(value).strip()

    if text.endswith("Z"):
        text = (
            text[:-1]
            + "+00:00"
        )

    timestamp = datetime.fromisoformat(
        text
    )

    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(
            tzinfo=UTC
        )

    return (
        timestamp
        .astimezone(UTC)
        .replace(
            second=0,
            microsecond=0,
        )
    )


def expected_regular_session_minutes(
    session: date,
) -> tuple[datetime, ...]:
    start = datetime.combine(
        session,
        time(
            hour=9,
            minute=30,
        ),
        tzinfo=EASTERN,
    )

    return tuple(
        (
            start
            + timedelta(
                minutes=offset
            )
        ).astimezone(UTC)
        for offset in range(390)
    )


@dataclass(frozen=True)
class SessionMinuteQuality:
    date_str: str
    observed_bars: int
    observed_regular_minutes: int
    missing_regular_minutes: tuple[
        datetime,
        ...,
    ]
    duplicate_regular_minutes: int

    @property
    def missing_total(
        self,
    ) -> int:
        return len(
            self.missing_regular_minutes
        )

    @staticmethod
    def _minute_of_day(
        timestamp: datetime,
    ) -> int:
        local = timestamp.astimezone(
            EASTERN
        )

        return (
            local.hour * 60
            + local.minute
        )

    @property
    def missing_opening_minutes(
        self,
    ) -> int:
        return sum(
            1
            for timestamp
            in self.missing_regular_minutes
            if (
                570
                <= self._minute_of_day(
                    timestamp
                )
                < 585
            )
        )

    @property
    def missing_quick_flip_minutes(
        self,
    ) -> int:
        return sum(
            1
            for timestamp
            in self.missing_regular_minutes
            if (
                585
                <= self._minute_of_day(
                    timestamp
                )
                < 660
            )
        )

    @property
    def missing_post_1100_minutes(
        self,
    ) -> int:
        return sum(
            1
            for timestamp
            in self.missing_regular_minutes
            if (
                660
                <= self._minute_of_day(
                    timestamp
                )
                < 960
            )
        )

    @property
    def minute_completeness(
        self,
    ) -> float:
        return (
            self.observed_regular_minutes
            / 390.0
        )

    @property
    def opening_minute_cache_complete(
        self,
    ) -> bool:
        """
        Diagnostic only.

        Neither production strategy reconstructs its opening
        15-minute candle from this minute cache.
        """
        return (
            self.missing_opening_minutes
            == 0
        )

    @property
    def quick_flip_signal_clean(
        self,
    ) -> bool:
        """
        Quick Flip's reversal monitor uses 09:45-11:00 minute
        history, so that window must contain every minute for
        the strict signal sample.

        Its opening 15-minute candle is native Webull data and
        is therefore intentionally excluded from this test.
        """
        return (
            self.missing_quick_flip_minutes
            == 0
        )

    @property
    def post_opening_outcome_clean(
        self,
    ) -> bool:
        """
        Conservative strict flag for realized outcomes beginning
        at or after 09:45 ET.
        """
        return (
            self.missing_quick_flip_minutes
            == 0
            and
            self.missing_post_1100_minutes
            == 0
        )

    def missing_at_or_after(
        self,
        timestamp: datetime,
    ) -> tuple[datetime, ...]:
        """
        Used after an actual historical fill time is known.

        This lets the outcome runner distinguish an irrelevant
        missing minute before a trade from a missing minute after
        the trade became active.
        """
        if timestamp.tzinfo is None:
            timestamp = (
                timestamp.replace(
                    tzinfo=EASTERN
                )
            )

        normalized = (
            timestamp
            .astimezone(UTC)
            .replace(
                second=0,
                microsecond=0,
            )
        )

        return tuple(
            minute
            for minute
            in self.missing_regular_minutes
            if minute >= normalized
        )


def analyze_minute_session(
    *,
    session: date,
    bars: list[dict],
) -> SessionMinuteQuality:
    expected = set(
        expected_regular_session_minutes(
            session
        )
    )

    observed = []

    for bar in bars:
        if (
            not isinstance(
                bar,
                dict,
            )
            or "t" not in bar
        ):
            continue

        try:
            timestamp = (
                _normalize_timestamp(
                    bar["t"]
                )
            )
        except (
            TypeError,
            ValueError,
        ):
            continue

        if timestamp in expected:
            observed.append(
                timestamp
            )

    unique_observed = set(
        observed
    )

    missing = tuple(
        sorted(
            expected
            - unique_observed
        )
    )

    return SessionMinuteQuality(
        date_str=session.isoformat(),
        observed_bars=len(bars),
        observed_regular_minutes=len(
            unique_observed
        ),
        missing_regular_minutes=missing,
        duplicate_regular_minutes=(
            len(observed)
            - len(unique_observed)
        ),
    )
