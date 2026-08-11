from __future__ import annotations

import csv

from dataclasses import asdict, dataclass
from pathlib import Path

from .fibonacci_retracement import RetracementSetup


PAPER_RULE_NAME = (
    "FIB_61_8_MIN_0_50_ATR_DURATION_15_"
    "LOWER_PULLBACK_VOLUME"
)

PAPER_WARNING = "PAPER ONLY — NOT SUBMITTED"


@dataclass(frozen=True)
class FibonacciPaperRecord:
    date: str
    symbol: str
    data_feed: str
    paper_status: str
    submitted: str
    observation_type: str
    rule_name: str

    fibonacci_level: str
    retracement_ratio: float

    atr: float | None
    atr_pct: float | None

    impulse_start_time: str
    impulse_end_time: str
    impulse_atr_multiple: float | None
    impulse_duration_minutes: int | None
    impulse_average_volume: float | None

    retracement_touch_time: str
    retracement_price: float | None
    pullback_duration_minutes: int | None
    pullback_average_volume: float | None
    pullback_volume_ratio: float | None

    confirmation_time: str
    confirmation_above_vwap: bool | None

    entry_price: float | None
    entry_time: str
    stop_price: float | None
    target_price: float | None
    reward_risk: float | None

    outcome: str
    exit_time: str
    exit_price: float | None
    exit_reason: str
    net_return_pct: float | None

    modeled_slippage_bps: float
    detail: str


def qualifies_for_fibonacci_paper(
    setup: RetracementSetup,
) -> bool:
    return (
        setup.fibonacci_level == "FIB_61_8"
        and setup.setup_found
        and setup.impulse_atr_multiple is not None
        and setup.impulse_atr_multiple >= 0.50
        and setup.impulse_duration_minutes is not None
        and setup.impulse_duration_minutes >= 15
        and setup.pullback_volume_ratio is not None
        and setup.pullback_volume_ratio < 1.0
        and setup.reward_risk is not None
        and setup.reward_risk >= 1.5
    )


def build_fibonacci_paper_record(
    setup: RetracementSetup,
    *,
    modeled_slippage_bps: float,
    observation_type: str = "FORWARD_PAPER",
) -> FibonacciPaperRecord | None:
    if not qualifies_for_fibonacci_paper(setup):
        return None

    observation_type = observation_type.strip().upper()

    if observation_type not in {
        "FORWARD_PAPER",
        "HISTORICAL_VALIDATION",
    }:
        raise ValueError(
            "Observation type must be FORWARD_PAPER or "
            "HISTORICAL_VALIDATION."
        )

    return FibonacciPaperRecord(
        date=setup.date,
        symbol=setup.symbol,
        data_feed=setup.data_feed,
        paper_status=PAPER_WARNING,
        submitted="NO",
        observation_type=observation_type,
        rule_name=PAPER_RULE_NAME,
        fibonacci_level=setup.fibonacci_level,
        retracement_ratio=setup.retracement_ratio,
        atr=setup.atr,
        atr_pct=setup.atr_pct,
        impulse_start_time=setup.impulse_start_time,
        impulse_end_time=setup.impulse_end_time,
        impulse_atr_multiple=(
            setup.impulse_atr_multiple
        ),
        impulse_duration_minutes=(
            setup.impulse_duration_minutes
        ),
        impulse_average_volume=(
            setup.impulse_average_volume
        ),
        retracement_touch_time=(
            setup.retracement_touch_time
        ),
        retracement_price=setup.retracement_price,
        pullback_duration_minutes=(
            setup.pullback_duration_minutes
        ),
        pullback_average_volume=(
            setup.pullback_average_volume
        ),
        pullback_volume_ratio=(
            setup.pullback_volume_ratio
        ),
        confirmation_time=setup.confirmation_time,
        confirmation_above_vwap=(
            setup.confirmation_above_vwap
        ),
        entry_price=setup.entry_price,
        entry_time=setup.entry_time,
        stop_price=setup.stop_price,
        target_price=setup.target_price,
        reward_risk=setup.reward_risk,
        outcome=setup.outcome,
        exit_time=setup.exit_time,
        exit_price=setup.exit_price,
        exit_reason=setup.exit_reason,
        net_return_pct=setup.net_return_pct,
        modeled_slippage_bps=modeled_slippage_bps,
        detail=setup.detail,
    )


class FibonacciPaperLedger:
    """
    CSV-only paper ledger.

    Existing matching records are updated instead of duplicated,
    allowing a setup to progress from NO ENTRY to WIN or LOSS.
    """

    def __init__(
        self,
        path: str | Path = (
            "reports/fibonacci-paper/"
            "fibonacci_paper_ledger.csv"
        ),
    ) -> None:
        self.path = Path(path)

    @staticmethod
    def _record_key(
        row: dict[str, object],
    ) -> tuple[str, ...]:
        return (
            str(row.get("date", "")),
            str(row.get("symbol", "")),
            str(row.get("fibonacci_level", "")),
            str(row.get("impulse_start_time", "")),
            str(row.get("impulse_end_time", "")),
            str(row.get("confirmation_time", "")),
        )

    def upsert(
        self,
        records: list[FibonacciPaperRecord],
    ) -> Path:
        self.path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        rows_by_key: dict[
            tuple[str, ...],
            dict[str, object],
        ] = {}

        if self.path.exists():
            with self.path.open(
                newline="",
                encoding="utf-8",
            ) as file:
                for row in csv.DictReader(file):
                    migrated = dict(row)

                    if not migrated.get(
                        "observation_type"
                    ):
                        migrated[
                            "observation_type"
                        ] = "HISTORICAL_VALIDATION"

                    rows_by_key[
                        self._record_key(migrated)
                    ] = migrated

        for record in records:
            row = asdict(record)
            rows_by_key[
                self._record_key(row)
            ] = row

        fields = list(
            FibonacciPaperRecord
            .__dataclass_fields__
            .keys()
        )

        ordered_rows = sorted(
            rows_by_key.values(),
            key=lambda row: (
                str(row.get("date", "")),
                str(row.get("symbol", "")),
                str(
                    row.get(
                        "confirmation_time",
                        "",
                    )
                ),
            ),
            reverse=True,
        )

        with self.path.open(
            "w",
            newline="",
            encoding="utf-8",
        ) as file:
            writer = csv.DictWriter(
                file,
                fieldnames=fields,
            )
            writer.writeheader()
            writer.writerows(ordered_rows)

        return self.path


def fibonacci_paper_status(
    ledger_path: str | Path = (
        "reports/fibonacci-paper/"
        "fibonacci_paper_ledger.csv"
    ),
    logs_directory: str | Path = "logs",
) -> dict[str, object]:
    """
    Summarize genuine forward paper observations separately
    from historical validation records.

    This function is strictly read-only.
    """
    from datetime import datetime
    from zoneinfo import ZoneInfo

    ledger_path = Path(ledger_path)
    logs_directory = Path(logs_directory)

    eastern = ZoneInfo("America/New_York")
    today = datetime.now(eastern).strftime("%Y-%m-%d")

    completion_marker = (
        logs_directory
        / f"fibonacci-paper-complete-{today}"
    )

    rows: list[dict[str, str]] = []

    if ledger_path.exists():
        with ledger_path.open(
            newline="",
            encoding="utf-8",
        ) as file:
            for row in csv.DictReader(file):
                migrated = dict(row)

                if not migrated.get(
                    "observation_type"
                ):
                    migrated[
                        "observation_type"
                    ] = "HISTORICAL_VALIDATION"

                rows.append(migrated)

    forward_rows = [
        row
        for row in rows
        if row.get("observation_type")
        == "FORWARD_PAPER"
    ]

    historical_rows = [
        row
        for row in rows
        if row.get("observation_type")
        == "HISTORICAL_VALIDATION"
    ]

    def summarize(
        selected: list[dict[str, str]],
    ) -> dict[str, object]:
        closed = [
            row
            for row in selected
            if row.get("outcome") in {
                "WIN",
                "LOSS",
            }
        ]

        wins = [
            row
            for row in closed
            if row.get("outcome") == "WIN"
        ]

        losses = [
            row
            for row in closed
            if row.get("outcome") == "LOSS"
        ]

        returns = [
            float(row["net_return_pct"])
            for row in closed
            if row.get("net_return_pct")
            not in {"", None}
        ]

        positive = [
            value
            for value in returns
            if value > 0
        ]

        negative = [
            value
            for value in returns
            if value < 0
        ]

        return {
            "total_setups": len(selected),
            "closed_trades": len(closed),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate_pct": (
                len(wins) / len(closed) * 100.0
                if closed
                else None
            ),
            "average_return_pct": (
                sum(returns) / len(returns)
                if returns
                else None
            ),
            "cumulative_return_pct": sum(returns),
            "profit_factor": (
                sum(positive)
                / abs(sum(negative))
                if negative
                else None
            ),
        }

    latest_forward = None

    if forward_rows:
        latest_forward = sorted(
            forward_rows,
            key=lambda row: (
                row.get("date", ""),
                row.get("confirmation_time", ""),
                row.get("symbol", ""),
            ),
            reverse=True,
        )[0]

    latest_historical = None

    if historical_rows:
        latest_historical = sorted(
            historical_rows,
            key=lambda row: (
                row.get("date", ""),
                row.get("confirmation_time", ""),
                row.get("symbol", ""),
            ),
            reverse=True,
        )[0]

    return {
        "today": today,
        "today_completed": completion_marker.exists(),
        "completion_marker": str(completion_marker),
        "ledger_path": str(ledger_path),
        "ledger_exists": ledger_path.exists(),
        "forward": summarize(forward_rows),
        "historical": summarize(historical_rows),
        "latest_forward_setup": latest_forward,
        "latest_historical_setup": latest_historical,
        "safety_status": PAPER_WARNING,
    }


def print_fibonacci_paper_status(
    ledger_path: str | Path = (
        "reports/fibonacci-paper/"
        "fibonacci_paper_ledger.csv"
    ),
    logs_directory: str | Path = "logs",
) -> dict[str, object]:
    status = fibonacci_paper_status(
        ledger_path=ledger_path,
        logs_directory=logs_directory,
    )

    print()
    print("===================================")
    print(" Fibonacci Paper Status")
    print("===================================")
    print(status["safety_status"])
    print(
        "Today's scheduled check:",
        (
            "COMPLETED"
            if status["today_completed"]
            else "NOT COMPLETED"
        ),
    )
    print(
        "Completion marker:",
        status["completion_marker"],
    )
    print("Paper ledger:", status["ledger_path"])

    def print_section(
        title: str,
        metrics: dict[str, object],
    ) -> None:
        print()
        print(title)
        print("-" * len(title))
        print(
            "Qualifying setups:",
            metrics["total_setups"],
        )
        print(
            "Closed paper trades:",
            metrics["closed_trades"],
        )
        print(
            f"Wins / losses: "
            f"{metrics['wins']} / "
            f"{metrics['losses']}"
        )

        win_rate = metrics["win_rate_pct"]

        print(
            "Win rate:",
            (
                f"{win_rate:.2f}%"
                if isinstance(win_rate, float)
                else "N/A"
            ),
        )

        profit_factor = metrics["profit_factor"]

        print(
            "Profit factor:",
            (
                f"{profit_factor:.3f}"
                if isinstance(
                    profit_factor,
                    float,
                )
                else "N/A"
            ),
        )

        average_return = metrics[
            "average_return_pct"
        ]

        print(
            "Average return:",
            (
                f"{average_return:.4f}%"
                if isinstance(
                    average_return,
                    float,
                )
                else "N/A"
            ),
        )

        print(
            "Cumulative return:",
            f"{metrics['cumulative_return_pct']:.4f}%",
        )

    print_section(
        "FORWARD PAPER PERFORMANCE",
        status["forward"],
    )

    print_section(
        "HISTORICAL VALIDATION — EXCLUDED "
        "FROM FORWARD RESULTS",
        status["historical"],
    )

    latest = status["latest_forward_setup"]

    print()
    print("Latest forward qualifying setup:")

    if not isinstance(latest, dict):
        print("None recorded yet.")
    else:
        print(
            f"{latest.get('date', '')} · "
            f"{latest.get('symbol', '')} · "
            f"{latest.get('fibonacci_level', '')}"
        )
        print(
            f"Outcome: "
            f"{latest.get('outcome', 'Pending')}"
        )
        print(
            f"Return: "
            f"{latest.get('net_return_pct') or 'Pending'}"
        )
        print(
            f"Submitted: "
            f"{latest.get('submitted', 'NO')}"
        )

    print()
    print("PAPER ONLY — NOT SUBMITTED")

    return status

