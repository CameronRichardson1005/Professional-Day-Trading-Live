from __future__ import annotations

import csv

from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .models import Stock
from .config import MARKET_DATA_FEED
from .market_calendar import nyse_trading_dates

if TYPE_CHECKING:
    from .replay import ReplaySummary


@dataclass(frozen=True)
class ReplaySession:
    date: str
    stocks: dict[str, Stock]
    summary: ReplaySummary


@dataclass(frozen=True)
class BacktestRecord:
    date: str
    symbol: str
    data_feed: str
    bars_processed: int
    missing_bars: int
    missing_timestamps: str
    missing_bar_classification: str
    atr_available: bool
    atr_status: str
    atr_daily_bars: int
    green_minutes: int
    red_minutes: int
    new_highs: int
    new_lows: int
    candle_range: float | None
    atr: float | None
    candle_atr_ratio: float | None
    is_manipulation: bool
    is_red: bool
    signal: str
    outcome: str
    entry_price: float | None
    exit_price: float | None
    stop_loss: float | None
    trading_stop_loss: float | None
    pnl_per_share: float | None
    return_pct: float | None
    gross_pnl_per_share: float | None
    costs_per_share: float | None
    exit_reason: str
    spy_regime: str
    qqq_regime: str
    detail: str

    @classmethod
    def from_stock(
            cls,
            date_str: str,
            stock: Stock,
            summary: ReplaySummary,
    ) -> "BacktestRecord":
        outcome: dict[str, Any] = stock.outcome or {}
        missing_timestamps = (
            summary.missing_timestamps.get(
                stock.symbol,
                [],
            )
        )
        candle_range = _optional_float(
            stock.candle_range
        )
        atr = _optional_float(stock.atr)
        atr_diagnostic = summary.atr_diagnostics.get(
            stock.symbol,
            {},
        )

        return cls(
            date=date_str,
            symbol=stock.symbol,
            data_feed=summary.data_feed,
            bars_processed=int(
                summary.processed_bars.get(
                    stock.symbol,
                    0,
                )
            ),
            missing_bars=int(
                summary.missing_bars.get(
                    stock.symbol,
                    15,
                )
            ),
            missing_timestamps="; ".join(
                missing_timestamps
            ),
            missing_bar_classification=(
                summary.missing_bar_classification.get(
                    stock.symbol,
                    (
                        (
                            "NO_VALID_"
                            f"{summary.data_feed.upper()}"
                            "_BAR_RETURNED"
                        )
                        if missing_timestamps
                        else "COMPLETE"
                    ),
                )
            ),
            atr_available=stock.atr is not None,
            atr_status=str(
                atr_diagnostic.get(
                    "status",
                    (
                        "AVAILABLE"
                        if stock.atr is not None
                        else "UNAVAILABLE"
                    ),
                )
            ),
            atr_daily_bars=int(
                atr_diagnostic.get(
                    "valid_daily_bars",
                    0,
                )
            ),
            green_minutes=stock.green_minutes,
            red_minutes=stock.red_minutes,
            new_highs=stock.new_highs,
            new_lows=stock.new_lows,
            candle_range=candle_range,
            atr=atr,
            candle_atr_ratio=(
                candle_range / atr
                if (
                    candle_range is not None
                    and atr not in {None, 0.0}
                )
                else None
            ),
            is_manipulation=stock.is_manipulation,
            is_red=stock.is_red,
            signal=stock.signal,
            outcome=str(
                outcome.get("status", "")
            ),
            entry_price=_optional_float(
                outcome.get("entryPrice")
            ),
            exit_price=_optional_float(
                outcome.get("exitPrice")
            ),
            stop_loss=_optional_float(
                stock.stop_loss
            ),
            trading_stop_loss=_optional_float(
                stock.trading_stop_loss
            ),
            pnl_per_share=_optional_float(
                outcome.get("pnlPerShare")
            ),
            return_pct=_optional_float(
                outcome.get("returnPct")
            ),
            gross_pnl_per_share=_optional_float(
                outcome.get("grossPnlPerShare")
            ),
            costs_per_share=_optional_float(
                outcome.get("costsPerShare")
            ),
            exit_reason=str(
                outcome.get("exitReason", "")
            ),
            spy_regime=summary.market_regimes.get(
                "SPY",
                "UNAVAILABLE",
            ),
            qqq_regime=summary.market_regimes.get(
                "QQQ",
                "UNAVAILABLE",
            ),
            detail=str(
                outcome.get("detail", "")
            ),
        )


@dataclass(frozen=True)
class BacktestMetrics:
    ticker_days: int
    invest_signals: int
    wins: int
    losses: int
    unresolved: int
    no_entry: int
    closed_trades: int
    win_rate_pct: float | None
    average_return_pct: float | None
    total_return_pct: float
    profit_factor: float | None
    max_drawdown_pct_points: float
    missing_bars: int
    incomplete_ticker_days: int
    atr_unavailable_ticker_days: int


class BacktestReport:
    def __init__(
            self,
            start_date: str,
            end_date: str,
        data_feed: str = MARKET_DATA_FEED,
        slippage_bps: float = 0.0,
        commission_per_share: float = 0.0,
        train_fraction: float = 0.70,
    ) -> None:
        self.start_date = start_date
        self.end_date = end_date
        self.data_feed = data_feed
        self.slippage_bps = slippage_bps
        self.commission_per_share = (
            commission_per_share
        )
        self.train_fraction = train_fraction
        self.records: list[BacktestRecord] = []
        self.failed_sessions: list[
            tuple[str, str]
        ] = []

    def add_session(
            self,
            session: ReplaySession,
    ) -> None:
        for stock in session.stocks.values():
            self.records.append(
                BacktestRecord.from_stock(
                    date_str=session.date,
                    stock=stock,
                    summary=session.summary,
                )
            )

    def add_failure(
            self,
            date_str: str,
            error: Exception,
    ) -> None:
        self.failed_sessions.append(
            (date_str, str(error))
        )

    @staticmethod
    def metrics_for(
            records: list[BacktestRecord],
    ) -> BacktestMetrics:
        invest_records = [
            record
            for record in records
            if record.signal == "INVEST"
        ]

        wins = sum(
            record.outcome == "WIN"
            for record in invest_records
        )
        losses = sum(
            record.outcome == "LOSS"
            for record in invest_records
        )
        unresolved = sum(
            record.outcome == "STILL OPEN"
            for record in invest_records
        )
        no_entry = sum(
            record.outcome == "NO ENTRY"
            for record in invest_records
        )

        returns = [
            float(record.return_pct)
            for record in invest_records
            if record.return_pct is not None
        ]

        positive_returns = sum(
            value
            for value in returns
            if value > 0
        )
        negative_returns = abs(
            sum(
                value
                for value in returns
                if value < 0
            )
        )

        closed_trades = wins + losses
        win_rate = (
            wins / closed_trades * 100.0
            if closed_trades
            else None
        )
        average_return = (
            sum(returns) / len(returns)
            if returns
            else None
        )
        profit_factor = (
            positive_returns / negative_returns
            if negative_returns
            else None
        )

        return BacktestMetrics(
            ticker_days=len(records),
            invest_signals=len(invest_records),
            wins=wins,
            losses=losses,
            unresolved=unresolved,
            no_entry=no_entry,
            closed_trades=closed_trades,
            win_rate_pct=win_rate,
            average_return_pct=average_return,
            total_return_pct=sum(returns),
            profit_factor=profit_factor,
            max_drawdown_pct_points=(
                _maximum_drawdown(returns)
            ),
            missing_bars=sum(
                record.missing_bars
                for record in records
            ),
            incomplete_ticker_days=sum(
                record.bars_processed < 15
                for record in records
            ),
            atr_unavailable_ticker_days=sum(
                record.bars_processed == 15
                and not record.atr_available
                for record in records
            ),
        )

    def overall_metrics(self) -> BacktestMetrics:
        return self.metrics_for(self.records)

    def metrics_by_symbol(
            self,
    ) -> dict[str, BacktestMetrics]:
        symbols = sorted({
            record.symbol
            for record in self.records
        })

        return {
            symbol: self.metrics_for([
                record
                for record in self.records
                if record.symbol == symbol
            ])
            for symbol in symbols
        }

    def robustness_comparisons(
            self,
    ) -> list[dict[str, Any]]:
        """
        Compare stricter, read-only filters against the
        existing INVEST signals. These are diagnostics, not
        automatic strategy changes.
        """
        return self._comparison_rows(self.records)

    def _comparison_rows(
            self,
            source_records: list[BacktestRecord],
    ) -> list[dict[str, Any]]:
        baseline = [
            record
            for record in source_records
            if record.signal == "INVEST"
        ]
        comparisons: list[
            tuple[str, str, list[BacktestRecord]]
        ] = [
            (
                "BASELINE",
                "Current INVEST rule",
                baseline,
            )
        ]

        for symbol in sorted({
            record.symbol
            for record in baseline
        }):
            comparisons.append((
                f"EXCLUDE_{symbol}",
                f"Current rule excluding {symbol}",
                [
                    record
                    for record in baseline
                    if record.symbol != symbol
                ],
            ))

        for minimum in (8, 9, 10):
            comparisons.append((
                f"MIN_RED_MINUTES_{minimum}",
                (
                    "Current rule plus at least "
                    f"{minimum} red opening minutes"
                ),
                [
                    record
                    for record in baseline
                    if record.red_minutes >= minimum
                ],
            ))

        for minimum in (3, 4, 5):
            comparisons.append((
                f"MIN_NEW_LOWS_{minimum}",
                (
                    "Current rule plus at least "
                    f"{minimum} new opening lows"
                ),
                [
                    record
                    for record in baseline
                    if record.new_lows >= minimum
                ],
            ))

        for minimum in (0.30, 0.35, 0.40, 0.50):
            comparisons.append((
                f"MIN_CANDLE_ATR_RATIO_{minimum:.2f}",
                (
                    "Current rule plus candle/ATR ratio "
                    f">= {minimum:.2f}"
                ),
                [
                    record
                    for record in baseline
                    if (
                        record.candle_atr_ratio is not None
                        and record.candle_atr_ratio >= minimum
                    )
                ],
            ))

        combined = [
            record
            for record in baseline
            if (
                record.symbol not in {"RGTI", "PLTR"}
                and record.candle_atr_ratio is not None
                and record.candle_atr_ratio >= 0.30
            )
        ]
        comparisons.extend([
            (
                "EXCLUDE_RGTI_PLTR",
                "Current rule excluding RGTI and PLTR",
                [
                    record
                    for record in baseline
                    if record.symbol not in {"RGTI", "PLTR"}
                ],
            ),
            (
                (
                    "EXCLUDE_RGTI_PLTR_"
                    "MIN_CANDLE_ATR_RATIO_0.30"
                ),
                (
                    "Exclude RGTI/PLTR plus candle/ATR "
                    "ratio >= 0.30"
                ),
                combined,
            ),
            (
                (
                    "EXCLUDE_RGTI_PLTR_"
                    "MIN_CANDLE_ATR_RATIO_0.30_"
                    "MIN_NEW_LOWS_5"
                ),
                (
                    "Exclude RGTI/PLTR, candle/ATR ratio "
                    ">= 0.30, and at least 5 new lows"
                ),
                [
                    record
                    for record in combined
                    if record.new_lows >= 5
                ],
            ),
        ])

        for benchmark, attribute in (
            ("SPY", "spy_regime"),
            ("QQQ", "qqq_regime"),
        ):
            for regime in ("BULL", "BEAR"):
                comparisons.append((
                    f"{benchmark}_{regime}",
                    (
                        "Current rule when prior-session "
                        f"{benchmark} close is {regime.lower()} "
                        "versus its 20-day SMA"
                    ),
                    [
                        record
                        for record in baseline
                        if getattr(record, attribute) == regime
                    ],
                ))

        rows = []
        for name, rule, records in comparisons:
            metrics = self.metrics_for(records)
            rows.append({
                "variant": name,
                "rule": rule,
                **asdict(metrics),
            })

        return rows

    def chronological_split_rows(
            self,
    ) -> list[dict[str, Any]]:
        dates = sorted({
            record.date
            for record in self.records
        })
        if len(dates) < 2:
            return []

        split_index = min(
            len(dates) - 1,
            max(1, int(len(dates) * self.train_fraction)),
        )
        train_dates = set(dates[:split_index])
        test_dates = set(dates[split_index:])
        rows = []

        for split_name, selected_dates in (
            ("TRAIN", train_dates),
            ("TEST", test_dates),
        ):
            split_records = [
                record
                for record in self.records
                if record.date in selected_dates
            ]
            for row in self._comparison_rows(split_records):
                rows.append({
                    "split": split_name,
                    "split_start": min(selected_dates),
                    "split_end": max(selected_dates),
                    **row,
                })

        train_rows = [
            row
            for row in rows
            if (
                row["split"] == "TRAIN"
                and row["closed_trades"] >= 20
                and row["profit_factor"] is not None
            )
        ]
        selected_variant = (
            max(
                train_rows,
                key=lambda row: (
                    row["profit_factor"],
                    row["total_return_pct"],
                ),
            )["variant"]
            if train_rows
            else "BASELINE"
        )
        for row in rows:
            row["selected_on_training"] = (
                row["variant"] == selected_variant
            )
        return rows

    def print_summary(self) -> None:
        metrics = self.overall_metrics()

        print()
        print("===== MULTI-DAY BACKTEST REPORT =====")
        print(
            f"Date range: {self.start_date} "
            f"to {self.end_date}"
        )
        print(f"Market-data feed: {self.data_feed.upper()}")
        print(
            "Execution assumptions: "
            f"{self.slippage_bps:.2f} bps slippage per side, "
            f"${self.commission_per_share:.4f} commission "
            "per share per side"
        )
        print(
            "Read-only mode: no spreadsheets or "
            "orders were created."
        )
        print(
            f"Ticker-days analysed: "
            f"{metrics.ticker_days}"
        )
        print(
            f"INVEST signals: {metrics.invest_signals}"
        )
        print(
            "Outcomes: "
            f"{metrics.wins} wins, "
            f"{metrics.losses} losses, "
            f"{metrics.unresolved} unresolved, "
            f"{metrics.no_entry} no entry"
        )
        print(
            "Win rate: "
            f"{_format_percentage(metrics.win_rate_pct)}"
        )
        print(
            "Average closed return: "
            f"{_format_percentage(metrics.average_return_pct)}"
        )
        print(
            "Total equal-weight return: "
            f"{metrics.total_return_pct:.2f}%"
        )
        print(
            "Profit factor: "
            f"{_format_ratio(metrics.profit_factor, metrics.wins)}"
        )
        print(
            "Maximum drawdown: "
            f"{metrics.max_drawdown_pct_points:.2f} "
            "percentage points"
        )
        print(
            "Data quality: "
            f"{metrics.missing_bars} missing opening bars, "
            f"{metrics.incomplete_ticker_days} incomplete "
            "ticker-days, "
            f"{metrics.atr_unavailable_ticker_days} "
            "ATR-unavailable ticker-days"
        )
        print(
            f"Failed sessions: "
            f"{len(self.failed_sessions)}"
        )

        print()
        print("By ticker:")
        print(
            "Symbol | Signals | W-L-U-N | "
            "Win rate | Total return"
        )

        for symbol, ticker in (
            self.metrics_by_symbol().items()
        ):
            print(
                f"{symbol} | {ticker.invest_signals} | "
                f"{ticker.wins}-{ticker.losses}-"
                f"{ticker.unresolved}-{ticker.no_entry} | "
                f"{_format_percentage(ticker.win_rate_pct)} | "
                f"{ticker.total_return_pct:.2f}%"
            )

        if self.failed_sessions:
            print()
            print("Failed dates:")
            for date_str, error in self.failed_sessions:
                print(f"{date_str}: {error}")

    def write_csv(
            self,
            output_directory: str | Path,
    ) -> tuple[Path, Path, Path, Path, Path, Path]:
        output_directory = Path(output_directory)
        output_directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        stem = (
            f"backtest_{self.start_date}_to_"
            f"{self.end_date}"
        )
        detail_path = (
            output_directory / f"{stem}_details.csv"
        )
        summary_path = (
            output_directory / f"{stem}_summary.csv"
        )
        missing_path = (
            output_directory
            / f"{stem}_missing_bars.csv"
        )
        robustness_path = (
            output_directory
            / f"{stem}_robustness.csv"
        )
        atr_path = (
            output_directory
            / f"{stem}_atr_diagnostics.csv"
        )
        split_path = (
            output_directory
            / f"{stem}_train_test.csv"
        )

        detail_fields = [
            field.name
            for field in BacktestRecord.__dataclass_fields__.values()
        ]

        with detail_path.open(
            "w",
            newline="",
            encoding="utf-8",
        ) as detail_file:
            writer = csv.DictWriter(
                detail_file,
                fieldnames=detail_fields,
            )
            writer.writeheader()
            writer.writerows(
                asdict(record)
                for record in self.records
            )

        summary_rows = [
            {
                "scope": "OVERALL",
                "symbol": "",
                "data_feed": self.data_feed,
                "slippage_bps": self.slippage_bps,
                "commission_per_share": (
                    self.commission_per_share
                ),
                **asdict(self.overall_metrics()),
            }
        ]
        summary_rows.extend(
            {
                "scope": "TICKER",
                "symbol": symbol,
                "data_feed": self.data_feed,
                "slippage_bps": self.slippage_bps,
                "commission_per_share": (
                    self.commission_per_share
                ),
                **asdict(metrics),
            }
            for symbol, metrics in (
                self.metrics_by_symbol().items()
            )
        )

        summary_fields = list(
            summary_rows[0].keys()
        )
        summary_fields.extend([
            "failed_sessions",
            "failed_session_details",
        ])

        for row in summary_rows:
            row["failed_sessions"] = (
                len(self.failed_sessions)
                if row["scope"] == "OVERALL"
                else ""
            )
            row["failed_session_details"] = (
                "; ".join(
                    f"{date_str}: {error}"
                    for date_str, error
                    in self.failed_sessions
                )
                if row["scope"] == "OVERALL"
                else ""
            )

        with summary_path.open(
            "w",
            newline="",
            encoding="utf-8",
        ) as summary_file:
            writer = csv.DictWriter(
                summary_file,
                fieldnames=summary_fields,
            )
            writer.writeheader()
            writer.writerows(summary_rows)

        missing_fields = [
            "date",
            "symbol",
            "data_feed",
            "missing_timestamp",
            "classification",
            "interpretation",
        ]
        with missing_path.open(
            "w",
            newline="",
            encoding="utf-8",
        ) as missing_file:
            writer = csv.DictWriter(
                missing_file,
                fieldnames=missing_fields,
            )
            writer.writeheader()

            for record in self.records:
                for timestamp in filter(
                    None,
                    record.missing_timestamps.split("; "),
                ):
                    writer.writerow({
                        "date": record.date,
                        "symbol": record.symbol,
                        "data_feed": record.data_feed,
                        "missing_timestamp": timestamp,
                        "classification": (
                            record
                            .missing_bar_classification
                        ),
                        "interpretation": (
                            "The paginated request completed "
                            "successfully, but Alpaca returned "
                            "no valid aggregate bar for this "
                            "symbol, feed, and minute. This is "
                            "not a request-level API retrieval "
                            "failure."
                        ),
                    })

        robustness_rows = (
            self.robustness_comparisons()
        )
        robustness_fields = list(
            robustness_rows[0].keys()
        )
        with robustness_path.open(
            "w",
            newline="",
            encoding="utf-8",
        ) as robustness_file:
            writer = csv.DictWriter(
                robustness_file,
                fieldnames=robustness_fields,
            )
            writer.writeheader()
            writer.writerows(robustness_rows)

        atr_fields = [
            "date",
            "symbol",
            "data_feed",
            "atr_available",
            "atr_status",
            "valid_daily_bars",
            "atr",
        ]
        with atr_path.open(
            "w",
            newline="",
            encoding="utf-8",
        ) as atr_file:
            writer = csv.DictWriter(
                atr_file,
                fieldnames=atr_fields,
            )
            writer.writeheader()
            for record in self.records:
                writer.writerow({
                    "date": record.date,
                    "symbol": record.symbol,
                    "data_feed": record.data_feed,
                    "atr_available": record.atr_available,
                    "atr_status": record.atr_status,
                    "valid_daily_bars": (
                        record.atr_daily_bars
                    ),
                    "atr": record.atr,
                })

        split_rows = self.chronological_split_rows()
        with split_path.open(
            "w",
            newline="",
            encoding="utf-8",
        ) as split_file:
            if split_rows:
                writer = csv.DictWriter(
                    split_file,
                    fieldnames=list(split_rows[0].keys()),
                )
                writer.writeheader()
                writer.writerows(split_rows)

        return (
            detail_path,
            summary_path,
            missing_path,
            robustness_path,
            atr_path,
            split_path,
        )


def weekday_dates(
        start_date: date,
        end_date: date,
) -> list[date]:
    return nyse_trading_dates(start_date, end_date)


def market_regimes_by_date(
        bars_by_symbol: dict[str, list[dict]],
        trading_dates: list[date],
        lookback: int = 20,
) -> dict[str, dict[str, str]]:
    regimes = {
        trading_date.isoformat(): {
            "SPY": "UNAVAILABLE",
            "QQQ": "UNAVAILABLE",
        }
        for trading_date in trading_dates
    }

    for symbol in ("SPY", "QQQ"):
        closes = []
        for bar in sorted(
            bars_by_symbol.get(symbol, []),
            key=lambda item: str(item["t"]),
        ):
            bar_date = str(bar["t"])[:10]
            closes.append(
                (bar_date, float(bar["c"]))
            )

        for trading_date in trading_dates:
            date_str = trading_date.isoformat()
            prior = [
                close
                for bar_date, close in closes
                if bar_date < date_str
            ]
            if len(prior) < lookback:
                continue
            moving_average = (
                sum(prior[-lookback:]) / lookback
            )
            regimes[date_str][symbol] = (
                "BULL"
                if prior[-1] >= moving_average
                else "BEAR"
            )

    return regimes


def _optional_float(
        value: Any,
) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _maximum_drawdown(
        returns: list[float],
) -> float:
    cumulative = 0.0
    peak = 0.0
    maximum = 0.0

    for value in returns:
        cumulative += value
        peak = max(peak, cumulative)
        maximum = max(
            maximum,
            peak - cumulative,
        )

    return maximum


def _format_percentage(
        value: float | None,
) -> str:
    if value is None:
        return "N/A"
    return f"{value:.2f}%"


def _format_ratio(
        value: float | None,
        wins: int,
) -> str:
    if value is not None:
        return f"{value:.2f}"
    if wins:
        return "infinite (no closed losses)"
    return "N/A"
