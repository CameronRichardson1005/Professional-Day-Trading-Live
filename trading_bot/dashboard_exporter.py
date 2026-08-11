from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import requests

from .config import (
    DASHBOARD_INGEST_KEY,
    DASHBOARD_REQUEST_TIMEOUT,
    DASHBOARD_SITE_TOKEN,
    DASHBOARD_URL,
    FIBONACCI_STRATEGY_NAME,
    MANIPULATION_STRATEGY_NAME,
    MARKET_DATA_FEED,
)
from .models import Stock


class DashboardExporter:
    """
    Sends read-only session results to the dashboard.

    This class cannot submit, modify, or cancel orders.
    """

    EXPECTED_BARS = 15

    def __init__(
            self,
            url: str = DASHBOARD_URL,
            ingest_key: str = DASHBOARD_INGEST_KEY,
            site_token: str = DASHBOARD_SITE_TOKEN,
            timeout: tuple[int, int] = (
                DASHBOARD_REQUEST_TIMEOUT
            ),
            post_fn=None,
    ) -> None:
        self.url = url
        self.ingest_key = ingest_key
        self.site_token = site_token
        self.timeout = timeout
        self.post_fn = post_fn or requests.post

    @staticmethod
    def _levels(stock: Stock) -> dict[str, float] | None:
        values = (
            stock.limit_buy,
            stock.limit_sell,
            stock.stop_loss,
            stock.trading_stop_loss,
        )

        if not all(
            isinstance(value, (int, float))
            for value in values
        ):
            return None

        return {
            "buy": float(stock.limit_buy),
            "target": float(stock.limit_sell),
            "stop": float(stock.stop_loss),
            "tradingStop": float(
                stock.trading_stop_loss
            ),
        }

    @staticmethod
    def _bar_time(bar: dict[str, Any]) -> str:
        raw_timestamp = str(bar["t"])
        normalised = raw_timestamp.replace(
            "Z",
            "+00:00",
        )

        timestamp = datetime.fromisoformat(
            normalised
        )

        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(
                tzinfo=timezone.utc
            )

        return (
            timestamp
            .astimezone(
                ZoneInfo("America/New_York")
            )
            .strftime("%H:%M")
        )

    @classmethod
    def _minute_bars(
            cls,
            stock: Stock,
    ) -> list[dict[str, Any]]:
        result = []

        for bar in stock.minute_bars[
            :cls.EXPECTED_BARS
        ]:
            payload = {
                "time": cls._bar_time(bar),
                "open": float(bar["o"]),
                "high": float(bar["h"]),
                "low": float(bar["l"]),
                "close": float(bar["c"]),
            }

            volume = bar.get("v")
            if isinstance(volume, (int, float)):
                payload["volume"] = float(volume)

            result.append(payload)

        return result

    @staticmethod
    def _optional_float(
            value,
    ) -> float | None:
        """
        Convert a numeric strategy value while preserving missing
        optional data.
        """
        if isinstance(value, (int, float)):
            return float(value)

        return None

    @classmethod
    def _strategy_payload(
            cls,
            stock: Stock,
    ) -> dict[str, Any]:
        """
        Build strategy-neutral dashboard metadata.

        Manipulation-specific and Fibonacci-specific fields coexist
        so historical sessions remain readable.
        """
        payload: dict[str, Any] = {
            "strategyName": (
                stock.strategy_name
                or MANIPULATION_STRATEGY_NAME
            ),
            "strategyStatus": stock.strategy_status,
            "detail": stock.strategy_detail,
            "rejectionReason": (
                stock.strategy_rejection_reason
            ),
            "atr": cls._optional_float(stock.atr),
        }

        opening_bar = stock.opening_bar

        if isinstance(opening_bar, dict):
            opening_fields = {
                "openingOpen": "o",
                "openingHigh": "h",
                "openingLow": "l",
                "openingClose": "c",
            }

            for output_name, source_name in (
                opening_fields.items()
            ):
                value = opening_bar.get(source_name)

                if isinstance(value, (int, float)):
                    payload[output_name] = float(value)

        optional_fields = {
            "candleRange": stock.candle_range,
            "atrThreshold": stock.atr_threshold,
            "rewardRisk": stock.reward_risk,
            "retracementPrice": (
                stock.retracement_price
            ),
            "impulseAtrMultiple": (
                stock.impulse_atr_multiple
            ),
            "pullbackVolumeRatio": (
                stock.pullback_volume_ratio
            ),
        }

        for output_name, value in optional_fields.items():
            converted = cls._optional_float(value)

            if converted is not None:
                payload[output_name] = converted

        if stock.confirmation_time:
            payload["confirmationTime"] = (
                stock.confirmation_time
            )

        payload["isManipulation"] = (
            bool(stock.is_manipulation)
        )
        payload["isRed"] = bool(stock.is_red)

        return payload

    @classmethod
    def _manipulation_rules(
            cls,
            stock: Stock,
    ) -> list[dict[str, Any]]:
        opening_bar = stock.opening_bar or {}

        candle_range = cls._optional_float(
            stock.candle_range
        )
        atr_threshold = cls._optional_float(
            stock.atr_threshold
        )

        open_price = cls._optional_float(
            opening_bar.get("o")
        )
        close_price = cls._optional_float(
            opening_bar.get("c")
        )

        return [
            {
                "label": "Manipulation candle",
                "passed": bool(stock.is_manipulation),
                "actual": (
                    (
                        f"Range ${candle_range:.4f}; "
                        f"ATR threshold ${atr_threshold:.4f}"
                    )
                    if (
                        candle_range is not None
                        and atr_threshold is not None
                    )
                    else "Unavailable"
                ),
                "requirement": (
                    "Range exceeds the ATR threshold "
                    "or is within $0.0050"
                ),
            },
            {
                "label": "Red opening candle",
                "passed": bool(stock.is_red),
                "actual": (
                    (
                        f"Open ${open_price:.4f}; "
                        f"close ${close_price:.4f}"
                    )
                    if (
                        open_price is not None
                        and close_price is not None
                    )
                    else "Unavailable"
                ),
                "requirement": (
                    "Opening close is below "
                    "the opening price"
                ),
            },
        ]

    @classmethod
    def _fibonacci_rules(
            cls,
            stock: Stock,
    ) -> list[dict[str, Any]]:
        impulse = cls._optional_float(
            stock.impulse_atr_multiple
        )
        volume_ratio = cls._optional_float(
            stock.pullback_volume_ratio
        )
        reward_risk = cls._optional_float(
            stock.reward_risk
        )

        return [
            {
                "label": "61.8% retracement setup",
                "passed": (
                    stock.retracement_price is not None
                ),
                "actual": (
                    (
                        f"${float(stock.retracement_price):.4f}"
                    )
                    if stock.retracement_price is not None
                    else "Not confirmed"
                ),
                "requirement": (
                    "Price touches the 61.8% Fibonacci "
                    "retracement"
                ),
            },
            {
                "label": "Impulse strength",
                "passed": (
                    impulse is not None
                    and impulse >= 0.50
                ),
                "actual": (
                    f"{impulse:.3f} ATR"
                    if impulse is not None
                    else "Unavailable"
                ),
                "requirement": "At least 0.50 ATR",
            },
            {
                "label": "Pullback volume",
                "passed": (
                    volume_ratio is not None
                    and volume_ratio < 1.0
                ),
                "actual": (
                    f"{volume_ratio:.3f}"
                    if volume_ratio is not None
                    else "Unavailable"
                ),
                "requirement": "Ratio below 1.0",
            },
            {
                "label": "Reward / risk",
                "passed": (
                    reward_risk is not None
                    and reward_risk >= 1.5
                ),
                "actual": (
                    f"{reward_risk:.2f}"
                    if reward_risk is not None
                    else "Unavailable"
                ),
                "requirement": "At least 1.50",
            },
            {
                "label": "Bullish confirmation",
                "passed": bool(
                    stock.confirmation_time
                ),
                "actual": (
                    stock.confirmation_time
                    or "Not confirmed"
                ),
                "requirement": (
                    "Bullish confirmation candle within "
                    "the permitted confirmation window"
                ),
            },
        ]

    @classmethod
    def _rules(
            cls,
            stock: Stock,
    ) -> list[dict[str, Any]]:
        if stock.strategy_name == FIBONACCI_STRATEGY_NAME:
            return cls._fibonacci_rules(stock)

        return cls._manipulation_rules(stock)

    @classmethod
    def _symbol_payload(
            cls,
            stock: Stock,
            bars_processed: int,
    ) -> dict[str, Any]:
        # Dashboard completeness refers only to the 09:30-09:44
        # opening window. Later Fibonacci-monitoring bars must not
        # increase this value beyond the expected 15 bars.
        bars_processed = max(
            0,
            min(
                int(bars_processed),
                cls.EXPECTED_BARS,
            ),
        )

        has_all_bars = (
            bars_processed >= cls.EXPECTED_BARS
        )
        strategy_complete = (
            has_all_bars
            and stock.opening_bar is not None
            and stock.atr is not None
        )

        if not has_all_bars:
            detail = (
                f"incomplete: {bars_processed}/"
                f"{cls.EXPECTED_BARS} bars"
            )
        elif stock.opening_bar is None:
            detail = "strategy unavailable"
        elif stock.atr is None:
            detail = "ATR unavailable"
        else:
            detail = "complete"

        payload: dict[str, Any] = {
            "symbol": stock.symbol,
            "signal": (
                stock.signal
                if strategy_complete
                else "WARNING"
            ),
            "barsProcessed": bars_processed,
            "barsExpected": cls.EXPECTED_BARS,
            "detail": detail,
        }

        levels = cls._levels(stock)
        if (
            strategy_complete
            and stock.signal == "INVEST"
            and levels is not None
        ):
            payload["levels"] = levels

        if strategy_complete:
            payload["rules"] = cls._rules(stock)
            payload["strategy"] = (
                cls._strategy_payload(stock)
            )

        minute_bars = cls._minute_bars(stock)
        if minute_bars:
            payload["minuteBars"] = minute_bars

        if (
            strategy_complete
            and stock.signal == "INVEST"
            and stock.webull_preview is not None
        ):
            preview = stock.webull_preview

            payload["webullPreview"] = {
                "status": str(
                    preview.get(
                        "status",
                        "PREVIEW FAILED",
                    )
                ),
                "submitted": False,
            }

            optional_fields = {
                "quantity": "quantity",
                "limitBuy": "limitBuy",
                "target": "target",
                "tradingStopLoss": "tradingStopLoss",
                "riskPerShare": "riskPerShare",
                "plannedRisk": "plannedRisk",
                "estimatedPositionValue": (
                    "estimatedPositionValue"
                ),
                "maxPositionValue": "maxPositionValue",
                "sizingConstraint": "sizingConstraint",
                "estimatedCost": "estimatedCost",
                "estimatedTransactionFee": (
                    "estimatedTransactionFee"
                ),
                "currency": "currency",
                "error": "error",
            }

            for output_name, source_name in optional_fields.items():
                value = preview.get(source_name)

                if value is not None:
                    payload["webullPreview"][
                        output_name
                    ] = value

        if (
            strategy_complete
            and stock.signal == "INVEST"
            and stock.outcome is not None
        ):
            payload["outcome"] = dict(
                stock.outcome
            )

        return payload

    @classmethod
    def build_payload(
            cls,
            date_str: str,
            source: str,
            stocks: dict[str, Stock],
            processed_bars: dict[str, int],
            data_feed: str = MARKET_DATA_FEED,
            symbol_reliability: list[dict[str, Any]] | None = None,
            run_mode: str = "MANUAL",
            webull_approvals: list[dict[str, Any]] | None = None,
            paper_performance: dict[str, Any] | None = None,
            paper_portfolio: dict[str, Any] | None = None,
            paper_analytics: dict[str, Any] | None = None,
            paper_evaluation: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        source = source.upper()

        supported_sources = {
            "REPLAY",
            "LIVE",
            "LIVE_MANIPULATION",
            "LIVE_FIBONACCI",
            "LIVE_FIBONACCI_FINAL",
        }

        if source not in supported_sources:
            raise ValueError(
                "Unsupported dashboard source: "
                f"{source}. Expected one of: "
                + ", ".join(sorted(supported_sources))
            )

        data_feed = data_feed.strip().lower()
        if data_feed not in {"iex", "sip"}:
            raise ValueError(
                "Dashboard sessions must use IEX or SIP market data."
            )

        symbols = [
            cls._symbol_payload(
                stock=stock,
                bars_processed=int(
                    processed_bars.get(symbol, 0)
                ),
            )
            for symbol, stock in stocks.items()
        ]

        status = (
            "COMPLETE"
            if all(
                symbol["detail"] == "complete"
                for symbol in symbols
            )
            else "INCOMPLETE"
        )

        updated_at = (
            datetime.now(timezone.utc)
            .isoformat(timespec="seconds")
            .replace("+00:00", "Z")
        )

        run_mode = run_mode.strip().upper()
        if run_mode not in {"MANUAL", "SCHEDULED", "REPLAY"}:
            run_mode = "MANUAL"

        payload = {
            "id": f"{source.lower()}-{date_str}",
            "tradingDate": date_str,
            "source": source,
            "dataFeed": data_feed.upper(),
            "status": status,
            "updatedAt": updated_at,
            "symbols": symbols,
            "productionHealth": {
                "runMode": (
                    "REPLAY"
                    if source == "REPLAY"
                    else run_mode
                ),
                "workflowStatus": "COMPLETED",
                "marketDay": True,
                "dataStatus": (
                    "HEALTHY"
                    if status == "COMPLETE"
                    else "WARNING"
                ),
            },
        }

        if symbol_reliability is not None:
            payload["symbolReliability"] = (
                symbol_reliability
            )

        if webull_approvals is not None:
            payload["webullApprovals"] = [
                dict(record)
                for record in webull_approvals
            ]
            payload["webullSafety"] = {
                "manualApprovalRequired": True,
                "killSwitchActive": True,
                "submissionEnabled": False,
            }

        if paper_performance is not None:
            payload["paperPerformance"] = dict(
                paper_performance
            )

        if paper_portfolio is not None:
            payload["paperPortfolio"] = dict(
                paper_portfolio
            )

        if paper_analytics is not None:
            payload["paperAnalytics"] = dict(
                paper_analytics
            )

        if paper_evaluation is not None:
            payload["paperEvaluation"] = dict(
                paper_evaluation
            )

        return payload

    def publish(
            self,
            date_str: str,
            source: str,
            stocks: dict[str, Stock],
            processed_bars: dict[str, int],
            data_feed: str = MARKET_DATA_FEED,
            symbol_reliability: list[dict[str, Any]] | None = None,
            run_mode: str = "MANUAL",
            webull_approvals: list[dict[str, Any]] | None = None,
            paper_performance: dict[str, Any] | None = None,
            paper_portfolio: dict[str, Any] | None = None,
            paper_analytics: dict[str, Any] | None = None,
            paper_evaluation: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        if not self.ingest_key:
            return None

        if not self.site_token:
            raise RuntimeError(
                "DASHBOARD_SITE_TOKEN is not configured."
            )

        payload = self.build_payload(
            date_str=date_str,
            source=source,
            stocks=stocks,
            processed_bars=processed_bars,
            data_feed=data_feed,
            symbol_reliability=symbol_reliability,
            run_mode=run_mode,
            webull_approvals=webull_approvals,
            paper_performance=paper_performance,
            paper_portfolio=paper_portfolio,
            paper_analytics=paper_analytics,
            paper_evaluation=paper_evaluation,
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
                f"Dashboard returned {response.status_code}: "
                f"{response.text}"
            ) from error

        result = response.json()
        if result.get("accepted") is not True:
            raise RuntimeError(
                "Dashboard did not accept the session."
            )

        return result
