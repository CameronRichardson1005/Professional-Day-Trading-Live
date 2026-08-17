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
    buying_power: float | None = None

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
class WebullReplacementProposal:
    symbol: str
    side: str

    current_quantity: int
    current_limit_price: float
    current_filled_quantity: float

    replacement_quantity: int
    replacement_limit_price: float

    @property
    def current_remaining_quantity(self) -> float:
        return round(
            float(self.current_quantity)
            - float(self.current_filled_quantity),
            5,
        )

    @property
    def current_order_exposure(self) -> float:
        return round(
            self.current_remaining_quantity
            * float(self.current_limit_price),
            2,
        )

    @property
    def replacement_exposure(self) -> float:
        return round(
            int(self.replacement_quantity)
            * float(self.replacement_limit_price),
            2,
        )


@dataclass(frozen=True)
class WebullReplacementSafetyDecision:
    allowed: bool
    reason: str

    current_exposure: float
    current_order_exposure: float
    replacement_exposure: float
    additional_exposure: float
    projected_exposure: float

    available_cash: float
    operational_cap: float
    hard_cap: float


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
        operational_cap_override: float | None = None,
        hard_cap_override: float | None = None,
    ) -> WebullSafetyDecision:
        operational_cap = (
            WEBULL_OPERATIONAL_EXPOSURE_CAP_DOLLARS
            if operational_cap_override is None
            else float(operational_cap_override)
        )

        hard_cap = (
            WEBULL_MAX_TOTAL_EXPOSURE_DOLLARS
            if hard_cap_override is None
            else float(hard_cap_override)
        )

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
                operational_cap=operational_cap,
                hard_cap=hard_cap,
            )

        if (
            operational_cap <= 0
            or hard_cap <= 0
            or operational_cap > hard_cap
        ):
            return reject("INVALID_EXPOSURE_CAP")

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

        if projected_exposure > hard_cap:
            return reject("HARD_EXPOSURE_CAP_EXCEEDED")

        if (
            enforce_operational_cap
            and projected_exposure
            > operational_cap
        ):
            return reject("OPERATIONAL_EXPOSURE_CAP_EXCEEDED")

        return WebullSafetyDecision(
            allowed=True,
            reason="APPROVED_BY_SAFETY_GATE",
            current_exposure=current_exposure,
            proposed_exposure=proposed_exposure,
            projected_exposure=projected_exposure,
            available_cash=account.available_cash,
            operational_cap=operational_cap,
            hard_cap=hard_cap,
        )

    @staticmethod
    def evaluate_replacement(
        *,
        account: WebullAccountState,
        proposal: WebullReplacementProposal,
        enforce_operational_cap: bool = True,
        operational_cap_override: float | None = None,
        hard_cap_override: float | None = None,
    ) -> WebullReplacementSafetyDecision:
        """
        Fail-closed safety evaluation for replacing one existing
        long BUY order.

        The existing order is already represented inside
        account.open_buy_order_exposure, so its reserved exposure
        is removed before the replacement reservation is added.
        """

        operational_cap = (
            WEBULL_OPERATIONAL_EXPOSURE_CAP_DOLLARS
            if operational_cap_override is None
            else float(operational_cap_override)
        )

        hard_cap = (
            WEBULL_MAX_TOTAL_EXPOSURE_DOLLARS
            if hard_cap_override is None
            else float(hard_cap_override)
        )

        current_exposure = (
            account.current_total_exposure
        )

        current_order_exposure = (
            proposal.current_order_exposure
        )

        replacement_exposure = (
            proposal.replacement_exposure
        )

        additional_exposure = round(
            max(
                replacement_exposure
                - current_order_exposure,
                0.0,
            ),
            2,
        )

        projected_exposure = round(
            current_exposure
            - current_order_exposure
            + replacement_exposure,
            2,
        )

        def reject(
            reason: str,
        ) -> WebullReplacementSafetyDecision:
            return WebullReplacementSafetyDecision(
                allowed=False,
                reason=reason,
                current_exposure=current_exposure,
                current_order_exposure=(
                    current_order_exposure
                ),
                replacement_exposure=(
                    replacement_exposure
                ),
                additional_exposure=(
                    additional_exposure
                ),
                projected_exposure=(
                    projected_exposure
                ),
                available_cash=(
                    account.available_cash
                ),
                operational_cap=operational_cap,
                hard_cap=hard_cap,
            )

        if (
            operational_cap <= 0
            or hard_cap <= 0
            or operational_cap > hard_cap
        ):
            return reject(
                "INVALID_EXPOSURE_CAP"
            )

        if not account.data_is_current:
            return reject(
                "ACCOUNT_DATA_STALE_OR_UNKNOWN"
            )

        account_type = (
            account.account_type
            .strip()
            .upper()
        )

        if not account_type:
            return reject(
                "ACCOUNT_TYPE_UNKNOWN"
            )

        if (
            WEBULL_REQUIRE_CASH_ACCOUNT
            and account_type != "CASH"
        ):
            return reject(
                "CASH_ACCOUNT_REQUIRED"
            )

        if (
            not WEBULL_ALLOW_MARGIN
            and account_type == "MARGIN"
        ):
            return reject(
                "MARGIN_FORBIDDEN"
            )

        side = (
            proposal.side
            .strip()
            .upper()
        )

        if side != "BUY":
            return reject(
                "ONLY_LONG_BUY_REPLACEMENTS_ALLOWED"
            )

        if (
            isinstance(
                proposal.current_quantity,
                bool,
            )
            or proposal.current_quantity <= 0
        ):
            return reject(
                "INVALID_CURRENT_QUANTITY"
            )

        if proposal.current_limit_price <= 0:
            return reject(
                "INVALID_CURRENT_LIMIT_PRICE"
            )

        if proposal.current_filled_quantity < 0:
            return reject(
                "INVALID_CURRENT_FILLED_QUANTITY"
            )

        if (
            proposal.current_filled_quantity
            > proposal.current_quantity
        ):
            return reject(
                "FILLED_QUANTITY_EXCEEDS_ORDER_QUANTITY"
            )

        # Initial replace support deliberately does not modify a
        # partially filled order. That lifecycle is validated
        # separately before it may be enabled.
        if proposal.current_filled_quantity > 0:
            return reject(
                "PARTIALLY_FILLED_REPLACEMENT_NOT_SUPPORTED"
            )

        if (
            isinstance(
                proposal.replacement_quantity,
                bool,
            )
            or proposal.replacement_quantity <= 0
        ):
            return reject(
                "INVALID_REPLACEMENT_QUANTITY"
            )

        if proposal.replacement_limit_price <= 0:
            return reject(
                "INVALID_REPLACEMENT_LIMIT_PRICE"
            )

        if current_order_exposure <= 0:
            return reject(
                "INVALID_CURRENT_ORDER_EXPOSURE"
            )

        if replacement_exposure <= 0:
            return reject(
                "INVALID_REPLACEMENT_EXPOSURE"
            )

        # Fail closed when the supposedly current account
        # snapshot does not contain the reservation belonging to
        # the order we are trying to replace. This catches a
        # stale/lagging open-orders snapshot.
        if (
            account.open_buy_order_exposure
            + 0.01
            < current_order_exposure
        ):
            return reject(
                "CURRENT_ORDER_EXPOSURE_NOT_PRESENT"
            )

        if projected_exposure < -0.01:
            return reject(
                "PROJECTED_EXPOSURE_INVALID"
            )

        # Only the incremental reservation needs new available
        # cash. The old order reservation already exists.
        if (
            additional_exposure
            > account.available_cash
        ):
            return reject(
                "REPLACEMENT_INSUFFICIENT_AVAILABLE_CASH"
            )

        if projected_exposure > hard_cap:
            return reject(
                "HARD_EXPOSURE_CAP_EXCEEDED"
            )

        if (
            enforce_operational_cap
            and projected_exposure
            > operational_cap
        ):
            return reject(
                "OPERATIONAL_EXPOSURE_CAP_EXCEEDED"
            )

        return WebullReplacementSafetyDecision(
            allowed=True,
            reason=(
                "APPROVED_REPLACEMENT_BY_SAFETY_GATE"
            ),
            current_exposure=current_exposure,
            current_order_exposure=(
                current_order_exposure
            ),
            replacement_exposure=(
                replacement_exposure
            ),
            additional_exposure=(
                additional_exposure
            ),
            projected_exposure=(
                projected_exposure
            ),
            available_cash=account.available_cash,
            operational_cap=operational_cap,
            hard_cap=hard_cap,
        )

    @staticmethod
    def real_submission_available() -> bool:
        return WEBULL_ORDER_SUBMISSION_ENABLED
