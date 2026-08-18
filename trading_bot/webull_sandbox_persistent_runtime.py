from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any, Callable

from .webull_trade_events_lifecycle import (
    WebullTradeEventsLifecycle,
)


class WebullSandboxPersistentRuntimeError(
    RuntimeError
):
    pass


@dataclass(frozen=True)
class WebullSandboxPersistentRuntimeReport:
    trusted: bool
    startup_polls: int
    runtime_polls: int
    interrupted: bool
    worker_stopped: bool


class WebullSandboxPersistentRuntime:
    """
    Long-running read-only Webull sandbox execution supervisor.

    Responsibilities:

        Trade Events lifecycle.start()
            -> CONNECTED
            -> authoritative preflight/reconciliation
            -> trusted=True
            -> continuous guarded polling
            -> durable event journal
            -> trusted ledger synchronization

    This class exposes no order placement, replacement,
    cancellation, or position-close operation.

    Any polling failure or loss of trust fails closed and the
    Trade Events child is stopped before control returns.
    """

    def __init__(
        self,
        *,
        runtime: Any,
        lifecycle_factory: (
            Callable[..., Any]
            | None
        ) = None,
        poll_interval_seconds: float = 0.10,
        sleeper: (
            Callable[[float], None]
            | None
        ) = None,
    ) -> None:
        try:
            poll_interval = float(
                poll_interval_seconds
            )
        except (
            TypeError,
            ValueError,
        ) as error:
            raise WebullSandboxPersistentRuntimeError(
                "SANDBOX_RUNTIME_TIMING_INVALID"
            ) from error

        if poll_interval <= 0:
            raise WebullSandboxPersistentRuntimeError(
                "SANDBOX_RUNTIME_TIMING_INVALID"
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
                raise WebullSandboxPersistentRuntimeError(
                    "SANDBOX_RUNTIME_INVALID"
                )

        selected_factory = (
            lifecycle_factory
            if lifecycle_factory is not None
            else WebullTradeEventsLifecycle
        )

        if not callable(
            selected_factory
        ):
            raise WebullSandboxPersistentRuntimeError(
                "SANDBOX_RUNTIME_LIFECYCLE_FACTORY_INVALID"
            )

        self.runtime = runtime
        self.lifecycle_factory = (
            selected_factory
        )

        self.poll_interval_seconds = (
            poll_interval
        )

        self.sleeper = (
            sleeper
            if sleeper is not None
            else time.sleep
        )

        if not callable(
            self.sleeper
        ):
            raise WebullSandboxPersistentRuntimeError(
                "SANDBOX_RUNTIME_SLEEPER_INVALID"
            )

    @staticmethod
    def _validate_max_polls(
        max_polls: int | None,
    ) -> int | None:
        if max_polls is None:
            return None

        if (
            isinstance(
                max_polls,
                bool,
            )
            or not isinstance(
                max_polls,
                int,
            )
            or max_polls < 0
        ):
            raise WebullSandboxPersistentRuntimeError(
                "SANDBOX_RUNTIME_MAX_POLLS_INVALID"
            )

        return max_polls

    def _trusted(
        self,
        result: Any,
    ) -> bool:
        return (
            getattr(
                result,
                "trusted",
                False,
            )
            is True
        )

    def _trust_loss_reason(
        self,
    ) -> str:
        fatal_reason = getattr(
            self.runtime.health,
            "fatal_reason",
            None,
        )

        if fatal_reason:
            return str(
                fatal_reason
            )

        return "TRADE_EVENTS_TRUST_LOST"

    def run(
        self,
        *,
        max_polls: int | None = None,
    ) -> WebullSandboxPersistentRuntimeReport:
        """
        Run until:

        - max_polls is reached in an offline/bounded test,
        - Ctrl-C / KeyboardInterrupt requests a clean stop,
        - Trade Events loses trust, or
        - a lifecycle/runtime failure occurs.

        Production callers should leave max_polls=None.
        """

        bounded_polls = (
            self._validate_max_polls(
                max_polls
            )
        )

        lifecycle = None
        startup_result = None

        runtime_polls = 0
        interrupted = False

        runtime_error: (
            WebullSandboxPersistentRuntimeError
            | None
        ) = None

        shutdown_error: (
            WebullSandboxPersistentRuntimeError
            | None
        ) = None

        worker_stopped = False

        try:
            lifecycle = (
                self.lifecycle_factory(
                    runtime=self.runtime
                )
            )

            startup_result = (
                lifecycle.start()
            )

            if not self._trusted(
                startup_result
            ):
                raise WebullSandboxPersistentRuntimeError(
                    "SANDBOX_RUNTIME_STARTUP_UNTRUSTED"
                )

            while (
                bounded_polls is None
                or runtime_polls
                < bounded_polls
            ):
                result = lifecycle.poll_once()

                runtime_polls += 1

                if not self._trusted(
                    result
                ):
                    raise WebullSandboxPersistentRuntimeError(
                        "SANDBOX_RUNTIME_UNTRUSTED:"
                        f"{self._trust_loss_reason()}"
                    )

                if (
                    bounded_polls is not None
                    and runtime_polls
                    >= bounded_polls
                ):
                    break

                self.sleeper(
                    self.poll_interval_seconds
                )

        except KeyboardInterrupt:
            interrupted = True

        except WebullSandboxPersistentRuntimeError as error:
            runtime_error = error

        except Exception as error:
            runtime_error = (
                WebullSandboxPersistentRuntimeError(
                    "SANDBOX_RUNTIME_FAILED"
                )
            )

            runtime_error.__cause__ = (
                error
            )

        finally:
            if lifecycle is not None:
                try:
                    lifecycle.stop()
                except Exception as error:
                    shutdown_error = (
                        WebullSandboxPersistentRuntimeError(
                            "SANDBOX_RUNTIME_SHUTDOWN_FAILED"
                        )
                    )

                    shutdown_error.__cause__ = (
                        error
                    )

            try:
                worker_stopped = not bool(
                    self.runtime
                    .supervisor
                    .is_alive()
                )
            except Exception as error:
                if shutdown_error is None:
                    shutdown_error = (
                        WebullSandboxPersistentRuntimeError(
                            "SANDBOX_RUNTIME_SHUTDOWN_VERIFY_FAILED"
                        )
                    )

                    shutdown_error.__cause__ = (
                        error
                    )

            if (
                shutdown_error is None
                and not worker_stopped
            ):
                shutdown_error = (
                    WebullSandboxPersistentRuntimeError(
                        "SANDBOX_RUNTIME_WORKER_STILL_RUNNING"
                    )
                )

        if runtime_error is not None:
            if shutdown_error is not None:
                raise WebullSandboxPersistentRuntimeError(
                    "SANDBOX_RUNTIME_FAILED_AND_SHUTDOWN_FAILED"
                ) from runtime_error

            raise runtime_error

        if shutdown_error is not None:
            raise shutdown_error

        if startup_result is None:
            raise WebullSandboxPersistentRuntimeError(
                "SANDBOX_RUNTIME_STARTUP_RESULT_MISSING"
            )

        return WebullSandboxPersistentRuntimeReport(
            trusted=True,
            startup_polls=int(
                getattr(
                    startup_result,
                    "polls",
                    0,
                )
            ),
            runtime_polls=runtime_polls,
            interrupted=interrupted,
            worker_stopped=worker_stopped,
        )
