from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


QUICK_FLIP_STRATEGY_NAME = "QUICK_FLIP"

# Opening 15-minute candle range must be at least
# 25% of the 14-day ATR.
QUICK_FLIP_LIQUIDITY_MULTIPLIER = 0.25


@dataclass(frozen=True)
class QuickFlipCandle:
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
    def body(self) -> float:
        return abs(self.close - self.open)

    @property
    def upper_wick(self) -> float:
        return self.high - max(
            self.open,
            self.close,
        )

    @property
    def lower_wick(self) -> float:
        return min(
            self.open,
            self.close,
        ) - self.low

    @property
    def is_bullish(self) -> bool:
        return self.close > self.open

    @property
    def is_bearish(self) -> bool:
        return self.close < self.open


@dataclass(frozen=True)
class QuickFlipOpeningRange:
    high: float
    low: float
    open: float
    close: float

    @property
    def range(self) -> float:
        return self.high - self.low


@dataclass(frozen=True)
class QuickFlipSignal:
    symbol: str

    signal: str
    pattern: str
    status: str
    detail: str

    entry_price: float | None

    take_profit_1: float | None
    take_profit_2: float | None

    opening_range_high: float
    opening_range_low: float

    opening_range_size: float
    atr_14: float
    liquidity_threshold: float

    reversal_time: datetime | None = None
    confirmation_time: datetime | None = None

    # Quick Flip intentionally has no automatic stop loss.
    # We do not include a stop-loss field here.


class QuickFlipStrategy:
    """
    Long-only Quick Flip strategy.

    Sequence
    --------
    1. Calculate 14-day ATR externally.
    2. Wait for the opening 15-minute candle to close.
    3. Opening candle range must be >= 0.25 * ATR14.
    4. That SAME opening candle creates the box.
    5. Watch 5-minute candles below the box.
    6. Find either:
       - hammer / inverted hammer
       - bullish engulfing
    7. Confirm entry according to pattern.
    8. TP1 = opening-range low.
    9. TP2 = opening-range high.

    There is intentionally no automatic stop loss.
    There is no short-selling logic.
    """

    def __init__(
        self,
        liquidity_multiplier: float = (
            QUICK_FLIP_LIQUIDITY_MULTIPLIER
        ),
    ) -> None:
        if liquidity_multiplier <= 0:
            raise ValueError(
                "Liquidity multiplier must be positive."
            )

        self.liquidity_multiplier = liquidity_multiplier

    @staticmethod
    def build_opening_range(
        opening_bar: QuickFlipCandle,
    ) -> QuickFlipOpeningRange:
        """
        The completed 09:30-09:45 candle creates
        the Quick Flip opening-range box.
        """

        if opening_bar.high < opening_bar.low:
            raise ValueError(
                "Opening bar high cannot be below its low."
            )

        return QuickFlipOpeningRange(
            high=opening_bar.high,
            low=opening_bar.low,
            open=opening_bar.open,
            close=opening_bar.close,
        )

    def liquidity_threshold(
        self,
        atr_14: float,
    ) -> float:
        if atr_14 <= 0:
            raise ValueError(
                "ATR14 must be positive."
            )

        return atr_14 * self.liquidity_multiplier

    def is_liquidity_opening_candle(
        self,
        opening_range: QuickFlipOpeningRange,
        atr_14: float,
    ) -> bool:
        """
        Liquidity is determined ONLY from the
        completed opening 15-minute candle.

        No 5-minute candle participates in this test.
        """

        threshold = self.liquidity_threshold(
            atr_14
        )

        return opening_range.range >= threshold

    @staticmethod
    def is_outside_lower_box(
        candle: QuickFlipCandle,
        opening_range: QuickFlipOpeningRange,
    ) -> bool:
        """
        Quick Flip is long-only.

        The reversal setup therefore needs to trade
        below the opening-range low.
        """

        return candle.low < opening_range.low

    @staticmethod
    def is_hammer(
        candle: QuickFlipCandle,
    ) -> bool:
        """
        Hammer:
        - lower wick >= 2x body
        - upper wick <= body

        Zero-body candles are excluded.
        """

        body = candle.body

        if body <= 0:
            return False

        return (
            candle.lower_wick >= (2.0 * body)
            and candle.upper_wick <= body
        )

    @staticmethod
    def is_inverted_hammer(
        candle: QuickFlipCandle,
    ) -> bool:
        """
        Inverted hammer:
        - upper wick >= 2x body
        - lower wick <= body

        Zero-body candles are excluded.
        """

        body = candle.body

        if body <= 0:
            return False

        return (
            candle.upper_wick >= (2.0 * body)
            and candle.lower_wick <= body
        )

    @classmethod
    def hammer_pattern_name(
        cls,
        candle: QuickFlipCandle,
    ) -> str | None:
        if cls.is_hammer(candle):
            return "HAMMER"

        if cls.is_inverted_hammer(candle):
            return "INVERTED_HAMMER"

        return None

    @staticmethod
    def is_bullish_engulfing(
        previous: QuickFlipCandle,
        current: QuickFlipCandle,
    ) -> bool:
        """
        Bullish engulfing requires:

        - previous candle red
        - current candle green
        - current candle fully engulfs the
          previous candle's complete high-low range

        This deliberately uses the full candle,
        not only the real body.
        """

        if not previous.is_bearish:
            return False

        if not current.is_bullish:
            return False

        return (
            current.low <= previous.low
            and current.high >= previous.high
        )

    def evaluate_hammer_setup(
        self,
        *,
        symbol: str,
        atr_14: float,
        opening_range: QuickFlipOpeningRange,
        previous: QuickFlipCandle,
        reversal: QuickFlipCandle,
        confirmation: QuickFlipCandle,
    ) -> QuickFlipSignal:
        threshold = self.liquidity_threshold(
            atr_14
        )

        if not self.is_liquidity_opening_candle(
            opening_range,
            atr_14,
        ):
            return self._no_invest(
                symbol=symbol,
                pattern="NONE",
                status="NO_LIQUIDITY",
                detail=(
                    "Opening 15-minute candle did not "
                    "meet the liquidity threshold."
                ),
                opening_range=opening_range,
                atr_14=atr_14,
                threshold=threshold,
            )

        if not previous.is_bearish:
            return self._no_invest(
                symbol=symbol,
                pattern="NONE",
                status="NO_RED_CANDLE",
                detail=(
                    "Hammer setup requires a red candle "
                    "before the reversal candle."
                ),
                opening_range=opening_range,
                atr_14=atr_14,
                threshold=threshold,
            )

        if not self.is_outside_lower_box(
            reversal,
            opening_range,
        ):
            return self._no_invest(
                symbol=symbol,
                pattern="NONE",
                status="INSIDE_BOX",
                detail=(
                    "Reversal candle did not trade below "
                    "the opening-range low."
                ),
                opening_range=opening_range,
                atr_14=atr_14,
                threshold=threshold,
            )

        pattern = self.hammer_pattern_name(
            reversal
        )

        if pattern is None:
            return self._no_invest(
                symbol=symbol,
                pattern="NONE",
                status="NO_REVERSAL_PATTERN",
                detail=(
                    "Outside candle was not a hammer "
                    "or inverted hammer."
                ),
                opening_range=opening_range,
                atr_14=atr_14,
                threshold=threshold,
            )

        entry_price = reversal.high

        if entry_price >= opening_range.low:
            return self._no_invest(
                symbol=symbol,
                pattern=pattern,
                status="ENTRY_INSIDE_BOX",
                detail=(
                    "Hammer entry is not below the "
                    "opening-range low."
                ),
                opening_range=opening_range,
                atr_14=atr_14,
                threshold=threshold,
                reversal_time=reversal.timestamp,
            )

        if confirmation.high <= entry_price:
            return self._no_invest(
                symbol=symbol,
                pattern=pattern,
                status="WAITING_FOR_BREAK",
                detail=(
                    "Following 5-minute candle did not "
                    "break the reversal candle high."
                ),
                opening_range=opening_range,
                atr_14=atr_14,
                threshold=threshold,
                reversal_time=reversal.timestamp,
            )

        return QuickFlipSignal(
            symbol=symbol,
            signal="INVEST",
            pattern=pattern,
            status="CONFIRMED",
            detail=(
                "Hammer-family reversal confirmed by "
                "a break of the reversal candle high."
            ),
            entry_price=entry_price,
            take_profit_1=opening_range.low,
            take_profit_2=opening_range.high,
            opening_range_high=opening_range.high,
            opening_range_low=opening_range.low,
            opening_range_size=opening_range.range,
            atr_14=atr_14,
            liquidity_threshold=threshold,
            reversal_time=reversal.timestamp,
            confirmation_time=confirmation.timestamp,
        )

    def evaluate_engulfing_setup(
        self,
        *,
        symbol: str,
        atr_14: float,
        opening_range: QuickFlipOpeningRange,
        previous: QuickFlipCandle,
        engulfing: QuickFlipCandle,
        confirmation: QuickFlipCandle,
    ) -> QuickFlipSignal:
        threshold = self.liquidity_threshold(
            atr_14
        )

        if not self.is_liquidity_opening_candle(
            opening_range,
            atr_14,
        ):
            return self._no_invest(
                symbol=symbol,
                pattern="BULLISH_ENGULFING",
                status="NO_LIQUIDITY",
                detail=(
                    "Opening 15-minute candle did not "
                    "meet the liquidity threshold."
                ),
                opening_range=opening_range,
                atr_14=atr_14,
                threshold=threshold,
            )

        if not (
            self.is_outside_lower_box(
                previous,
                opening_range,
            )
            or self.is_outside_lower_box(
                engulfing,
                opening_range,
            )
        ):
            return self._no_invest(
                symbol=symbol,
                pattern="BULLISH_ENGULFING",
                status="INSIDE_BOX",
                detail=(
                    "Engulfing setup did not trade below "
                    "the opening-range low."
                ),
                opening_range=opening_range,
                atr_14=atr_14,
                threshold=threshold,
            )

        if not self.is_bullish_engulfing(
            previous,
            engulfing,
        ):
            return self._no_invest(
                symbol=symbol,
                pattern="BULLISH_ENGULFING",
                status="NO_REVERSAL_PATTERN",
                detail=(
                    "Candles did not form a valid "
                    "bullish engulfing reversal."
                ),
                opening_range=opening_range,
                atr_14=atr_14,
                threshold=threshold,
            )

        # The engulfing candle must finish before an
        # entry can be confirmed.
        #
        # Entry = break of the engulfing candle high by the
        # following completed 5-minute candle.
        entry_price = engulfing.high

        if entry_price >= opening_range.low:
            return self._no_invest(
                symbol=symbol,
                pattern="BULLISH_ENGULFING",
                status="ENTRY_INSIDE_BOX",
                detail=(
                    "Bullish engulfing breakout entry is "
                    "not below the opening-range low."
                ),
                opening_range=opening_range,
                atr_14=atr_14,
                threshold=threshold,
                reversal_time=engulfing.timestamp,
            )

        if confirmation.high <= entry_price:
            return self._no_invest(
                symbol=symbol,
                pattern="BULLISH_ENGULFING",
                status="WAITING_FOR_BREAK",
                detail=(
                    "Following 5-minute candle did not "
                    "break the engulfing candle high."
                ),
                opening_range=opening_range,
                atr_14=atr_14,
                threshold=threshold,
                reversal_time=engulfing.timestamp,
            )

        return QuickFlipSignal(
            symbol=symbol,
            signal="INVEST",
            pattern="BULLISH_ENGULFING",
            status="CONFIRMED",
            detail=(
                "Bullish engulfing reversal confirmed by "
                "a following break of the engulfing high."
            ),
            entry_price=entry_price,
            take_profit_1=opening_range.low,
            take_profit_2=opening_range.high,
            opening_range_high=opening_range.high,
            opening_range_low=opening_range.low,
            opening_range_size=opening_range.range,
            atr_14=atr_14,
            liquidity_threshold=threshold,
            reversal_time=engulfing.timestamp,
            confirmation_time=confirmation.timestamp,
        )

    @staticmethod
    def _no_invest(
        *,
        symbol: str,
        pattern: str,
        status: str,
        detail: str,
        opening_range: QuickFlipOpeningRange,
        atr_14: float,
        threshold: float,
        reversal_time: datetime | None = None,
    ) -> QuickFlipSignal:
        return QuickFlipSignal(
            symbol=symbol,
            signal="NO INVEST",
            pattern=pattern,
            status=status,
            detail=detail,
            entry_price=None,
            take_profit_1=None,
            take_profit_2=None,
            opening_range_high=opening_range.high,
            opening_range_low=opening_range.low,
            opening_range_size=opening_range.range,
            atr_14=atr_14,
            liquidity_threshold=threshold,
            reversal_time=reversal_time,
            confirmation_time=None,
        )
