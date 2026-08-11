from __future__ import annotations

import csv
import hashlib
import math

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


FIBONACCI_TARGETS = {
    "FIB_38_2": 0.382,
    "FIB_50_0": 0.500,
    "FIB_61_8": 0.618,
}


@dataclass(frozen=True)
class FibonacciResearchRecord:
    date: str
    symbol: str
    data_feed: str
    target_variant: str
    target_ratio: float
    rule_variant: str
    rule_description: str
    setup_eligible: bool
    bars_processed: int
    opening_open: float | None
    opening_high: float | None
    opening_low: float | None
    opening_close: float | None
    opening_range: float | None
    opening_volume: float | None
    atr: float | None
    candle_atr_ratio: float | None
    red_candle: bool
    manipulation_candle: bool
    red_minutes: int
    green_minutes: int
    new_lows: int
    new_highs: int
    entry_price: float | None
    target_price: float | None
    stop_price: float | None
    reward_risk: float | None
    outcome: str
    entry_time: str
    exit_time: str
    exit_reason: str
    gross_return_pct: float | None
    net_return_pct: float | None
    detail: str


@dataclass(frozen=True)
class FibonacciMetrics:
    observations: int
    eligible_setups: int
    entries: int
    wins: int
    losses: int
    no_entry: int
    win_rate_pct: float | None
    average_return_pct: float | None
    total_return_pct: float
    profit_factor: float | None
    expectancy_pct: float | None
    maximum_drawdown_pct_points: float


RULES: tuple[
    tuple[str, str],
    ...
] = (
    (
        "ALL_COMPLETE",
        "All complete opening windows with ATR available",
    ),
    (
        "RED_CANDLE",
        "Opening 15-minute candle is red",
    ),
    (
        "MANIPULATION",
        "Opening range passes the manipulation threshold",
    ),
    (
        "RED_AND_MANIPULATION",
        "Red candle and manipulation threshold both pass",
    ),
    (
        "RED_MANIPULATION_MIN_8_RED",
        "Red/manipulation setup with at least 8 red minutes",
    ),
    (
        "RED_MANIPULATION_MIN_5_NEW_LOWS",
        "Red/manipulation setup with at least 5 new lows",
    ),
    (
        "RED_MANIPULATION_ATR_RATIO_0_30",
        "Red/manipulation setup with candle/ATR ratio >= 0.30",
    ),
)


def deterministic_control_ratio(
    date_str: str,
    symbol: str,
) -> float:
    """
    Return a reproducible non-Fibonacci target ratio.

    The value is constrained to 0.25-0.75 and kept away from
    0.382, 0.500, and 0.618.
    """
    digest = hashlib.sha256(
        f"{date_str}:{symbol}".encode("utf-8")
    ).hexdigest()

    raw = int(digest[:12], 16) / float(16**12 - 1)
    ratio = 0.25 + raw * 0.50

    forbidden = (0.382, 0.500, 0.618)

    if any(abs(ratio - value) < 0.035 for value in forbidden):
        ratio += 0.071

        if ratio > 0.75:
            ratio -= 0.142

    return round(ratio, 6)


def rule_passes(
    rule_name: str,
    *,
    red_candle: bool,
    manipulation_candle: bool,
    red_minutes: int,
    new_lows: int,
    candle_atr_ratio: float | None,
) -> bool:
    if rule_name == "ALL_COMPLETE":
        return True

    if rule_name == "RED_CANDLE":
        return red_candle

    if rule_name == "MANIPULATION":
        return manipulation_candle

    if rule_name == "RED_AND_MANIPULATION":
        return red_candle and manipulation_candle

    if rule_name == "RED_MANIPULATION_MIN_8_RED":
        return (
            red_candle
            and manipulation_candle
            and red_minutes >= 8
        )

    if rule_name == "RED_MANIPULATION_MIN_5_NEW_LOWS":
        return (
            red_candle
            and manipulation_candle
            and new_lows >= 5
        )

    if rule_name == "RED_MANIPULATION_ATR_RATIO_0_30":
        return (
            red_candle
            and manipulation_candle
            and candle_atr_ratio is not None
            and candle_atr_ratio >= 0.30
        )

    raise ValueError(f"Unknown Fibonacci rule: {rule_name}")


def _time_label(bar: dict[str, Any]) -> str:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    timestamp = datetime.fromisoformat(
        str(bar["t"]).replace("Z", "+00:00")
    )

    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(
            tzinfo=ZoneInfo("UTC")
        )

    return timestamp.astimezone(
        ZoneInfo("America/New_York")
    ).strftime("%H:%M")


def simulate_trade(
    *,
    bars: list[dict[str, Any]],
    entry_price: float,
    target_price: float,
    stop_price: float,
    slippage_bps: float,
    commission_per_share: float,
) -> dict[str, Any]:
    """
    Simulate a long limit-entry trade after 09:45 ET.

    If target and stop are touched in the same minute, the
    conservative stop outcome is used.
    """
    entered = False
    entry_time = ""

    for bar in bars:
        high = float(bar["h"])
        low = float(bar["l"])
        bar_time = _time_label(bar)

        if not entered:
            if low > entry_price:
                continue

            entered = True
            entry_time = bar_time

        target_hit = high >= target_price
        stop_hit = low <= stop_price

        if stop_hit:
            detail = (
                "Target and stop touched in the same minute; "
                "recorded conservatively as a loss."
                if target_hit
                else "Trading stop reached."
            )

            return _closed_trade(
                outcome="LOSS",
                entry_time=entry_time,
                exit_time=bar_time,
                entry_price=entry_price,
                exit_price=stop_price,
                exit_reason="STOP",
                detail=detail,
                slippage_bps=slippage_bps,
                commission_per_share=commission_per_share,
            )

        if target_hit:
            return _closed_trade(
                outcome="WIN",
                entry_time=entry_time,
                exit_time=bar_time,
                entry_price=entry_price,
                exit_price=target_price,
                exit_reason="TARGET",
                detail="Fibonacci target reached.",
                slippage_bps=slippage_bps,
                commission_per_share=commission_per_share,
            )

    if not entered:
        return {
            "outcome": "NO ENTRY",
            "entry_time": "",
            "exit_time": "",
            "exit_reason": "",
            "gross_return_pct": None,
            "net_return_pct": None,
            "detail": "Entry price was not reached after 09:45 ET.",
        }

    if not bars:
        return {
            "outcome": "UNRESOLVED",
            "entry_time": entry_time,
            "exit_time": "",
            "exit_reason": "",
            "gross_return_pct": None,
            "net_return_pct": None,
            "detail": "No post-opening bars were available.",
        }

    final_bar = bars[-1]
    final_price = float(final_bar["c"])

    result = _closed_trade(
        outcome="",
        entry_time=entry_time,
        exit_time=_time_label(final_bar),
        entry_price=entry_price,
        exit_price=final_price,
        exit_reason="EOD",
        detail="Closed at final available session price.",
        slippage_bps=slippage_bps,
        commission_per_share=commission_per_share,
    )

    result["outcome"] = (
        "WIN"
        if float(result["net_return_pct"]) >= 0
        else "LOSS"
    )

    return result


def _closed_trade(
    *,
    outcome: str,
    entry_time: str,
    exit_time: str,
    entry_price: float,
    exit_price: float,
    exit_reason: str,
    detail: str,
    slippage_bps: float,
    commission_per_share: float,
) -> dict[str, Any]:
    slippage_rate = slippage_bps / 10_000.0

    effective_entry = entry_price * (
        1.0 + slippage_rate
    )
    effective_exit = exit_price * (
        1.0 - slippage_rate
    )

    gross_return_pct = (
        (exit_price - entry_price) / entry_price
    ) * 100.0

    pnl_per_share = (
        effective_exit
        - effective_entry
        - commission_per_share * 2.0
    )

    net_return_pct = (
        pnl_per_share / effective_entry
    ) * 100.0

    return {
        "outcome": outcome,
        "entry_time": entry_time,
        "exit_time": exit_time,
        "exit_reason": exit_reason,
        "gross_return_pct": round(
            gross_return_pct,
            6,
        ),
        "net_return_pct": round(
            net_return_pct,
            6,
        ),
        "detail": detail,
    }


def _maximum_drawdown(
    returns: list[float],
) -> float:
    running_total = 0.0
    peak = 0.0
    maximum = 0.0

    for value in returns:
        running_total += value
        peak = max(peak, running_total)
        maximum = max(
            maximum,
            peak - running_total,
        )

    return maximum


def metrics_for(
    records: list[FibonacciResearchRecord],
) -> FibonacciMetrics:
    eligible = [
        record
        for record in records
        if record.setup_eligible
    ]

    entered = [
        record
        for record in eligible
        if record.outcome in {"WIN", "LOSS"}
    ]

    wins = sum(
        record.outcome == "WIN"
        for record in entered
    )
    losses = sum(
        record.outcome == "LOSS"
        for record in entered
    )
    no_entry = sum(
        record.outcome == "NO ENTRY"
        for record in eligible
    )

    returns = [
        float(record.net_return_pct)
        for record in entered
        if record.net_return_pct is not None
    ]

    positive = sum(
        value
        for value in returns
        if value > 0
    )
    negative = abs(
        sum(
            value
            for value in returns
            if value < 0
        )
    )

    return FibonacciMetrics(
        observations=len(records),
        eligible_setups=len(eligible),
        entries=len(entered),
        wins=wins,
        losses=losses,
        no_entry=no_entry,
        win_rate_pct=(
            wins / len(entered) * 100.0
            if entered
            else None
        ),
        average_return_pct=(
            sum(returns) / len(returns)
            if returns
            else None
        ),
        total_return_pct=sum(returns),
        profit_factor=(
            positive / negative
            if negative
            else None
        ),
        expectancy_pct=(
            sum(returns) / len(entered)
            if entered
            else None
        ),
        maximum_drawdown_pct_points=(
            _maximum_drawdown(returns)
        ),
    )


class FibonacciResearchReport:
    def __init__(
        self,
        *,
        start_date: str,
        end_date: str,
        data_feed: str,
        slippage_bps: float,
        commission_per_share: float,
    ) -> None:
        self.start_date = start_date
        self.end_date = end_date
        self.data_feed = data_feed
        self.slippage_bps = slippage_bps
        self.commission_per_share = (
            commission_per_share
        )

        self.records: list[
            FibonacciResearchRecord
        ] = []

        self.failed_sessions: list[
            tuple[str, str]
        ] = []

    def add_failure(
        self,
        date_str: str,
        error: Exception,
    ) -> None:
        self.failed_sessions.append(
            (date_str, str(error))
        )

    def add_stock(
        self,
        *,
        date_str: str,
        symbol: str,
        stock,
        bars_processed: int,
        outcome_bars: list[dict[str, Any]],
    ) -> None:
        opening_bar = stock.opening_bar
        atr = stock.atr

        if opening_bar is None or atr in {None, 0}:
            return

        opening_open = float(opening_bar["o"])
        opening_high = float(opening_bar["h"])
        opening_low = float(opening_bar["l"])
        opening_close = float(opening_bar["c"])
        opening_range = opening_high - opening_low

        candle_atr_ratio = (
            opening_range / float(atr)
            if atr
            else None
        )

        targets = dict(FIBONACCI_TARGETS)
        targets["NON_FIB_CONTROL"] = (
            deterministic_control_ratio(
                date_str,
                symbol,
            )
        )

        risk_distance = max(
            opening_range * 0.191,
            0.01,
        )
        entry_price = opening_low
        stop_price = entry_price - risk_distance

        for rule_name, rule_description in RULES:
            eligible = rule_passes(
                rule_name,
                red_candle=bool(stock.is_red),
                manipulation_candle=bool(
                    stock.is_manipulation
                ),
                red_minutes=int(stock.red_minutes),
                new_lows=int(stock.new_lows),
                candle_atr_ratio=candle_atr_ratio,
            )

            for target_name, target_ratio in targets.items():
                target_price = (
                    entry_price
                    + opening_range * target_ratio
                )

                reward = target_price - entry_price
                risk = entry_price - stop_price

                reward_risk = (
                    reward / risk
                    if risk > 0
                    else None
                )

                if eligible:
                    result = simulate_trade(
                        bars=outcome_bars,
                        entry_price=entry_price,
                        target_price=target_price,
                        stop_price=stop_price,
                        slippage_bps=self.slippage_bps,
                        commission_per_share=(
                            self.commission_per_share
                        ),
                    )
                else:
                    result = {
                        "outcome": "FILTERED",
                        "entry_time": "",
                        "exit_time": "",
                        "exit_reason": "",
                        "gross_return_pct": None,
                        "net_return_pct": None,
                        "detail": (
                            "Setup did not pass this rule."
                        ),
                    }

                self.records.append(
                    FibonacciResearchRecord(
                        date=date_str,
                        symbol=symbol,
                        data_feed=self.data_feed,
                        target_variant=target_name,
                        target_ratio=round(
                            target_ratio,
                            6,
                        ),
                        rule_variant=rule_name,
                        rule_description=rule_description,
                        setup_eligible=eligible,
                        bars_processed=bars_processed,
                        opening_open=opening_open,
                        opening_high=opening_high,
                        opening_low=opening_low,
                        opening_close=opening_close,
                        opening_range=opening_range,
                        opening_volume=(
                            float(opening_bar["v"])
                            if "v" in opening_bar
                            else None
                        ),
                        atr=float(atr),
                        candle_atr_ratio=(
                            candle_atr_ratio
                        ),
                        red_candle=bool(stock.is_red),
                        manipulation_candle=bool(
                            stock.is_manipulation
                        ),
                        red_minutes=int(
                            stock.red_minutes
                        ),
                        green_minutes=int(
                            stock.green_minutes
                        ),
                        new_lows=int(stock.new_lows),
                        new_highs=int(stock.new_highs),
                        entry_price=entry_price,
                        target_price=target_price,
                        stop_price=stop_price,
                        reward_risk=reward_risk,
                        outcome=str(result["outcome"]),
                        entry_time=str(
                            result["entry_time"]
                        ),
                        exit_time=str(
                            result["exit_time"]
                        ),
                        exit_reason=str(
                            result["exit_reason"]
                        ),
                        gross_return_pct=(
                            result["gross_return_pct"]
                        ),
                        net_return_pct=(
                            result["net_return_pct"]
                        ),
                        detail=str(result["detail"]),
                    )
                )

    def summary_rows(
        self,
    ) -> list[dict[str, Any]]:
        groups: dict[
            tuple[str, str],
            list[FibonacciResearchRecord],
        ] = {}

        for record in self.records:
            key = (
                record.rule_variant,
                record.target_variant,
            )
            groups.setdefault(key, []).append(record)

        rows = []

        for key in sorted(groups):
            rule_name, target_name = key
            records = groups[key]
            metrics = metrics_for(records)

            rows.append(
                {
                    "rule_variant": rule_name,
                    "rule_description": (
                        records[0].rule_description
                    ),
                    "target_variant": target_name,
                    "target_ratio": (
                        records[0].target_ratio
                    ),
                    **asdict(metrics),
                }
            )

        return rows

    def symbol_rows(
        self,
    ) -> list[dict[str, Any]]:
        groups: dict[
            tuple[str, str, str],
            list[FibonacciResearchRecord],
        ] = {}

        for record in self.records:
            key = (
                record.symbol,
                record.rule_variant,
                record.target_variant,
            )
            groups.setdefault(key, []).append(record)

        rows = []

        for key in sorted(groups):
            symbol, rule_name, target_name = key
            records = groups[key]
            metrics = metrics_for(records)

            rows.append(
                {
                    "symbol": symbol,
                    "rule_variant": rule_name,
                    "target_variant": target_name,
                    "target_ratio": (
                        records[0].target_ratio
                    ),
                    **asdict(metrics),
                }
            )

        return rows

    def best_rows(
        self,
        minimum_entries: int = 20,
    ) -> list[dict[str, Any]]:
        rows = [
            row
            for row in self.summary_rows()
            if (
                row["entries"] >= minimum_entries
                and row["profit_factor"] is not None
            )
        ]

        return sorted(
            rows,
            key=lambda row: (
                row["profit_factor"],
                row["expectancy_pct"]
                if row["expectancy_pct"] is not None
                else -math.inf,
                row["total_return_pct"],
            ),
            reverse=True,
        )

    def print_summary(self) -> None:
        print()
        print("===== FIBONACCI RESEARCH REPORT =====")
        print(
            f"Date range: {self.start_date} "
            f"to {self.end_date}"
        )
        print(f"Data feed: {self.data_feed.upper()}")
        print(
            "READ-ONLY MODE: Google Sheets, dashboard, "
            "Webull, and order workflows are disabled."
        )
        print(
            f"Research records: {len(self.records)}"
        )
        print(
            f"Failed sessions: {len(self.failed_sessions)}"
        )

        best = self.best_rows()

        print()
        print(
            "Top rule/target combinations "
            "(minimum 20 entries):"
        )
        print(
            "Rule | Target | Entries | Win rate | "
            "Profit factor | Expectancy | Drawdown"
        )

        for row in best[:15]:
            win_rate = (
                f"{row['win_rate_pct']:.2f}%"
                if row["win_rate_pct"] is not None
                else "N/A"
            )
            profit_factor = (
                f"{row['profit_factor']:.3f}"
                if row["profit_factor"] is not None
                else "N/A"
            )
            expectancy = (
                f"{row['expectancy_pct']:.4f}%"
                if row["expectancy_pct"] is not None
                else "N/A"
            )

            print(
                f"{row['rule_variant']} | "
                f"{row['target_variant']} | "
                f"{row['entries']} | "
                f"{win_rate} | "
                f"{profit_factor} | "
                f"{expectancy} | "
                f"{row['maximum_drawdown_pct_points']:.4f}"
            )

    def write_csv(
        self,
        output_directory: str | Path,
    ) -> tuple[Path, Path, Path, Path]:
        output_directory = Path(output_directory)
        output_directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        stem = (
            f"fibonacci_{self.start_date}_to_"
            f"{self.end_date}"
        )

        detail_path = (
            output_directory / f"{stem}_details.csv"
        )
        summary_path = (
            output_directory / f"{stem}_rules.csv"
        )
        symbol_path = (
            output_directory / f"{stem}_symbols.csv"
        )
        failure_path = (
            output_directory / f"{stem}_failures.csv"
        )

        detail_fields = [
            field.name
            for field in (
                FibonacciResearchRecord
                .__dataclass_fields__
                .values()
            )
        ]

        with detail_path.open(
            "w",
            newline="",
            encoding="utf-8",
        ) as file:
            writer = csv.DictWriter(
                file,
                fieldnames=detail_fields,
            )
            writer.writeheader()
            writer.writerows(
                asdict(record)
                for record in self.records
            )

        summary_rows = self.summary_rows()
        if summary_rows:
            with summary_path.open(
                "w",
                newline="",
                encoding="utf-8",
            ) as file:
                writer = csv.DictWriter(
                    file,
                    fieldnames=list(
                        summary_rows[0].keys()
                    ),
                )
                writer.writeheader()
                writer.writerows(summary_rows)

        symbol_rows = self.symbol_rows()
        if symbol_rows:
            with symbol_path.open(
                "w",
                newline="",
                encoding="utf-8",
            ) as file:
                writer = csv.DictWriter(
                    file,
                    fieldnames=list(
                        symbol_rows[0].keys()
                    ),
                )
                writer.writeheader()
                writer.writerows(symbol_rows)

        with failure_path.open(
            "w",
            newline="",
            encoding="utf-8",
        ) as file:
            writer = csv.DictWriter(
                file,
                fieldnames=["date", "error"],
            )
            writer.writeheader()
            writer.writerows(
                {
                    "date": date_str,
                    "error": error,
                }
                for date_str, error in self.failed_sessions
            )

        return (
            detail_path,
            summary_path,
            symbol_path,
            failure_path,
        )
