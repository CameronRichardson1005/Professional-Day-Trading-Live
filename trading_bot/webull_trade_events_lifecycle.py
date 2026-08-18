from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any, Callable


class WebullTradeEventsLifecycleError(
    RuntimeError
):
    pass


@dataclass(frozen=True)
class WebullTradeEventsStartupResult:
    trusted: bool
    polls: int


class WebullTradeEventsLifecycle:
    """
    Parent-side lifecycle guard for the Trade Events runtime.

    This class owns startup/shutdown sequencing only.

    Startup is successful only after the parent controller
    reports trusted=True, which itself requires:

        CONNECTED
            -> broker reconciliation
            -> health.mark_reconciled()

    Any startup failure or runtime polling failure stops the
    isolated worker and leaves Trade Events untrusted.
    """

    def __init__(
        self,
        *,
        runtime: Any,
        startup_timeout_seconds: float = 10.0,
        poll_interval_seconds: float = 0.05,
        monotonic: Callable[[], float] | None = None,
        sleeper: Callable[[float], None] | None = None,
    ) -> None:
        try:
            startup_timeout = float(
                startup_timeout_seconds
            )
            poll_interval = float(
                poll_interval_seconds
            )
        except (TypeError, ValueError) as error:
            raise WebullTradeEventsLifecycleError(
                "TRADE_EVENTS_LIFECYCLE_TIMING_INVALID"
            ) from error

        if (
            startup_timeout <= 0
            or poll_interval <= 0
        ):
            raise WebullTradeEventsLifecycleError(
                "TRADE_EVENTS_LIFECYCLE_TIMING_INVALID"
            )

        for attribute in (
            "supervisor",
            "controller",
            "health",
        ):
            if not hasattr(
                runtime,
                attribute,
            ):
                raise WebullTradeEventsLifecycleError(
                    "TRADE_EVENTS_RUNTIME_INVALID"
                )

        self.runtime = runtime
        self.startup_timeout_seconds = (
            startup_timeout
        )
        self.poll_interval_seconds = (
            poll_interval
        )
        self.monotonic = (
            monotonic
            if monotonic is not None
            else time.monotonic
        )
        self.sleeper = (
            sleeper
            if sleeper is not None
            else time.sleep
        )

    def _mark_lost(
        self,
        reason: str,
    ) -> None:
        self.runtime.health.mark_worker_lost(
            reason
        )

    def _stop_after_failure(
        self,
        reason: str,
    ) -> None:
        try:
            self.runtime.supervisor.stop()
        except Exception as error:
            self._mark_lost(
                "TRADE_EVENTS_STOP_FAILED"
            )

            raise WebullTradeEventsLifecycleError(
                "TRADE_EVENTS_STOP_FAILED"
            ) from error

        self._mark_lost(
            reason
        )

    def start(
        self,
    ) -> WebullTradeEventsStartupResult:
        """
        Start the isolated child and wait until the stream is
        trusted.

        Merely constructing the lifecycle never starts anything.
        """

        try:
            if self.runtime.supervisor.is_alive():
                raise WebullTradeEventsLifecycleError(
                    "TRADE_EVENTS_ALREADY_RUNNING"
                )
        except WebullTradeEventsLifecycleError:
            raise
        except Exception as error:
            self._mark_lost(
                "TRADE_EVENTS_LIVENESS_UNKNOWN"
            )

            raise WebullTradeEventsLifecycleError(
                "TRADE_EVENTS_LIVENESS_UNKNOWN"
            ) from error

        try:
            self.runtime.supervisor.start()
        except Exception as error:
            self._mark_lost(
                "TRADE_EVENTS_WORKER_START_FAILED"
            )

            raise WebullTradeEventsLifecycleError(
                "TRADE_EVENTS_WORKER_START_FAILED"
            ) from error

        deadline = (
            self.monotonic()
            + self.startup_timeout_seconds
        )

        polls = 0

        while True:
            try:
                result = (
                    self.runtime.controller
                    .poll_once()
                )
            except Exception as error:
                self._stop_after_failure(
                    "TRADE_EVENTS_STARTUP_FAILED"
                )

                raise WebullTradeEventsLifecycleError(
                    "TRADE_EVENTS_STARTUP_FAILED"
                ) from error

            polls += 1

            if bool(
                getattr(
                    result,
                    "trusted",
                    False,
                )
            ):
                return WebullTradeEventsStartupResult(
                    trusted=True,
                    polls=polls,
                )

            fatal_reason = getattr(
                self.runtime.health,
                "fatal_reason",
                None,
            )

            if fatal_reason:
                self._stop_after_failure(
                    str(
                        fatal_reason
                    )
                )

                raise WebullTradeEventsLifecycleError(
                    "TRADE_EVENTS_STARTUP_FATAL:"
                    f"{fatal_reason}"
                )

            if (
                self.monotonic()
                >= deadline
            ):
                self._stop_after_failure(
                    "TRADE_EVENTS_STARTUP_TIMEOUT"
                )

                raise WebullTradeEventsLifecycleError(
                    "TRADE_EVENTS_STARTUP_TIMEOUT"
                )

            self.sleeper(
                self.poll_interval_seconds
            )

    def poll_once(
        self,
    ) -> Any:
        """
        Perform one guarded runtime poll.

        A polling failure stops the child and revokes trust.
        """

        try:
            return (
                self.runtime.controller
                .poll_once()
            )
        except Exception as error:
            self._stop_after_failure(
                "TRADE_EVENTS_RUNTIME_FAILED"
            )

            raise WebullTradeEventsLifecycleError(
                "TRADE_EVENTS_RUNTIME_FAILED"
            ) from error

    def stop(
        self,
    ) -> bool:
        """
        Stop the child and explicitly revoke stream trust.
        """

        try:
            stopped = bool(
                self.runtime.supervisor.stop()
            )
        except Exception as error:
            self._mark_lost(
                "TRADE_EVENTS_STOP_FAILED"
            )

            raise WebullTradeEventsLifecycleError(
                "TRADE_EVENTS_STOP_FAILED"
            ) from error

        self._mark_lost(
            "TRADE_EVENTS_STOPPED"
        )

        return stopped
