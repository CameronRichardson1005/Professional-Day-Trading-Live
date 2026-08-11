from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from .fibonacci_paper import qualifies_for_fibonacci_paper
from .fibonacci_retracement import analyse_symbol_day
from .models import Stock


class Fibonacci618Strategy:
    """
    Active paper/preview adapter for the preserved Fibonacci
    61.8% retracement rules.

    This adapter maps a qualifying Fibonacci setup onto the
    existing Stock fields used by Google Sheets, the Cloudflare
    dashboard, and Webull preview generation.

    It never submits an order.
    """

    name = "FIBONACCI_61_8"
    status = "ACTIVE PAPER/PREVIEW — NOT SUBMITTED"

    def evaluate(
        self,
        *,
        stock: Stock,
        date_str: str,
        bars: Sequence[dict[str, Any]],
        atr: float | None,
        data_feed: str,
        slippage_bps: float = 15.0,
    ) -> Stock:
        self._reset_active_fields(stock)

        stock.strategy_name = self.name
        stock.strategy_status = self.status
        stock.atr = atr

        opening_bar = stock.opening_bar

        if isinstance(opening_bar, dict):
            opening_open = opening_bar.get("o")
            opening_close = opening_bar.get("c")

            stock.is_red = (
                isinstance(opening_open, (int, float))
                and isinstance(opening_close, (int, float))
                and float(opening_close) < float(opening_open)
            )
        else:
            stock.is_red = False

        setups = analyse_symbol_day(
            date_str=date_str,
            symbol=stock.symbol,
            data_feed=data_feed,
            bars=list(bars),
            atr=atr,
            minimum_impulse_atr=0.50,
            slippage_bps=slippage_bps,
            commission_per_share=0.0,
        )

        setup = next(
            (
                candidate
                for candidate in setups
                if candidate.fibonacci_level == "FIB_61_8"
            ),
            None,
        )

        stock.strategy_detail = (
            setup.detail
            if setup is not None
            else "FIB_61_8 setup was not evaluated."
        )

        if setup is None or not qualifies_for_fibonacci_paper(setup):
            stock.signal = "NO INVEST"

            if setup is not None:
                stock.strategy_rejection_reason = (
                    self._qualification_rejection_reason(setup)
                )

            return stock

        if (
            setup.entry_price is None
            or setup.stop_price is None
            or setup.target_price is None
        ):
            stock.signal = "NO INVEST"
            stock.strategy_rejection_reason = (
                "QUALIFYING_SETUP_MISSING_LEVELS"
            )
            return stock

        stock.signal = "INVEST"
        stock.limit_buy = float(setup.entry_price)
        stock.limit_sell = float(setup.target_price)

        # The Fibonacci structural stop becomes both the displayed
        # and trading stop. No manipulation STOP_BUFFER is applied.
        stock.stop_loss = float(setup.stop_price)
        stock.trading_stop_loss = float(setup.stop_price)

        stock.reward_risk = setup.reward_risk
        stock.confirmation_time = setup.confirmation_time
        stock.retracement_price = setup.retracement_price
        stock.impulse_atr_multiple = setup.impulse_atr_multiple
        stock.pullback_volume_ratio = setup.pullback_volume_ratio
        stock.strategy_rejection_reason = ""

        return stock

    @staticmethod
    def _qualification_rejection_reason(
        setup: Any,
    ) -> str:
        """
        Return the first explicit paper-qualification rule that
        rejected the setup.
        """
        if setup.rejection_reason:
            return str(setup.rejection_reason)

        if not setup.setup_found:
            return (
                setup.detail
                or "FIBONACCI_SETUP_NOT_FOUND"
            )

        if setup.impulse_atr_multiple is None:
            return "IMPULSE_ATR_MULTIPLE_UNAVAILABLE"

        if setup.impulse_atr_multiple < 0.50:
            return "IMPULSE_BELOW_0_50_ATR"

        if setup.impulse_duration_minutes is None:
            return "IMPULSE_DURATION_UNAVAILABLE"

        if setup.impulse_duration_minutes < 15:
            return "IMPULSE_DURATION_BELOW_15_MINUTES"

        if setup.pullback_volume_ratio is None:
            return "PULLBACK_VOLUME_RATIO_UNAVAILABLE"

        if setup.pullback_volume_ratio >= 1.0:
            return "PULLBACK_VOLUME_NOT_LOWER_THAN_IMPULSE"

        if setup.reward_risk is None:
            return "REWARD_RISK_UNAVAILABLE"

        if setup.reward_risk < 1.5:
            return "REWARD_RISK_BELOW_1_50"

        return (
            setup.detail
            or "FIBONACCI_RULES_NOT_SATISFIED"
        )

    @staticmethod
    def _reset_active_fields(stock: Stock) -> None:
        stock.signal = "NO INVEST"
        stock.limit_buy = None
        stock.limit_sell = None
        stock.stop_loss = None
        stock.trading_stop_loss = None
        stock.webull_preview = None

        stock.strategy_detail = ""
        stock.strategy_rejection_reason = ""
        stock.reward_risk = None
        stock.confirmation_time = ""
        stock.retracement_price = None
        stock.impulse_atr_multiple = None
        stock.pullback_volume_ratio = None
