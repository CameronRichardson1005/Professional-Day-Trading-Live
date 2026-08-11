from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from .webull_paper_order_store import (
    WebullPaperOrderRecord,
    WebullPaperOrderStore,
)


class WebullPaperLifecycleError(RuntimeError):
    pass


def _bar_time(bar: dict[str, Any]) -> datetime:
    try:
        value = datetime.fromisoformat(
            str(bar["t"]).replace(
                "Z",
                "+00:00",
            )
        )
    except (
        KeyError,
        TypeError,
        ValueError,
    ) as error:
        raise WebullPaperLifecycleError(
            "INVALID_BAR_TIMESTAMP"
        ) from error

    if value.tzinfo is None:
        raise WebullPaperLifecycleError(
            "BAR_TIMESTAMP_MUST_BE_TIMEZONE_AWARE"
        )

    return value.astimezone(UTC)


class WebullPaperLifecycleTracker:
    """
    Advance LOCAL PAPER orders using completed market bars.

    This tracker contains no broker order placement, replacement,
    modification, or cancellation capability.
    """

    def __init__(
        self,
        *,
        store: WebullPaperOrderStore | None = None,
    ) -> None:
        self.store = (
            store or WebullPaperOrderStore()
        )

    @staticmethod
    def _open_from_bar(
        record: WebullPaperOrderRecord,
        *,
        bar: dict[str, Any],
        bar_time: datetime,
    ) -> WebullPaperOrderRecord:
        high = float(bar["h"])
        low = float(bar["l"])

        return replace(
            record,
            lifecycle_status="OPEN",
            filled_at=bar_time,
            fill_price=record.limit_price,
            highest_price=max(
                record.limit_price,
                high,
            ),
            lowest_price=min(
                record.limit_price,
                low,
            ),
        )

    @staticmethod
    def _update_excursion(
        record: WebullPaperOrderRecord,
        *,
        high: float,
        low: float,
    ) -> WebullPaperOrderRecord:
        if (
            record.highest_price is None
            or record.lowest_price is None
        ):
            raise WebullPaperLifecycleError(
                "OPEN_ORDER_MISSING_EXCURSION_STATE"
            )

        return replace(
            record,
            highest_price=max(
                record.highest_price,
                high,
            ),
            lowest_price=min(
                record.lowest_price,
                low,
            ),
        )

    @staticmethod
    def _close(
        record: WebullPaperOrderRecord,
        *,
        bar_time: datetime,
        exit_price: float,
        exit_reason: str,
    ) -> WebullPaperOrderRecord:
        return replace(
            record,
            lifecycle_status="CLOSED",
            closed_at=bar_time,
            exit_price=exit_price,
            exit_reason=exit_reason,
        )

    def process_bars(
        self,
        *,
        bars_by_symbol: dict[
            str,
            list[dict[str, Any]],
        ],
    ) -> list[WebullPaperOrderRecord]:
        records = self.store.load()
        changed: list[
            WebullPaperOrderRecord
        ] = []

        for _, original in records.items():
            if original.lifecycle_status == "CLOSED":
                continue

            if (
                original.target_price is None
                or original.stop_price is None
            ):
                continue

            bars = sorted(
                bars_by_symbol.get(
                    original.symbol,
                    [],
                ),
                key=lambda bar: str(
                    bar.get("t", "")
                ),
            )

            current = original

            for bar in bars:
                bar_time = _bar_time(bar)

                if bar_time < current.submitted_at:
                    continue

                # An order that is already OPEN may be replaying
                # cached session history after a restart. Never
                # apply bars from before its durable fill time.
                if (
                    current.lifecycle_status == "OPEN"
                    and current.filled_at is not None
                    and bar_time < current.filled_at
                ):
                    continue

                try:
                    high = float(bar["h"])
                    low = float(bar["l"])
                except (
                    KeyError,
                    TypeError,
                    ValueError,
                ) as error:
                    raise WebullPaperLifecycleError(
                        "INVALID_BAR_PRICE"
                    ) from error

                if high <= 0 or low <= 0 or low > high:
                    raise WebullPaperLifecycleError(
                        "INVALID_BAR_RANGE"
                    )

                if (
                    current.lifecycle_status
                    == "ENTRY PENDING"
                ):
                    if high < current.limit_price:
                        continue

                    current = self._open_from_bar(
                        current,
                        bar=bar,
                        bar_time=bar_time,
                    )

                if current.lifecycle_status != "OPEN":
                    continue

                current = self._update_excursion(
                    current,
                    high=high,
                    low=low,
                )

                stop_hit = (
                    low <= current.stop_price
                )
                target_hit = (
                    high >= current.target_price
                )

                if stop_hit:
                    current = self._close(
                        current,
                        bar_time=bar_time,
                        exit_price=current.stop_price,
                        exit_reason="STOP",
                    )
                    break

                if target_hit:
                    current = self._close(
                        current,
                        bar_time=bar_time,
                        exit_price=current.target_price,
                        exit_reason="TARGET",
                    )
                    break

            if current != original:
                persisted = self.store.update(
                    current
                )
                changed.append(persisted)

        return changed


def _completed_bars_before(
    *,
    bars: list[dict[str, Any]],
    cutoff: datetime,
) -> list[dict[str, Any]]:
    return [
        bar
        for bar in bars
        if _bar_time(bar) < cutoff
    ]


def _finalize_at_cutoff(
    tracker: WebullPaperLifecycleTracker,
    *,
    cutoff: datetime,
    bars_by_symbol: dict[
        str,
        list[dict[str, Any]],
    ],
) -> list[WebullPaperOrderRecord]:
    """
    Finalise remaining LOCAL PAPER orders at session cutoff.

    ENTRY PENDING -> CLOSED / NO ENTRY
    OPEN -> CLOSED / TIME EXIT using the last completed bar close.
    """
    if cutoff.tzinfo is None:
        raise WebullPaperLifecycleError(
            "CUTOFF_MUST_BE_TIMEZONE_AWARE"
        )

    cutoff = cutoff.astimezone(UTC)

    filtered = {
        symbol: _completed_bars_before(
            bars=bars,
            cutoff=cutoff,
        )
        for symbol, bars in bars_by_symbol.items()
    }

    # First process every completed pre-cutoff bar normally.
    tracker.process_bars(
        bars_by_symbol=filtered
    )

    records = tracker.store.load()
    finalized: list[
        WebullPaperOrderRecord
    ] = []

    for original in records.values():
        if original.lifecycle_status == "CLOSED":
            continue

        # Legacy records without durable target/stop information
        # cannot be reconstructed safely.
        if (
            original.target_price is None
            or original.stop_price is None
        ):
            continue

        if original.lifecycle_status == "ENTRY PENDING":
            current = replace(
                original,
                lifecycle_status="CLOSED",
                closed_at=cutoff,
                exit_reason="NO ENTRY",
            )

            finalized.append(
                tracker.store.update(current)
            )
            continue

        if original.lifecycle_status != "OPEN":
            continue

        eligible = [
            bar
            for bar in filtered.get(
                original.symbol,
                [],
            )
            if (
                original.filled_at is None
                or _bar_time(bar)
                >= original.filled_at
            )
        ]

        if not eligible:
            raise WebullPaperLifecycleError(
                "TIME_EXIT_REQUIRES_COMPLETED_BAR"
            )

        final_bar = max(
            eligible,
            key=_bar_time,
        )

        try:
            final_close = float(
                final_bar["c"]
            )
        except (
            KeyError,
            TypeError,
            ValueError,
        ) as error:
            raise WebullPaperLifecycleError(
                "INVALID_TIME_EXIT_CLOSE"
            ) from error

        if final_close <= 0:
            raise WebullPaperLifecycleError(
                "INVALID_TIME_EXIT_CLOSE"
            )

        current = replace(
            original,
            lifecycle_status="CLOSED",
            closed_at=cutoff,
            exit_price=final_close,
            exit_reason="TIME EXIT",
        )

        finalized.append(
            tracker.store.update(current)
        )

    return finalized


WebullPaperLifecycleTracker.finalize_at_cutoff = (
    _finalize_at_cutoff
)
