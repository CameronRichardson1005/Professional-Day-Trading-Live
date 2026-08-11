from __future__ import annotations

from dataclasses import asdict, dataclass

from .webull_paper_analytics import (
    WebullPaperAnalyticsGroup,
    WebullPaperAnalyticsReport,
    load_webull_paper_analytics,
)


@dataclass(frozen=True)
class FibonacciPaperFinding:
    dimension: str
    key: str
    closed_trades: int
    win_rate_pct: float | None
    expectancy_per_trade: float | None
    average_return_pct: float | None
    realized_pnl: float
    sample_label: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class FibonacciPaperEvaluation:
    total_orders: int
    closed_trades: int

    evidence_status: str
    evidence_message: str
    parameter_changes_allowed: bool

    strongest_cohort: FibonacciPaperFinding | None
    weakest_cohort: FibonacciPaperFinding | None

    symbol_findings: tuple[FibonacciPaperFinding, ...]
    entry_time_findings: tuple[FibonacciPaperFinding, ...]
    reward_risk_findings: tuple[FibonacciPaperFinding, ...]
    impulse_atr_findings: tuple[FibonacciPaperFinding, ...]
    pullback_volume_findings: tuple[FibonacciPaperFinding, ...]
    confirmation_time_findings: tuple[FibonacciPaperFinding, ...]

    simulation_only: bool = True
    broker_submitted: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


def _evidence_status(
    closed_trades: int,
) -> tuple[str, str]:
    if closed_trades == 0:
        return (
            "NO DATA",
            (
                "No closed simulated paper trades are available. "
                "No performance conclusion should be drawn."
            ),
        )

    if closed_trades < 5:
        return (
            "VERY EARLY",
            (
                "Fewer than 5 closed trades are available. "
                "Results are descriptive only."
            ),
        )

    if closed_trades < 20:
        return (
            "EARLY",
            (
                "Fewer than 20 closed trades are available. "
                "Apparent differences may be sample noise."
            ),
        )

    if closed_trades < 50:
        return (
            "DEVELOPING",
            (
                "The sample is developing, but strategy parameter "
                "changes should still require broader validation."
            ),
        )

    return (
        "REVIEWABLE",
        (
            "At least 50 closed simulated trades are available. "
            "Results may be reviewed for research, but parameter "
            "changes still require separate validation."
        ),
    )


def _finding(
    *,
    dimension: str,
    group: WebullPaperAnalyticsGroup,
) -> FibonacciPaperFinding:
    return FibonacciPaperFinding(
        dimension=dimension,
        key=group.key,
        closed_trades=group.closed_trades,
        win_rate_pct=group.win_rate_pct,
        expectancy_per_trade=group.expectancy_per_trade,
        average_return_pct=group.average_return_pct,
        realized_pnl=group.realized_pnl,
        sample_label=group.sample_label,
    )


def _findings(
    *,
    dimension: str,
    groups: tuple[WebullPaperAnalyticsGroup, ...],
) -> tuple[FibonacciPaperFinding, ...]:
    return tuple(
        _finding(
            dimension=dimension,
            group=group,
        )
        for group in groups
    )


def _eligible_for_ranking(
    finding: FibonacciPaperFinding,
) -> bool:
    return (
        finding.closed_trades >= 5
        and finding.expectancy_per_trade is not None
    )


def build_fibonacci_paper_evaluation(
    *,
    analytics: WebullPaperAnalyticsReport,
) -> FibonacciPaperEvaluation:
    evidence_status, evidence_message = (
        _evidence_status(
            analytics.closed_trades
        )
    )

    symbol_findings = _findings(
        dimension="SYMBOL",
        groups=analytics.by_symbol,
    )

    entry_time_findings = _findings(
        dimension="ENTRY TIME",
        groups=analytics.by_entry_time,
    )

    reward_risk_findings = _findings(
        dimension="REWARD/RISK",
        groups=analytics.by_reward_risk,
    )

    impulse_atr_findings = _findings(
        dimension="IMPULSE ATR",
        groups=analytics.by_impulse_atr,
    )

    pullback_volume_findings = _findings(
        dimension="PULLBACK VOLUME",
        groups=analytics.by_pullback_volume,
    )

    confirmation_time_findings = _findings(
        dimension="CONFIRMATION TIME",
        groups=analytics.by_confirmation_time,
    )

    all_findings = (
        symbol_findings
        + entry_time_findings
        + reward_risk_findings
        + impulse_atr_findings
        + pullback_volume_findings
        + confirmation_time_findings
    )

    eligible = [
        finding
        for finding in all_findings
        if _eligible_for_ranking(finding)
    ]

    strongest = (
        max(
            eligible,
            key=lambda finding: (
                float(
                    finding.expectancy_per_trade
                ),
                finding.closed_trades,
            ),
        )
        if eligible
        else None
    )

    weakest = (
        min(
            eligible,
            key=lambda finding: (
                float(
                    finding.expectancy_per_trade
                ),
                -finding.closed_trades,
            ),
        )
        if eligible
        else None
    )

    return FibonacciPaperEvaluation(
        total_orders=analytics.total_orders,
        closed_trades=analytics.closed_trades,
        evidence_status=evidence_status,
        evidence_message=evidence_message,
        parameter_changes_allowed=False,
        strongest_cohort=strongest,
        weakest_cohort=weakest,
        symbol_findings=symbol_findings,
        entry_time_findings=entry_time_findings,
        reward_risk_findings=reward_risk_findings,
        impulse_atr_findings=impulse_atr_findings,
        pullback_volume_findings=(
            pullback_volume_findings
        ),
        confirmation_time_findings=(
            confirmation_time_findings
        ),
    )


def load_fibonacci_paper_evaluation(
) -> FibonacciPaperEvaluation:
    return build_fibonacci_paper_evaluation(
        analytics=load_webull_paper_analytics()
    )
