from __future__ import annotations

import multiprocessing as mp
import os
from collections.abc import Callable
from typing import Any


class WebullTradeEventsProcessError(
    RuntimeError
):
    pass


def _redirect_worker_output() -> None:
    """
    Redirect the isolated worker's stdout and stderr to
    /dev/null before any Webull SDK code is allowed to run.

    This protects against SDK print statements that expose
    signing metadata or other authentication details.
    """
    descriptor = os.open(
        os.devnull,
        os.O_WRONLY,
    )

    try:
        os.dup2(
            descriptor,
            1,
        )

        os.dup2(
            descriptor,
            2,
        )
    finally:
        if descriptor not in {
            1,
            2,
        }:
            os.close(
                descriptor
            )


def _worker_bootstrap(
    worker_target: Callable[..., Any],
    worker_args: tuple[Any, ...],
) -> None:
    """
    Security boundary for the child process.

    Output redirection happens before the supplied target
    executes.
    """
    _redirect_worker_output()

    worker_target(
        *worker_args
    )


class WebullTradeEventsProcessSupervisor:
    """
    Own a disposable child process for Webull Trade Events.

    The Webull SDK stream is deliberately isolated because its
    current implementation has an unbounded retry loop and no
    public shutdown method.

    No Webull API connection is made merely by constructing
    this object.

    The parent can always terminate the child and uses kill()
    as a final fallback if terminate() cannot stop it.
    """

    def __init__(
        self,
        *,
        worker_target: Callable[..., Any],
        worker_args: tuple[Any, ...] = (),
        process_factory: Callable[..., Any] | None = None,
        process_name: str = (
            "webull-trade-events"
        ),
        stop_timeout_seconds: float = 2.0,
    ) -> None:
        if not callable(
            worker_target
        ):
            raise WebullTradeEventsProcessError(
                "TRADE_EVENTS_WORKER_TARGET_INVALID"
            )

        if not isinstance(
            worker_args,
            tuple,
        ):
            raise WebullTradeEventsProcessError(
                "TRADE_EVENTS_WORKER_ARGS_INVALID"
            )

        process_name = str(
            process_name
        ).strip()

        if not process_name:
            raise WebullTradeEventsProcessError(
                "TRADE_EVENTS_PROCESS_NAME_REQUIRED"
            )

        try:
            timeout = float(
                stop_timeout_seconds
            )
        except (
            TypeError,
            ValueError,
        ) as error:
            raise WebullTradeEventsProcessError(
                "TRADE_EVENTS_STOP_TIMEOUT_INVALID"
            ) from error

        if timeout <= 0:
            raise WebullTradeEventsProcessError(
                "TRADE_EVENTS_STOP_TIMEOUT_INVALID"
            )

        self.worker_target = (
            worker_target
        )

        self.worker_args = (
            worker_args
        )

        self.process_factory = (
            process_factory
            if process_factory is not None
            else mp.Process
        )

        self.process_name = (
            process_name
        )

        self.stop_timeout_seconds = (
            timeout
        )

        self._process: Any | None = None

    @property
    def process(self) -> Any | None:
        return self._process

    def is_alive(self) -> bool:
        process = self._process

        if process is None:
            return False

        try:
            return bool(
                process.is_alive()
            )
        except Exception as error:
            raise WebullTradeEventsProcessError(
                "TRADE_EVENTS_LIVENESS_UNKNOWN"
            ) from error

    def start(self) -> None:
        if self.is_alive():
            raise WebullTradeEventsProcessError(
                "TRADE_EVENTS_WORKER_ALREADY_RUNNING"
            )

        try:
            process = self.process_factory(
                target=_worker_bootstrap,
                args=(
                    self.worker_target,
                    self.worker_args,
                ),
                name=self.process_name,
                daemon=True,
            )
        except Exception as error:
            raise WebullTradeEventsProcessError(
                "TRADE_EVENTS_WORKER_CREATE_FAILED"
            ) from error

        self._process = (
            process
        )

        try:
            process.start()
        except Exception as error:
            self._process = None

            raise WebullTradeEventsProcessError(
                "TRADE_EVENTS_WORKER_START_FAILED"
            ) from error

    def ensure_healthy(self) -> None:
        if self._process is None:
            raise WebullTradeEventsProcessError(
                "TRADE_EVENTS_WORKER_NOT_STARTED"
            )

        if not self.is_alive():
            raise WebullTradeEventsProcessError(
                "TRADE_EVENTS_WORKER_NOT_RUNNING"
            )

    def stop(self) -> bool:
        process = self._process

        if process is None:
            return False

        if not self.is_alive():
            try:
                process.join(
                    timeout=0,
                )
            except Exception as error:
                raise WebullTradeEventsProcessError(
                    "TRADE_EVENTS_WORKER_JOIN_FAILED"
                ) from error

            return False

        try:
            process.terminate()
        except Exception as error:
            raise WebullTradeEventsProcessError(
                "TRADE_EVENTS_WORKER_TERMINATE_FAILED"
            ) from error

        try:
            process.join(
                timeout=(
                    self.stop_timeout_seconds
                ),
            )
        except Exception as error:
            raise WebullTradeEventsProcessError(
                "TRADE_EVENTS_WORKER_JOIN_FAILED"
            ) from error

        if not self.is_alive():
            return True

        kill = getattr(
            process,
            "kill",
            None,
        )

        if not callable(
            kill
        ):
            raise WebullTradeEventsProcessError(
                "TRADE_EVENTS_WORKER_STOP_FAILED"
            )

        try:
            kill()
        except Exception as error:
            raise WebullTradeEventsProcessError(
                "TRADE_EVENTS_WORKER_KILL_FAILED"
            ) from error

        try:
            process.join(
                timeout=(
                    self.stop_timeout_seconds
                ),
            )
        except Exception as error:
            raise WebullTradeEventsProcessError(
                "TRADE_EVENTS_WORKER_JOIN_FAILED"
            ) from error

        if self.is_alive():
            raise WebullTradeEventsProcessError(
                "TRADE_EVENTS_WORKER_STOP_FAILED"
            )

        return True
