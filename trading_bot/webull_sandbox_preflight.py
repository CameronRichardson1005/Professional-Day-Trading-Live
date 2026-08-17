from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .config import (
    WEBULL_EXECUTION_MODE,
    WEBULL_MAX_TOTAL_EXPOSURE_DOLLARS,
    WEBULL_OPERATIONAL_EXPOSURE_CAP_DOLLARS,
    WEBULL_REQUIRE_CASH_ACCOUNT,
    WEBULL_SANDBOX_ACCOUNT_ID,
    WEBULL_SANDBOX_APP_KEY,
    WEBULL_SANDBOX_APP_SECRET,
)
from .webull_account_parser import (
    ParsedWebullAccount,
    WebullResponseError,
    parse_account_balance,
    parse_open_orders,
    parse_positions,
)
from .webull_execution import (
    WebullExecutionMode,
    require_safe_execution_mode,
)
from .webull_execution_ledger import (
    WebullExecutionLedger,
    WebullExecutionRecord,
)
from .webull_safety import WebullAccountState
from .webull_sdk_safety import (
    build_quiet_trade_client,
)
from .webull_sandbox_broker import (
    SANDBOX_ENDPOINT,
    WebullBrokerOrderState,
    WebullSandboxBroker,
    WebullSandboxBrokerError,
)


class WebullSandboxPreflightError(RuntimeError):
    pass


@dataclass(frozen=True)
class WebullSandboxSnapshot:
    account_id: str
    account_state: WebullAccountState
    open_order_count: int
    open_client_order_ids: tuple[str, ...]


@dataclass(frozen=True)
class WebullSandboxPreflightReport:
    allowed: bool
    reason: str
    account_id: str
    available_cash: float
    current_exposure: float
    reconciled_orders: int
    active_manual_overrides: int
    open_orders: int


def _account_records(
    payload: Any,
) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        records = payload

    elif isinstance(payload, dict):
        records = None

        for key in (
            "accounts",
            "account_list",
            "data",
        ):
            value = payload.get(key)

            if isinstance(value, list):
                records = value
                break

        if records is None:
            raise WebullSandboxPreflightError(
                "ACCOUNT_LIST_MISSING"
            )

    else:
        raise WebullSandboxPreflightError(
            "ACCOUNT_LIST_INVALID"
        )

    if not all(
        isinstance(item, dict)
        for item in records
    ):
        raise WebullSandboxPreflightError(
            "ACCOUNT_LIST_RECORD_INVALID"
        )

    return records



def list_sandbox_accounts(
    payload: Any,
) -> tuple[ParsedWebullAccount, ...]:
    """
    Strictly parse every account returned by the sandbox
    account-list endpoint without choosing one automatically.
    """

    parsed = []
    seen_ids = set()

    for item in _account_records(payload):
        raw_id = item.get(
            "account_id",
            item.get("accountId"),
        )

        if raw_id in {None, ""}:
            raise WebullSandboxPreflightError(
                "SANDBOX_ACCOUNT_ID_MISSING"
            )

        account_id = str(
            raw_id
        ).strip()

        if not account_id:
            raise WebullSandboxPreflightError(
                "SANDBOX_ACCOUNT_ID_MISSING"
            )

        if account_id in seen_ids:
            raise WebullSandboxPreflightError(
                "DUPLICATE_SANDBOX_ACCOUNT_ID"
            )

        account_type = str(
            item.get(
                "account_type",
                item.get(
                    "accountType",
                    item.get("type", ""),
                ),
            )
        ).strip().upper()

        if account_type not in {
            "CASH",
            "MARGIN",
        }:
            raise WebullSandboxPreflightError(
                "SANDBOX_ACCOUNT_TYPE_INVALID"
            )

        seen_ids.add(account_id)

        parsed.append(
            ParsedWebullAccount(
                account_id=account_id,
                account_type=account_type,
            )
        )

    if not parsed:
        raise WebullSandboxPreflightError(
            "NO_SANDBOX_ACCOUNTS_FOUND"
        )

    return tuple(parsed)

def select_account_by_id(
    payload: Any,
    *,
    account_id: str,
) -> ParsedWebullAccount:
    target = account_id.strip()

    if not target:
        raise WebullSandboxPreflightError(
            "SANDBOX_ACCOUNT_ID_REQUIRED"
        )

    matches = []

    for item in _account_records(payload):
        raw_id = (
            item.get(
                "account_id",
                item.get("accountId"),
            )
        )

        if raw_id is None:
            continue

        if str(raw_id).strip() == target:
            matches.append(item)

    if not matches:
        raise WebullSandboxPreflightError(
            "CONFIGURED_SANDBOX_ACCOUNT_NOT_FOUND"
        )

    if len(matches) != 1:
        raise WebullSandboxPreflightError(
            "DUPLICATE_SANDBOX_ACCOUNT_ID"
        )

    item = matches[0]

    account_type = str(
        item.get(
            "account_type",
            item.get(
                "accountType",
                item.get("type", ""),
            ),
        )
    ).strip().upper()

    if account_type not in {
        "CASH",
        "MARGIN",
    }:
        raise WebullSandboxPreflightError(
            "SANDBOX_ACCOUNT_TYPE_INVALID"
        )

    return ParsedWebullAccount(
        account_id=target,
        account_type=account_type,
    )


def _walk_dicts(value: Any):
    if isinstance(value, dict):
        yield value

        for child in value.values():
            yield from _walk_dicts(child)

    elif isinstance(value, list):
        for child in value:
            yield from _walk_dicts(child)


def _open_client_order_ids(
    payload: Any,
) -> tuple[str, ...]:
    ids = []

    for item in _walk_dicts(payload):
        value = item.get(
            "client_order_id"
        )

        if value in {None, ""}:
            continue

        normalized = str(
            value
        ).strip()

        if (
            normalized
            and normalized not in ids
        ):
            ids.append(normalized)

    return tuple(ids)


def _read_json_response(
    response: Any,
    *,
    label: str,
) -> Any:
    status_code = getattr(
        response,
        "status_code",
        None,
    )

    if status_code != 200:
        raise WebullSandboxPreflightError(
            f"{label}_HTTP_{status_code!r}"
        )

    try:
        return response.json()
    except Exception as error:
        raise WebullSandboxPreflightError(
            f"{label}_INVALID_JSON"
        ) from error


class WebullSandboxAccountSnapshotClient:
    """
    Read-only Webull sandbox account adapter.

    This class exposes no place, replace, or cancel methods.
    """

    def __init__(
        self,
        *,
        trade_client: Any | None = None,
        account_id: str | None = None,
        execution_mode: str = (
            WEBULL_EXECUTION_MODE
        ),
    ) -> None:
        mode = require_safe_execution_mode(
            execution_mode
        )

        if mode is not WebullExecutionMode.SANDBOX:
            raise WebullSandboxPreflightError(
                "SANDBOX_MODE_REQUIRED"
            )

        selected_account = (
            account_id
            if account_id is not None
            else WEBULL_SANDBOX_ACCOUNT_ID
        ).strip()

        if not selected_account:
            raise WebullSandboxPreflightError(
                "SANDBOX_ACCOUNT_ID_REQUIRED"
            )

        self.account_id = selected_account

        if trade_client is not None:
            self._trade_client = trade_client
            return

        if not WEBULL_SANDBOX_APP_KEY:
            raise WebullSandboxPreflightError(
                "SANDBOX_APP_KEY_REQUIRED"
            )

        if not WEBULL_SANDBOX_APP_SECRET:
            raise WebullSandboxPreflightError(
                "SANDBOX_APP_SECRET_REQUIRED"
            )

        self._trade_client = (
            build_quiet_trade_client(
                app_key=WEBULL_SANDBOX_APP_KEY,
                app_secret=WEBULL_SANDBOX_APP_SECRET,
                endpoint=SANDBOX_ENDPOINT,
            )
        )

    def get_snapshot(
        self,
    ) -> WebullSandboxSnapshot:
        try:
            account_payload = (
                _read_json_response(
                    self._trade_client
                    .account_v2
                    .get_account_list(),
                    label="ACCOUNT_LIST",
                )
            )

            account = select_account_by_id(
                account_payload,
                account_id=self.account_id,
            )

            balance_payload = (
                _read_json_response(
                    self._trade_client
                    .account_v2
                    .get_account_balance(
                        self.account_id
                    ),
                    label="ACCOUNT_BALANCE",
                )
            )

            position_payload = (
                _read_json_response(
                    self._trade_client
                    .account_v2
                    .get_account_position(
                        self.account_id
                    ),
                    label="POSITIONS",
                )
            )

            open_order_payload = (
                _read_json_response(
                    self._trade_client
                    .order_v3
                    .get_order_open(
                        self.account_id,
                        page_size=100,
                    ),
                    label="OPEN_ORDERS",
                )
            )

            balance = parse_account_balance(
                balance_payload
            )

            positions = parse_positions(
                position_payload
            )

            open_orders = parse_open_orders(
                open_order_payload
            )

        except WebullResponseError as error:
            raise WebullSandboxPreflightError(
                "SANDBOX_ACCOUNT_RESPONSE_INVALID:"
                f"{error}"
            ) from error

        position_exposure = round(
            sum(
                item.market_value
                for item in positions
            ),
            2,
        )

        open_buy_exposure = round(
            sum(
                item.reserved_exposure
                for item in open_orders
            ),
            2,
        )

        client_ids = (
            _open_client_order_ids(
                open_order_payload
            )
        )

        if len(client_ids) < len(
            open_orders
        ):
            raise WebullSandboxPreflightError(
                "OPEN_ORDER_CLIENT_ID_MISSING"
            )

        return WebullSandboxSnapshot(
            account_id=account.account_id,
            account_state=WebullAccountState(
                account_type=(
                    account.account_type
                ),
                available_cash=(
                    balance.available_cash
                ),
                position_exposure=(
                    position_exposure
                ),
                open_buy_order_exposure=(
                    open_buy_exposure
                ),
                data_is_current=True,
                buying_power=(
                    balance.buying_power
                ),
            ),
            open_order_count=len(
                open_orders
            ),
            open_client_order_ids=(
                client_ids
            ),
        )


def _ledger_status(
    broker_status: str,
) -> str:
    status = broker_status.strip().upper()

    if status in {
        "FILLED",
        "FINAL_FILLED",
    }:
        return "FILLED"

    if status in {
        "PARTIAL_FILLED",
        "PARTIALLY_FILLED",
        "PARTIAL",
    }:
        return "PARTIALLY_FILLED"

    if status in {
        "CANCELLED",
        "CANCELED",
        "EXPIRED",
    }:
        return "CANCELLED"

    if status in {
        "FAILED",
        "REJECTED",
        "PLACE_FAILED",
    }:
        return "REJECTED"

    if status in {
        "CANCEL_PENDING",
        "PENDING_CANCEL",
    }:
        return "CANCEL_PENDING"

    if status in {
        "REPLACE_PENDING",
        "PENDING_REPLACE",
    }:
        return "REPLACE_PENDING"

    if status in {
        "SUBMITTED",
        "NEW",
        "PENDING_NEW",
        "WORKING",
    }:
        return "SUBMITTED"

    return "BROKER_STATE_UNKNOWN"


class WebullSandboxPreflight:
    """
    Fail-closed startup/pre-order verification.

    No method in this class places, replaces, or cancels an
    order.
    """

    TERMINAL_STATUSES = {
        "FILLED",
        "CANCELLED",
        "REJECTED",
    }

    def __init__(
        self,
        *,
        snapshot_client: (
            WebullSandboxAccountSnapshotClient
        ),
        broker: WebullSandboxBroker,
        ledger: WebullExecutionLedger,
    ) -> None:
        self.snapshot_client = (
            snapshot_client
        )
        self.broker = broker
        self.ledger = ledger

    def _record_state(
        self,
        *,
        local: WebullExecutionRecord,
        broker_state: WebullBrokerOrderState,
    ) -> WebullExecutionRecord:
        if (
            broker_state.symbol is not None
            and broker_state.symbol
            != local.symbol
        ):
            self.ledger.mark_manual_override(
                client_order_id=(
                    local.client_order_id
                ),
                reason=(
                    "BROKER_SYMBOL_DIFFERS_"
                    "FROM_LEDGER"
                ),
            )

            raise WebullSandboxPreflightError(
                "BROKER_SYMBOL_MISMATCH:"
                f"{local.client_order_id}"
            )

        if (
            broker_state.side is not None
            and broker_state.side
            != local.side
        ):
            self.ledger.mark_manual_override(
                client_order_id=(
                    local.client_order_id
                ),
                reason=(
                    "BROKER_SIDE_DIFFERS_"
                    "FROM_LEDGER"
                ),
            )

            raise WebullSandboxPreflightError(
                "BROKER_SIDE_MISMATCH:"
                f"{local.client_order_id}"
            )

        quantity_changed = (
            broker_state.quantity
            is not None
            and broker_state.quantity
            != local.quantity
        )

        price_changed = (
            broker_state.limit_price
            is not None
            and abs(
                broker_state.limit_price
                - local.limit_price
            ) > 0.000001
        )

        if (
            quantity_changed
            or price_changed
        ):
            self.ledger.mark_manual_override(
                client_order_id=(
                    local.client_order_id
                ),
                reason=(
                    "BROKER_ORDER_CHANGED_"
                    "OUTSIDE_BOT"
                ),
            )

            self.ledger.record_broker_state(
                client_order_id=(
                    local.client_order_id
                ),
                broker_status=(
                    broker_state.broker_status
                ),
                broker_order_id=(
                    broker_state.broker_order_id
                ),
                filled_quantity=(
                    broker_state.filled_quantity
                ),
                average_fill_price=(
                    broker_state
                    .average_fill_price
                ),
                quantity=(
                    broker_state.quantity
                ),
                limit_price=(
                    broker_state.limit_price
                ),
                status=_ledger_status(
                    broker_state.broker_status
                ),
            )

            raise WebullSandboxPreflightError(
                "MANUAL_BROKER_CHANGE_DETECTED:"
                f"{local.client_order_id}"
            )

        return self.ledger.record_broker_state(
            client_order_id=(
                local.client_order_id
            ),
            broker_status=(
                broker_state.broker_status
            ),
            broker_order_id=(
                broker_state.broker_order_id
            ),
            filled_quantity=(
                broker_state.filled_quantity
            ),
            average_fill_price=(
                broker_state.average_fill_price
            ),
            quantity=(
                broker_state.quantity
            ),
            limit_price=(
                broker_state.limit_price
            ),
            status=_ledger_status(
                broker_state.broker_status
            ),
        )

    def run(
        self,
    ) -> WebullSandboxPreflightReport:
        snapshot = (
            self.snapshot_client
            .get_snapshot()
        )

        account = snapshot.account_state

        if (
            WEBULL_REQUIRE_CASH_ACCOUNT
            and account.account_type
            .strip()
            .upper()
            != "CASH"
        ):
            raise WebullSandboxPreflightError(
                "CASH_ACCOUNT_REQUIRED"
            )

        if not account.data_is_current:
            raise WebullSandboxPreflightError(
                "ACCOUNT_DATA_STALE_OR_UNKNOWN"
            )

        if (
            account.current_total_exposure
            > WEBULL_MAX_TOTAL_EXPOSURE_DOLLARS
        ):
            raise WebullSandboxPreflightError(
                "HARD_EXPOSURE_CAP_ALREADY_EXCEEDED"
            )

        if (
            account.current_total_exposure
            > WEBULL_OPERATIONAL_EXPOSURE_CAP_DOLLARS
        ):
            raise WebullSandboxPreflightError(
                "OPERATIONAL_EXPOSURE_CAP_ALREADY_EXCEEDED"
            )

        records = self.ledger.load()
        reconciled = 0

        # Reconcile every non-terminal locally tracked broker
        # order using Order Detail by client_order_id.
        for record in list(
            records.values()
        ):
            if (
                record.status
                in self.TERMINAL_STATUSES
            ):
                continue

            try:
                broker_state = (
                    self.broker
                    .get_order_detail(
                        client_order_id=(
                            record.client_order_id
                        ),
                    )
                )
            except WebullSandboxBrokerError as error:
                self.ledger.mark_operation_state(
                    client_order_id=(
                        record.client_order_id
                    ),
                    status=(
                        "BROKER_STATE_UNKNOWN"
                    ),
                    last_error=str(error),
                )

                raise WebullSandboxPreflightError(
                    "ORDER_RECONCILIATION_FAILED:"
                    f"{record.client_order_id}:"
                    f"{error}"
                ) from error

            updated = self._record_state(
                local=record,
                broker_state=broker_state,
            )

            reconciled += 1

            if (
                updated.status
                == "BROKER_STATE_UNKNOWN"
            ):
                raise WebullSandboxPreflightError(
                    "UNKNOWN_BROKER_ORDER_STATUS:"
                    f"{record.client_order_id}"
                )

        records = self.ledger.load()

        # If an order appears in Webull Open Orders but has no
        # local execution record, fail closed. This includes
        # manually created broker orders.
        for client_order_id in (
            snapshot.open_client_order_ids
        ):
            if client_order_id not in records:
                raise WebullSandboxPreflightError(
                    "UNTRACKED_BROKER_OPEN_ORDER:"
                    f"{client_order_id}"
                )

        # If Open Orders still shows one of our terminal orders,
        # use Order Detail rather than trusting the potentially
        # delayed open-order list.
        for client_order_id in (
            snapshot.open_client_order_ids
        ):
            record = records.get(
                client_order_id
            )

            if (
                record is None
                or record.status
                not in self.TERMINAL_STATUSES
            ):
                continue

            try:
                state = (
                    self.broker
                    .get_order_detail(
                        client_order_id=(
                            client_order_id
                        ),
                    )
                )
            except WebullSandboxBrokerError as error:
                raise WebullSandboxPreflightError(
                    "TERMINAL_ORDER_RECHECK_FAILED:"
                    f"{client_order_id}:"
                    f"{error}"
                ) from error

            broker_ledger_status = (
                _ledger_status(
                    state.broker_status
                )
            )

            if (
                broker_ledger_status
                not in self.TERMINAL_STATUSES
            ):
                raise WebullSandboxPreflightError(
                    "TERMINAL_LEDGER_BROKER_CONFLICT:"
                    f"{client_order_id}"
                )

        records = self.ledger.load()

        active_manual_overrides = [
            record
            for record in records.values()
            if (
                record.manual_override
                and record.status
                not in self.TERMINAL_STATUSES
            )
        ]

        if active_manual_overrides:
            ids = ",".join(
                sorted(
                    record.client_order_id
                    for record
                    in active_manual_overrides
                )
            )

            raise WebullSandboxPreflightError(
                "ACTIVE_MANUAL_OVERRIDE:"
                f"{ids}"
            )

        unresolved = [
            record
            for record in records.values()
            if record.status in {
                "SUBMISSION_UNKNOWN",
                "BROKER_STATE_UNKNOWN",
                "ERROR",
            }
        ]

        if unresolved:
            ids = ",".join(
                sorted(
                    record.client_order_id
                    for record in unresolved
                )
            )

            raise WebullSandboxPreflightError(
                "UNRESOLVED_EXECUTION_STATE:"
                f"{ids}"
            )

        return WebullSandboxPreflightReport(
            allowed=True,
            reason="SANDBOX_PREFLIGHT_PASSED",
            account_id=snapshot.account_id,
            available_cash=(
                account.available_cash
            ),
            current_exposure=(
                account.current_total_exposure
            ),
            reconciled_orders=reconciled,
            active_manual_overrides=0,
            open_orders=(
                snapshot.open_order_count
            ),
        )
