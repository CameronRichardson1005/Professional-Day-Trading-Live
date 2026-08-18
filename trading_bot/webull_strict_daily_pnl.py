from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Callable

from .webull_trade_history import (
    WebullTradeHistoryError,
    parse_webull_fills_strict,
    strict_daily_realized_pnl,
)


class WebullStrictDailyPnlError(
    RuntimeError
):
    pass


class WebullStrictDailyRealizedPnlProvider:
    """
    Read-only daily realized-P&L provider for execution risk.

    The provider:
    - requires an explicitly injected history reader;
    - requires an explicitly injected trading-date provider;
    - requires an explicit history start date;
    - parses broker history with the strict fill parser;
    - calculates realized P&L using strict overnight FIFO;
    - never defaults missing P&L to zero.

    It does not create a Webull client and cannot place, replace,
    cancel, close, preview, or submit orders.
    """

    def __init__(
        self,
        *,
        history_reader: Any,
        trading_date_provider: Callable[[], str],
        history_start_date: str,
    ) -> None:
        get_history_payload = getattr(
            history_reader,
            "get_history_payload",
            None,
        )

        if not callable(
            get_history_payload
        ):
            raise WebullStrictDailyPnlError(
                "STRICT_PNL_HISTORY_READER_INVALID"
            )

        if not callable(
            trading_date_provider
        ):
            raise WebullStrictDailyPnlError(
                "STRICT_PNL_DATE_PROVIDER_INVALID"
            )

        self.history_start_date = (
            self._parse_date(
                history_start_date,
                reason=(
                    "STRICT_PNL_HISTORY_START_DATE_INVALID"
                ),
            )
        )

        self.history_reader = (
            history_reader
        )

        self.trading_date_provider = (
            trading_date_provider
        )

    @staticmethod
    def _parse_date(
        value: Any,
        *,
        reason: str,
    ) -> date:
        if not isinstance(
            value,
            str,
        ):
            raise WebullStrictDailyPnlError(
                reason
            )

        try:
            return date.fromisoformat(
                value
            )
        except ValueError as error:
            raise WebullStrictDailyPnlError(
                reason
            ) from error

    def __call__(
        self,
    ) -> float:
        try:
            raw_target_date = (
                self.trading_date_provider()
            )
        except Exception as error:
            raise WebullStrictDailyPnlError(
                "STRICT_PNL_DATE_UNAVAILABLE"
            ) from error

        target_date = self._parse_date(
            raw_target_date,
            reason=(
                "STRICT_PNL_TRADING_DATE_INVALID"
            ),
        )

        if (
            target_date
            < self.history_start_date
        ):
            raise WebullStrictDailyPnlError(
                "STRICT_PNL_DATE_BEFORE_HISTORY_START"
            )

        try:
            end_date = (
                target_date
                + timedelta(days=1)
            )
        except OverflowError as error:
            raise WebullStrictDailyPnlError(
                "STRICT_PNL_END_DATE_INVALID"
            ) from error

        try:
            payload = (
                self.history_reader
                .get_history_payload(
                    start_date=(
                        self.history_start_date
                        .isoformat()
                    ),
                    end_date=(
                        end_date.isoformat()
                    ),
                )
            )
        except Exception as error:
            raise WebullStrictDailyPnlError(
                "STRICT_PNL_HISTORY_UNAVAILABLE"
            ) from error

        try:
            fills = (
                parse_webull_fills_strict(
                    payload
                )
            )
        except WebullTradeHistoryError as error:
            raise WebullStrictDailyPnlError(
                "STRICT_PNL_HISTORY_INVALID"
            ) from error

        try:
            result = (
                strict_daily_realized_pnl(
                    fills,
                    target_date.isoformat(),
                )
            )
        except WebullTradeHistoryError as error:
            raise WebullStrictDailyPnlError(
                "STRICT_PNL_CALCULATION_FAILED"
            ) from error

        return float(
            result
        )
