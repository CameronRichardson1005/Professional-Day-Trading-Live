from __future__ import annotations

from dataclasses import dataclass

from .config import (
    WEBULL_ALLOW_MARGIN,
    WEBULL_ALLOW_SHORT_SELLING,
    WEBULL_MAX_TOTAL_EXPOSURE_DOLLARS,
    WEBULL_OPERATIONAL_EXPOSURE_CAP_DOLLARS,
    WEBULL_ORDER_SUBMISSION_ENABLED,
    WEBULL_REQUIRE_CASH_ACCOUNT,
    WEBULL_REQUIRE_MANUAL_APPROVAL,
)


@dataclass(frozen=True)
class WebullAccountState:
    account_type: str
    available_cash: float
    position_exposure: float
    open_buy_order_exposure: float
    data_is_current: bool = True

    @property
    def current_total_exposure(self) -> float:
        return round(
            self.position_exposure
            + self.open_buy_order_exposure,
            2,
        )


@dataclass(frozen=True)
class WebullOrderProposal:
    symbol: str
    side: str
    quantity: int
    limit_price: float
    manually_approved: bool = False

    @property
    def proposed_exposure(self) -> float:
        return round(
            self.quantity * self.limit_price,
            2,
        )


@dataclass(frozen=True)
class WebullSafetyDecision:
    allowed: bool
    reason: str
    current_exposure: float
    proposed_exposure: float
    projected_exposure: float
    available_cash: float
    operational_cap: float
    hard_cap: float


class WebullSafetyGate:
    """
    Fail-closed validation for any future Webull order.

    This module does not submit, replace, modify, or cancel orders.
    """

    @staticmethod
    def evaluate(
        *,
        account: WebullAccountState,
        proposal: WebullOrderProposal,
        require_manual_approval: bool = (
            WEBULL_REQUIRE_MANUAL_APPROVAL
        ),
        enforce_operational_cap: bool = True,
    ) -> WebullSafetyDecision:
        current_exposure = account.current_total_exposure
        proposed_exposure = proposal.proposed_exposure
        projected_exposure = round(
            current_exposure + proposed_exposure,
            2,
        )

        def reject(reason: str) -> WebullSafetyDecision:
            return WebullSafetyDecision(
                allowed=False,
                reason=reason,
                current_exposure=current_exposure,
                proposed_exposure=proposed_exposure,
                projected_exposure=projected_exposure,
                available_cash=account.available_cash,
                operational_cap=(
                    WEBULL_OPERATIONAL_EXPOSURE_CAP_DOLLARS
                ),
                hard_cap=(
                    WEBULL_MAX_TOTAL_EXPOSURE_DOLLARS
                ),
            )

        if not account.data_is_current:
            return reject("ACCOUNT_DATA_STALE_OR_UNKNOWN")

        account_type = (
            account.account_type.strip().upper()
        )

        if not account_type:
            return reject("ACCOUNT_TYPE_UNKNOWN")

        if (
            WEBULL_REQUIRE_CASH_ACCOUNT
            and account_type != "CASH"
        ):
            return reject("CASH_ACCOUNT_REQUIRED")

        if not WEBULL_ALLOW_MARGIN and account_type == "MARGIN":
            return reject("MARGIN_FORBIDDEN")

        side = proposal.side.strip().upper()

        if side != "BUY":
            if not WEBULL_ALLOW_SHORT_SELLING:
                return reject("ONLY_LONG_BUY_ORDERS_ALLOWED")

        if proposal.quantity <= 0:
            return reject("INVALID_QUANTITY")

        if proposal.limit_price <= 0:
            return reject("INVALID_LIMIT_PRICE")

        if proposed_exposure <= 0:
            return reject("INVALID_PROPOSED_EXPOSURE")

        if (
            require_manual_approval
            and not proposal.manually_approved
        ):
            return reject("MANUAL_APPROVAL_REQUIRED")

        if proposed_exposure > account.available_cash:
            return reject("INSUFFICIENT_AVAILABLE_CASH")

        if projected_exposure > (
            WEBULL_MAX_TOTAL_EXPOSURE_DOLLARS
        ):
            return reject("HARD_EXPOSURE_CAP_EXCEEDED")

        if (
            enforce_operational_cap
            and projected_exposure
            > WEBULL_OPERATIONAL_EXPOSURE_CAP_DOLLARS
        ):
            return reject("OPERATIONAL_EXPOSURE_CAP_EXCEEDED")

        return WebullSafetyDecision(
            allowed=True,
            reason="APPROVED_BY_SAFETY_GATE",
            current_exposure=current_exposure,
            proposed_exposure=proposed_exposure,
            projected_exposure=projected_exposure,
            available_cash=account.available_cash,
            operational_cap=(
                WEBULL_OPERATIONAL_EXPOSURE_CAP_DOLLARS
            ),
            hard_cap=WEBULL_MAX_TOTAL_EXPOSURE_DOLLARS,
        )

    @staticmethod
    def real_submission_available() -> bool:
        return WEBULL_ORDER_SUBMISSION_ENABLED
