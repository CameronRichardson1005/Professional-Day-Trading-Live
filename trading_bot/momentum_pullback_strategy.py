from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time


MOMENTUM_PULLBACK_STRATEGY_NAME = (
    "MOMENTUM_PULLBACK"
)


@dataclass(frozen=True)
class MomentumCandle:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

    @property
    def range(self) -> float:
        return self.high - self.low

    @property
    def is_bullish(self) -> bool:
        return self.close > self.open

    @property
    def is_bearish(self) -> bool:
        return self.close < self.open


@dataclass(frozen=True)
class MomentumPullbackSignal:
    symbol: str

    signal: str
    pattern: str
    status: str
    detail: str

    entry_price: float | None
    stop_price: float | None
    target_price: float | None

    risk_per_share: float | None
    reward_risk: float | None

    pullback_candles: int
    retracement_fraction: float | None

    trigger_time: datetime | None


class MomentumPullbackStrategy:
    """
    Research implementation of the momentum-pullback
    material.

    Source-backed concepts:
    - trade strong momentum stocks
    - buy pullbacks / dips on the front side
    - buy the first candle to make a new high
    - flat-top breakout is another valid entry
    - use approximately 2:1 reward/risk

    Mechanical research assumptions:
    - micro-pullback = 1 to 3 candles
    - maximum retracement = 50% of impulse range
    - pullback volume must contract versus impulse
    - entries stop after 11:00 ET
    """

    def __init__(
        self,
        *,
        max_pullback_candles: int = 3,
        max_retracement_fraction: float = 0.50,
        reward_risk: float = 2.0,
        flat_top_tolerance: float = 0.002,
        latest_entry_time: time = time(11, 0),
    ) -> None:
        if max_pullback_candles < 1:
            raise ValueError(
                "max_pullback_candles must be positive."
            )

        if not 0 < max_retracement_fraction <= 1:
            raise ValueError(
                "max_retracement_fraction must be "
                "between 0 and 1."
            )

        if reward_risk <= 0:
            raise ValueError(
                "reward_risk must be positive."
            )

        self.max_pullback_candles = (
            max_pullback_candles
        )
        self.max_retracement_fraction = (
            max_retracement_fraction
        )
        self.reward_risk = reward_risk
        self.flat_top_tolerance = (
            flat_top_tolerance
        )
        self.latest_entry_time = (
            latest_entry_time
        )

    def _entry_time_allowed(
        self,
        candle: MomentumCandle,
    ) -> bool:
        clock = (
            candle.timestamp
            .timetz()
            .replace(tzinfo=None)
        )

        return clock <= self.latest_entry_time

    @staticmethod
    def _no_signal(
        *,
        symbol: str,
        pattern: str,
        status: str,
        detail: str,
        pullback_candles: int = 0,
        retracement_fraction: float | None = None,
    ) -> MomentumPullbackSignal:
        return MomentumPullbackSignal(
            symbol=symbol,
            signal="NO INVEST",
            pattern=pattern,
            status=status,
            detail=detail,
            entry_price=None,
            stop_price=None,
            target_price=None,
            risk_per_share=None,
            reward_risk=None,
            pullback_candles=pullback_candles,
            retracement_fraction=(
                retracement_fraction
            ),
            trigger_time=None,
        )

    def _invest_signal(
        self,
        *,
        symbol: str,
        pattern: str,
        entry: float,
        stop: float,
        trigger: MomentumCandle,
        pullback_candles: int,
        retracement_fraction: float | None,
    ) -> MomentumPullbackSignal:
        risk = entry - stop

        if risk <= 0:
            return self._no_signal(
                symbol=symbol,
                pattern=pattern,
                status="INVALID_RISK",
                detail=(
                    "Entry must be above stop."
                ),
                pullback_candles=(
                    pullback_candles
                ),
                retracement_fraction=(
                    retracement_fraction
                ),
            )

        target = (
            entry
            + risk * self.reward_risk
        )

        return MomentumPullbackSignal(
            symbol=symbol,
            signal="INVEST",
            pattern=pattern,
            status="CONFIRMED",
            detail=(
                f"{pattern} confirmed at "
                f"{trigger.timestamp.isoformat()}."
            ),
            entry_price=entry,
            stop_price=stop,
            target_price=target,
            risk_per_share=risk,
            reward_risk=self.reward_risk,
            pullback_candles=(
                pullback_candles
            ),
            retracement_fraction=(
                retracement_fraction
            ),
            trigger_time=trigger.timestamp,
        )

    def evaluate_micro_pullback(
        self,
        *,
        symbol: str,
        impulse: MomentumCandle,
        pullback: list[MomentumCandle],
        trigger: MomentumCandle,
    ) -> MomentumPullbackSignal:
        pattern = "MICRO_PULLBACK"

        if not self._entry_time_allowed(trigger):
            return self._no_signal(
                symbol=symbol,
                pattern=pattern,
                status="AFTER_CUTOFF",
                detail="Entry occurred after 11:00 ET.",
            )

        if not impulse.is_bullish:
            return self._no_signal(
                symbol=symbol,
                pattern=pattern,
                status="NO_BULLISH_IMPULSE",
                detail=(
                    "Momentum impulse must be bullish."
                ),
            )

        if impulse.range <= 0:
            return self._no_signal(
                symbol=symbol,
                pattern=pattern,
                status="INVALID_IMPULSE",
                detail=(
                    "Impulse range must be positive."
                ),
            )

        count = len(pullback)

        if (
            count < 1
            or count > self.max_pullback_candles
        ):
            return self._no_signal(
                symbol=symbol,
                pattern=pattern,
                status="INVALID_PULLBACK_LENGTH",
                detail=(
                    "Micro-pullback must contain "
                    f"1-{self.max_pullback_candles} candles."
                ),
                pullback_candles=count,
            )

        pullback_low = min(
            candle.low
            for candle in pullback
        )

        retracement = (
            impulse.high - pullback_low
        ) / impulse.range

        if (
            retracement
            > self.max_retracement_fraction
        ):
            return self._no_signal(
                symbol=symbol,
                pattern=pattern,
                status="PULLBACK_TOO_DEEP",
                detail=(
                    "Pullback retraced more than "
                    f"{self.max_retracement_fraction:.0%} "
                    "of the impulse."
                ),
                pullback_candles=count,
                retracement_fraction=retracement,
            )

        if impulse.volume <= 0:
            return self._no_signal(
                symbol=symbol,
                pattern=pattern,
                status="IMPULSE_VOLUME_MISSING",
                detail=(
                    "Impulse volume must be positive."
                ),
                pullback_candles=count,
                retracement_fraction=retracement,
            )

        average_pullback_volume = (
            sum(
                candle.volume
                for candle in pullback
            )
            / count
        )

        if (
            average_pullback_volume
            >= impulse.volume
        ):
            return self._no_signal(
                symbol=symbol,
                pattern=pattern,
                status="NO_VOLUME_CONTRACTION",
                detail=(
                    "Pullback volume did not contract "
                    "versus the impulse candle."
                ),
                pullback_candles=count,
                retracement_fraction=retracement,
            )

        # Mechanical interpretation of the source's
        # "first candle to make a new high":
        # entry is the break of the final pullback
        # candle's high.
        entry = pullback[-1].high

        if trigger.high <= entry:
            return self._no_signal(
                symbol=symbol,
                pattern=pattern,
                status="NO_NEW_HIGH_BREAK",
                detail=(
                    "Trigger did not break the prior "
                    "pullback candle high."
                ),
                pullback_candles=count,
                retracement_fraction=retracement,
            )

        return self._invest_signal(
            symbol=symbol,
            pattern=pattern,
            entry=entry,
            stop=pullback_low,
            trigger=trigger,
            pullback_candles=count,
            retracement_fraction=retracement,
        )

    def evaluate_flat_top(
        self,
        *,
        symbol: str,
        base: list[MomentumCandle],
        breakout: MomentumCandle,
    ) -> MomentumPullbackSignal:
        pattern = "FLAT_TOP"

        if not self._entry_time_allowed(
            breakout
        ):
            return self._no_signal(
                symbol=symbol,
                pattern=pattern,
                status="AFTER_CUTOFF",
                detail="Entry occurred after 11:00 ET.",
            )

        if len(base) < 2:
            return self._no_signal(
                symbol=symbol,
                pattern=pattern,
                status="INSUFFICIENT_BASE",
                detail=(
                    "Flat top requires at least "
                    "two resistance tests."
                ),
            )

        highs = [
            candle.high
            for candle in base
        ]

        resistance = max(highs)

        if resistance <= 0:
            return self._no_signal(
                symbol=symbol,
                pattern=pattern,
                status="INVALID_RESISTANCE",
                detail=(
                    "Flat-top resistance must "
                    "be positive."
                ),
            )

        spread = (
            max(highs) - min(highs)
        ) / resistance

        if spread > self.flat_top_tolerance:
            return self._no_signal(
                symbol=symbol,
                pattern=pattern,
                status="NOT_FLAT_TOP",
                detail=(
                    "Resistance highs are outside "
                    "flat-top tolerance."
                ),
            )

        if breakout.high <= resistance:
            return self._no_signal(
                symbol=symbol,
                pattern=pattern,
                status="NO_BREAKOUT",
                detail=(
                    "Breakout candle did not break "
                    "flat-top resistance."
                ),
            )

        stop = min(
            candle.low
            for candle in base
        )

        return self._invest_signal(
            symbol=symbol,
            pattern=pattern,
            entry=resistance,
            stop=stop,
            trigger=breakout,
            pullback_candles=len(base),
            retracement_fraction=None,
        )
