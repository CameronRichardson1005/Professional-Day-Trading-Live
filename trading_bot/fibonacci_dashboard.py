from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from .config import (
    DASHBOARD_INGEST_KEY,
    DASHBOARD_REQUEST_TIMEOUT,
    DASHBOARD_SITE_TOKEN,
    DASHBOARD_URL,
)
from .fibonacci_paper import fibonacci_paper_status


class FibonacciDashboardPublisher:
    """
    Publishes read-only Fibonacci forward-paper status.

    This class cannot submit, modify, cancel, or preview orders.
    """

    def __init__(
        self,
        url: str | None = None,
        ingest_key: str = DASHBOARD_INGEST_KEY,
        site_token: str = DASHBOARD_SITE_TOKEN,
        timeout: tuple[int, int] = DASHBOARD_REQUEST_TIMEOUT,
        post_fn=None,
    ) -> None:
        base_url = (
            url
            or DASHBOARD_URL.replace(
                "/api/sessions/latest",
                "",
            ).rstrip("/")
        )

        self.url = (
            f"{base_url}/api/fibonacci-paper/latest"
        )
        self.ingest_key = ingest_key
        self.site_token = site_token
        self.timeout = timeout
        self.post_fn = post_fn or requests.post

    @staticmethod
    def _metrics_payload(
        metrics: dict[str, object],
    ) -> dict[str, Any]:
        return {
            "qualifyingSetups": int(
                metrics["total_setups"]
            ),
            "closedTrades": int(
                metrics["closed_trades"]
            ),
            "wins": int(metrics["wins"]),
            "losses": int(metrics["losses"]),
            "winRatePct": metrics["win_rate_pct"],
            "profitFactor": metrics["profit_factor"],
            "averageReturnPct": (
                metrics["average_return_pct"]
            ),
            "cumulativeReturnPct": float(
                metrics["cumulative_return_pct"]
            ),
        }

    @staticmethod
    def _latest_setup_payload(
        setup: dict[str, str] | None,
    ) -> dict[str, Any] | None:
        if setup is None:
            return None

        return {
            "tradingDate": setup["date"],
            "symbol": setup["symbol"],
            "fibonacciLevel": setup[
                "fibonacci_level"
            ],
            "outcome": setup["outcome"],
            "netReturnPct": float(
                setup["net_return_pct"]
            ),
            "submitted": "NO",
        }

    @classmethod
    def build_payload(
        cls,
        *,
        ledger_path: str | Path = (
            "reports/fibonacci-paper/"
            "fibonacci_paper_ledger.csv"
        ),
        logs_directory: str | Path = "logs",
    ) -> dict[str, Any]:
        status = fibonacci_paper_status(
            ledger_path=ledger_path,
            logs_directory=logs_directory,
        )

        return {
            "tradingDate": str(status["today"]),
            "updatedAt": (
                datetime.now(timezone.utc)
                .isoformat(timespec="seconds")
                .replace("+00:00", "Z")
            ),
            "todayCompleted": bool(
                status["today_completed"]
            ),
            "safetyStatus": (
                "PAPER ONLY — NOT SUBMITTED"
            ),
            "forward": cls._metrics_payload(
                status["forward"]
            ),
            "latestForwardSetup": (
                cls._latest_setup_payload(
                    status["latest_forward_setup"]
                )
            ),
        }

    def publish(
        self,
        *,
        ledger_path: str | Path = (
            "reports/fibonacci-paper/"
            "fibonacci_paper_ledger.csv"
        ),
        logs_directory: str | Path = "logs",
    ) -> dict[str, Any] | None:
        if not self.ingest_key:
            return None

        if not self.site_token:
            raise RuntimeError(
                "DASHBOARD_SITE_TOKEN is not configured."
            )

        payload = self.build_payload(
            ledger_path=ledger_path,
            logs_directory=logs_directory,
        )

        response = self.post_fn(
            self.url,
            headers={
                "x-dashboard-key": self.ingest_key,
                "OAI-Sites-Authorization": (
                    f"Bearer {self.site_token}"
                ),
            },
            json=payload,
            timeout=self.timeout,
        )

        try:
            response.raise_for_status()
        except requests.HTTPError as error:
            raise RuntimeError(
                f"Fibonacci dashboard returned "
                f"{response.status_code}: "
                f"{response.text}"
            ) from error

        result = response.json()

        if result.get("accepted") is not True:
            raise RuntimeError(
                "Dashboard did not accept Fibonacci status."
            )

        return result
