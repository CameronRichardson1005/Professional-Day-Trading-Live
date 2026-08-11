import logging
import sys
import time

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any, TextIO


class LogStream:
    """
    Redirect print output through logging while preserving line boundaries.
    """

    def __init__(
        self,
        logger: logging.Logger,
        level: int,
    ) -> None:
        self.logger = logger
        self.level = level
        self.buffer = ""

    def write(self, message: str) -> int:
        self.buffer += message

        while "\n" in self.buffer:
            line, self.buffer = self.buffer.split("\n", 1)

            if line:
                self.logger.log(self.level, line)
            else:
                self.logger.log(self.level, "")

        return len(message)

    def flush(self) -> None:
        if self.buffer:
            self.logger.log(self.level, self.buffer)
            self.buffer = ""

    def isatty(self) -> bool:
        return False


def setup_logging() -> Path:
    """
    Write console output and errors to a dated file in logs/.
    """
    log_directory = Path("logs")
    log_directory.mkdir(parents=True, exist_ok=True)

    log_path = log_directory / (
        datetime.now().strftime("%Y-%m-%d") + ".log"
    )

    original_stdout: TextIO = sys.__stdout__
    original_stderr: TextIO = sys.__stderr__

    logger = logging.getLogger("trading_bot")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    logger.propagate = False

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console_handler = logging.StreamHandler(
        original_stdout
    )
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)

    file_handler = logging.FileHandler(
        log_path,
        mode="a",
        encoding="utf-8",
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)

    logger.addHandler(console_handler)
    logger.addHandler(file_handler)

    sys.stdout = LogStream(
        logger=logger,
        level=logging.INFO,
    )
    sys.stderr = LogStream(
        logger=logger,
        level=logging.ERROR,
    )

    return log_path


def call_with_retries(
    func: Callable[..., Any],
    *args: Any,
    max_retries: int = 3,
    backoff_seconds: int = 2,
    label: str = "request",
    **kwargs: Any,
) -> Any:
    last_error: Exception | None = None

    for attempt in range(1, max_retries + 1):
        try:
            result = func(*args, **kwargs)

            if hasattr(result, "raise_for_status"):
                result.raise_for_status()

            return result

        except Exception as error:
            last_error = error

            if attempt == max_retries:
                break

            wait_seconds = backoff_seconds * attempt

            print(
                f"{label} failed "
                f"(attempt {attempt}/{max_retries}): "
                f"{error}. Retrying in {wait_seconds} seconds."
            )

            time.sleep(wait_seconds)

    if last_error is None:
        raise RuntimeError(
            f"{label} failed without an error message."
        )

    raise last_error