from __future__ import annotations

from dataclasses import dataclass
from queue import Empty
from typing import Any, Callable

from .webull_trade_events_journal import (
    WebullTradeEventsHealthState,
    WebullTradeEventsJournal,
    WebullTradeEventsJournalError,
)


class WebullTradeEventsParentError(
    RuntimeError
):
    pass


@dataclass(frozen=True)
class WebullTradeEventsPollResult:
    control_messages: int
    journaled_events: int
    duplicate_events: int
    dispatched_events: int
    trusted: bool


class WebullTradeEventsParentController:
    """
    Parent-side owner for sanitized Webull Trade Events.

    Security / durability ordering:

        child worker
            -> event queue
            -> durable journal + fsync
            -> optional parent event handler

    CONNECTED alone never makes the stream trusted.

    A successful broker reconciliation is required before
    trusted becomes True.

    Events received while the stream is untrusted are still
    journaled durably, but are deliberately not dispatched.
    Broker reconciliation is responsible for restoring the
    authoritative state after a disconnect or failure.
    """

    def __init__(
        self,
        *,
        event_queue: Any,
        control_queue: Any,
        journal: WebullTradeEventsJournal,
        reconcile: Callable[[], Any],
        event_handler: (
            Callable[[dict[str, Any]], None]
            | None
        ) = None,
        ensure_worker_healthy: (
            Callable[[], None]
            | None
        ) = None,
        health: (
            WebullTradeEventsHealthState
            | None
        ) = None,
    ) -> None:
        if not callable(reconcile):
            raise WebullTradeEventsParentError(
                "TRADE_EVENTS_RECONCILE_INVALID"
            )

        if (
            event_handler is not None
            and not callable(event_handler)
        ):
            raise WebullTradeEventsParentError(
                "TRADE_EVENTS_HANDLER_INVALID"
            )

        if (
            ensure_worker_healthy is not None
            and not callable(
                ensure_worker_healthy
            )
        ):
            raise WebullTradeEventsParentError(
                "TRADE_EVENTS_HEALTH_CHECK_INVALID"
            )

        self.event_queue = event_queue
        self.control_queue = control_queue
        self.journal = journal
        self.reconcile = reconcile
        self.event_handler = event_handler
        self.ensure_worker_healthy = (
            ensure_worker_healthy
        )

        self.health = (
            health
            if health is not None
            else WebullTradeEventsHealthState()
        )

    def _fail_closed(
        self,
        reason: str,
    ) -> None:
        self.health.mark_worker_lost(
            reason
        )

    def _check_worker(
        self,
    ) -> None:
        if self.ensure_worker_healthy is None:
            return

        try:
            self.ensure_worker_healthy()
        except Exception as error:
            self._fail_closed(
                "TRADE_EVENTS_WORKER_NOT_HEALTHY"
            )

            raise WebullTradeEventsParentError(
                "TRADE_EVENTS_WORKER_NOT_HEALTHY"
            ) from error

    def _handle_control(
        self,
        message: Any,
    ) -> None:
        try:
            self.health.handle_control(
                message
            )
        except WebullTradeEventsJournalError as error:
            self._fail_closed(
                "TRADE_EVENTS_CONTROL_INVALID"
            )

            raise WebullTradeEventsParentError(
                "TRADE_EVENTS_CONTROL_INVALID"
            ) from error

        message_type = str(
            message.get(
                "type",
                "",
            )
        ).strip().upper()

        if (
            message_type == "CONNECTED"
            and self.health.reconciliation_required
        ):
            try:
                self.reconcile()
            except Exception as error:
                # Leave the stream untrusted.  The worker may
                # still be connected, but broker state has not
                # been authoritatively reconciled.
                raise WebullTradeEventsParentError(
                    "TRADE_EVENTS_RECONCILIATION_FAILED"
                ) from error

            try:
                self.health.mark_reconciled()
            except WebullTradeEventsJournalError as error:
                self._fail_closed(
                    "TRADE_EVENTS_RECONCILIATION_STATE_FAILED"
                )

                raise WebullTradeEventsParentError(
                    "TRADE_EVENTS_RECONCILIATION_STATE_FAILED"
                ) from error

    def _drain_controls(
        self,
    ) -> int:
        count = 0

        while True:
            try:
                message = (
                    self.control_queue
                    .get_nowait()
                )
            except Empty:
                break
            except Exception as error:
                self._fail_closed(
                    "TRADE_EVENTS_CONTROL_QUEUE_READ_FAILED"
                )

                raise WebullTradeEventsParentError(
                    "TRADE_EVENTS_CONTROL_QUEUE_READ_FAILED"
                ) from error

            self._handle_control(
                message
            )

            count += 1

        return count

    def _drain_events(
        self,
    ) -> tuple[int, int, int]:
        journaled = 0
        duplicates = 0
        dispatched = 0

        while True:
            try:
                event = (
                    self.event_queue
                    .get_nowait()
                )
            except Empty:
                break
            except Exception as error:
                self._fail_closed(
                    "TRADE_EVENTS_EVENT_QUEUE_READ_FAILED"
                )

                raise WebullTradeEventsParentError(
                    "TRADE_EVENTS_EVENT_QUEUE_READ_FAILED"
                ) from error

            try:
                is_new = self.journal.append(
                    event
                )
            except WebullTradeEventsJournalError as error:
                self._fail_closed(
                    "TRADE_EVENTS_JOURNAL_FAILED"
                )

                raise WebullTradeEventsParentError(
                    "TRADE_EVENTS_JOURNAL_FAILED"
                ) from error

            if not is_new:
                duplicates += 1
                continue

            journaled += 1

            # Never dispatch broker-derived state while trust
            # is absent.  The durable journal still preserves
            # the event for audit/recovery.
            if (
                not self.health.trusted
                or self.event_handler is None
            ):
                continue

            try:
                self.event_handler(
                    event
                )
            except Exception as error:
                self._fail_closed(
                    "TRADE_EVENTS_EVENT_HANDLER_FAILED"
                )

                raise WebullTradeEventsParentError(
                    "TRADE_EVENTS_EVENT_HANDLER_FAILED"
                ) from error

            dispatched += 1

        return (
            journaled,
            duplicates,
            dispatched,
        )

    def poll_once(
        self,
    ) -> WebullTradeEventsPollResult:
        """
        Perform one non-blocking parent processing cycle.

        Control messages are processed first so CONNECTED/FATAL
        trust transitions are applied before queued order events.
        """

        # Drain worker control messages before checking process
        # liveness. A worker may publish a sanitized FATAL reason
        # immediately before exiting; that reason must not be
        # overwritten by a generic worker-not-running failure.
        control_messages = (
            self._drain_controls()
        )

        # A FATAL control message already establishes a
        # fail-closed state. Preserve its specific reason and
        # allow the lifecycle layer to report it.
        if self.health.fatal_reason is None:
            self._check_worker()

        (
            journaled_events,
            duplicate_events,
            dispatched_events,
        ) = self._drain_events()

        return WebullTradeEventsPollResult(
            control_messages=(
                control_messages
            ),
            journaled_events=(
                journaled_events
            ),
            duplicate_events=(
                duplicate_events
            ),
            dispatched_events=(
                dispatched_events
            ),
            trusted=self.health.trusted,
        )
