from __future__ import annotations

import random
import tempfile

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from .webull_account_parser import (
    ParsedWebullOpenOrder,
    ParsedWebullPosition,
)
from .webull_execution import (
    WebullTradeIntent,
)
from .webull_execution_ledger import (
    WebullExecutionLedger,
)
from .webull_execution_manager import (
    WebullExecutionManagerError,
    WebullSandboxExecutionManager,
)
from .webull_reduce_only_close import (
    WebullReduceOnlyCloseLedger,
    build_reduce_only_close_intent,
)
from .webull_reduce_only_close_manager import (
    WebullReduceOnlyCloseManagerError,
    WebullSandboxReduceOnlyCloseManager,
)
from .webull_safety import (
    WebullAccountState,
)
from .webull_sandbox_broker import (
    WebullSandboxBroker,
)


NOW = datetime(
    2026,
    8,
    17,
    20,
    0,
    tzinfo=UTC,
)


class ManagerStressError(RuntimeError):
    pass


class _FakeResponse:
    def __init__(
        self,
        *,
        payload=None,
        status_code=200,
    ):
        self.payload = (
            {}
            if payload is None
            else payload
        )
        self.status_code = status_code

    def json(self):
        return self.payload


class _FakeOrderV3:
    """
    Deliberately has no network capability.

    The real WebullSandboxBroker adapter is exercised against
    this object, so broker payload construction/error wrapping
    remain part of the stress test.
    """

    def __init__(
        self,
        *,
        detail_payload,
    ):
        self.detail_payload = dict(
            detail_payload
        )

        self.place_calls = []
        self.replace_calls = []
        self.cancel_calls = []
        self.detail_calls = []

        self.place_behavior = "SUCCESS"
        self.replace_behavior = "SUCCESS"
        self.cancel_behavior = "SUCCESS"

    def place_order(
        self,
        account_id,
        orders,
        client_combo_order_id=None,
    ):
        self.place_calls.append(
            (
                account_id,
                orders,
            )
        )

        if (
            self.place_behavior
            == "TIMEOUT_ACCEPT"
        ):
            raise TimeoutError(
                "simulated accepted placement timeout"
            )

        return _FakeResponse()

    def replace_order(
        self,
        account_id,
        modify_orders,
    ):
        self.replace_calls.append(
            (
                account_id,
                modify_orders,
            )
        )

        item = modify_orders[0]

        if self.replace_behavior in {
            "SUCCESS",
            "TIMEOUT_ACCEPT",
        }:
            self.detail_payload[
                "quantity"
            ] = item["quantity"]

            self.detail_payload[
                "limit_price"
            ] = item["limit_price"]

        if (
            self.replace_behavior
            == "TIMEOUT_ACCEPT"
        ):
            raise TimeoutError(
                "simulated accepted replacement timeout"
            )

        return _FakeResponse()

    def cancel_order(
        self,
        account_id,
        client_order_id,
    ):
        self.cancel_calls.append(
            (
                account_id,
                client_order_id,
            )
        )

        if self.cancel_behavior in {
            "SUCCESS",
            "TIMEOUT_ACCEPT",
        }:
            self.detail_payload[
                "status"
            ] = "CANCELLED"

        if (
            self.cancel_behavior
            == "TIMEOUT_ACCEPT"
        ):
            raise TimeoutError(
                "simulated accepted cancellation timeout"
            )

        return _FakeResponse()

    def get_order_detail(
        self,
        account_id,
        client_order_id,
    ):
        self.detail_calls.append(
            (
                account_id,
                client_order_id,
            )
        )

        return _FakeResponse(
            payload=dict(
                self.detail_payload
            )
        )


class _FakeTradeClient:
    def __init__(
        self,
        *,
        detail_payload,
    ):
        self.order_v3 = _FakeOrderV3(
            detail_payload=detail_payload
        )


class _FakeSnapshotClient:
    def __init__(
        self,
        value,
    ):
        self.value = value
        self.calls = 0

    def get_snapshot(self):
        self.calls += 1
        return self.value


@dataclass(frozen=True)
class WebullManagerStressReport:
    seed: int
    scenarios: int

    entry_cases: int
    close_cases: int

    entry_safety_rejections: int
    duplicate_entry_rejections: int
    ambiguous_entry_recoveries: int

    successful_replacements: int
    pending_replacement_recoveries: int
    ambiguous_replacement_recoveries: int
    disarmed_replacement_rejections: int

    successful_entry_cancels: int
    ambiguous_entry_cancel_recoveries: int
    pending_entry_cancel_recoveries: int

    disarmed_close_rejections: int
    stale_close_rejections: int
    changed_position_rejections: int
    existing_sell_rejections: int
    margin_close_rejections: int

    full_close_reconciliations: int
    partial_close_reconciliations: int
    duplicate_close_rejections: int
    ambiguous_close_recoveries: int
    ambiguous_close_cancel_recoveries: int
    pending_close_cancel_recoveries: int

    durable_restart_recoveries: int
    invariant_failures: int


def _position(
    quantity: float = 2.0,
) -> ParsedWebullPosition:
    return ParsedWebullPosition(
        symbol="SOUN",
        quantity=quantity,
        market_price=20.0,
        market_value=round(
            quantity * 20.0,
            2,
        ),
    )


def _snapshot(
    *,
    quantity: float = 2.0,
    current: bool = True,
    account_type: str = "CASH",
    open_sell: bool = False,
):
    open_orders = ()

    if open_sell:
        open_orders = (
            ParsedWebullOpenOrder(
                symbol="SOUN",
                side="SELL",
                remaining_quantity=1.0,
                limit_price=20.0,
                reserved_exposure=0.0,
            ),
        )

    return SimpleNamespace(
        account_state=SimpleNamespace(
            account_type=account_type,
            data_is_current=current,
        ),
        positions=(
            _position(
                quantity
            ),
        ),
        open_orders=open_orders,
    )


def _entry_intent(
    *,
    key: str,
    created_at: datetime,
) -> WebullTradeIntent:
    return WebullTradeIntent(
        client_order_id=key,
        strategy_name="MANAGER_STRESS",
        symbol="SOUN",
        side="BUY",
        quantity=2,
        limit_price=20.0,
        created_at=created_at,
    )


def _entry_account(
    *,
    available_cash: float = 1000.0,
    current: bool = True,
) -> WebullAccountState:
    return WebullAccountState(
        account_type="CASH",
        available_cash=available_cash,
        position_exposure=0.0,
        open_buy_order_exposure=0.0,
        data_is_current=current,
        buying_power=available_cash,
    )


def _replacement_account():
    return WebullAccountState(
        account_type="CASH",
        available_cash=1000.0,
        position_exposure=0.0,
        open_buy_order_exposure=40.0,
        data_is_current=True,
        buying_power=1000.0,
    )


def _entry_manager(
    *,
    path: Path,
    client: _FakeTradeClient,
    clock,
):
    broker = WebullSandboxBroker(
        trade_client=client,
        account_id="fake-sandbox-account",
        execution_mode="SANDBOX",
        submission_enabled=True,
    )

    ledger = WebullExecutionLedger(
        path,
        clock=clock,
    )

    manager = WebullSandboxExecutionManager(
        broker=broker,
        ledger=ledger,
        execution_mode="SANDBOX",
    )

    return manager, ledger


def _close_manager(
    *,
    path: Path,
    client: _FakeTradeClient,
    snapshot_client: _FakeSnapshotClient,
    clock,
):
    broker = WebullSandboxBroker(
        trade_client=client,
        account_id="fake-sandbox-account",
        execution_mode="SANDBOX",
        submission_enabled=False,
    )

    ledger = WebullReduceOnlyCloseLedger(
        path,
        clock=clock,
    )

    manager = (
        WebullSandboxReduceOnlyCloseManager(
            broker=broker,
            ledger=ledger,
            snapshot_client=snapshot_client,
            execution_mode="SANDBOX",
        )
    )

    return manager, ledger


def _entry_detail(
    key: str,
):
    return {
        "client_order_id": key,
        "order_id": (
            "broker-" + key
        ),
        "status": "SUBMITTED",
        "quantity": "2",
        "limit_price": "20.0000",
        "filled_quantity": "0",
        "filled_price": None,
    }


def _close_detail(
    key: str,
):
    return {
        "client_order_id": key,
        "order_id": (
            "broker-" + key
        ),
        "status": "SUBMITTED",
        "symbol": "SOUN",
        "side": "SELL",
        "quantity": "2",
        "limit_price": "19.0000",
        "filled_quantity": "0",
        "filled_price": None,
    }


def run_webull_manager_stress(
    *,
    scenarios: int = 1000,
    seed: int = 20260817,
) -> WebullManagerStressReport:
    if (
        isinstance(
            scenarios,
            bool,
        )
        or not isinstance(
            scenarios,
            int,
        )
        or scenarios <= 0
    ):
        raise ManagerStressError(
            "INVALID_MANAGER_STRESS_SCENARIOS"
        )

    rng = random.Random(
        seed
    )

    counts = {
        "entry_safety_rejections": 0,
        "duplicate_entry_rejections": 0,
        "ambiguous_entry_recoveries": 0,
        "successful_replacements": 0,
        "pending_replacement_recoveries": 0,
        "ambiguous_replacement_recoveries": 0,
        "disarmed_replacement_rejections": 0,
        "successful_entry_cancels": 0,
        "ambiguous_entry_cancel_recoveries": 0,
        "pending_entry_cancel_recoveries": 0,
        "disarmed_close_rejections": 0,
        "stale_close_rejections": 0,
        "changed_position_rejections": 0,
        "existing_sell_rejections": 0,
        "margin_close_rejections": 0,
        "full_close_reconciliations": 0,
        "partial_close_reconciliations": 0,
        "duplicate_close_rejections": 0,
        "ambiguous_close_recoveries": 0,
        "ambiguous_close_cancel_recoveries": 0,
        "pending_close_cancel_recoveries": 0,
        "durable_restart_recoveries": 0,
        "invariant_failures": 0,
    }

    with tempfile.TemporaryDirectory(
        prefix="webull-manager-stress-"
    ) as directory:
        root = Path(
            directory
        )

        entry_path = (
            root
            / "entry.json"
        )

        close_path = (
            root
            / "close.json"
        )

        for index in range(
            scenarios
        ):
            for path in (
                entry_path,
                close_path,
                entry_path.with_suffix(
                    ".json.tmp"
                ),
                close_path.with_suffix(
                    ".json.tmp"
                ),
            ):
                path.unlink(
                    missing_ok=True
                )

            now = (
                NOW
                + timedelta(
                    seconds=index
                )
            )

            clock = (
                lambda value=now:
                value
            )

            entry_key = (
                f"entry-{seed}-{index}"
            )

            entry_client = (
                _FakeTradeClient(
                    detail_payload=(
                        _entry_detail(
                            entry_key
                        )
                    )
                )
            )

            entry_manager, entry_ledger = (
                _entry_manager(
                    path=entry_path,
                    client=entry_client,
                    clock=clock,
                )
            )

            intent = _entry_intent(
                key=entry_key,
                created_at=now,
            )

            entry_case = (
                rng.randrange(9)
            )

            if entry_case == 0:
                try:
                    entry_manager.submit(
                        intent=intent,
                        account=(
                            _entry_account(
                                available_cash=1.0
                            )
                        ),
                    )

                except WebullExecutionManagerError:
                    pass

                else:
                    raise ManagerStressError(
                        "ENTRY_SAFETY_DID_NOT_REJECT"
                    )

                if (
                    entry_client
                    .order_v3
                    .place_calls
                ):
                    raise ManagerStressError(
                        "ENTRY_SAFETY_REACHED_BROKER"
                    )

                if entry_ledger.load():
                    raise ManagerStressError(
                        "ENTRY_SAFETY_POLLUTED_LEDGER"
                    )

                counts[
                    "entry_safety_rejections"
                ] += 1

            else:
                if entry_case == 2:
                    (
                        entry_client
                        .order_v3
                        .place_behavior
                    ) = "TIMEOUT_ACCEPT"

                try:
                    entry_manager.submit(
                        intent=intent,
                        account=_entry_account(),
                    )

                except WebullExecutionManagerError:
                    if entry_case != 2:
                        raise

                    stored = (
                        entry_ledger.load()[
                            entry_key
                        ]
                    )

                    if (
                        stored.status
                        != "SUBMISSION_UNKNOWN"
                    ):
                        raise ManagerStressError(
                            "ENTRY_AMBIGUITY_NOT_DURABLE"
                        )

                    before = len(
                        entry_client
                        .order_v3
                        .place_calls
                    )

                    try:
                        entry_manager.submit(
                            intent=intent,
                            account=_entry_account(),
                        )

                    except WebullExecutionManagerError:
                        pass

                    else:
                        raise ManagerStressError(
                            "DUPLICATE_ENTRY_ACCEPTED"
                        )

                    after = len(
                        entry_client
                        .order_v3
                        .place_calls
                    )

                    if after != before:
                        raise ManagerStressError(
                            "AMBIGUOUS_ENTRY_RETRIED"
                        )

                    counts[
                        "duplicate_entry_rejections"
                    ] += 1

                    entry_manager, entry_ledger = (
                        _entry_manager(
                            path=entry_path,
                            client=entry_client,
                            clock=clock,
                        )
                    )

                    recovered = (
                        entry_manager.reconcile(
                            client_order_id=(
                                entry_key
                            )
                        )
                    )

                    if (
                        recovered.status
                        != "SUBMITTED"
                    ):
                        raise ManagerStressError(
                            "ENTRY_AMBIGUITY_NOT_RECOVERED"
                        )

                    counts[
                        "ambiguous_entry_recoveries"
                    ] += 1

                    counts[
                        "durable_restart_recoveries"
                    ] += 1

                if entry_case == 1:
                    before = len(
                        entry_client
                        .order_v3
                        .place_calls
                    )

                    try:
                        entry_manager.submit(
                            intent=intent,
                            account=_entry_account(),
                        )

                    except WebullExecutionManagerError:
                        pass

                    else:
                        raise ManagerStressError(
                            "DUPLICATE_ENTRY_ACCEPTED"
                        )

                    if (
                        len(
                            entry_client
                            .order_v3
                            .place_calls
                        )
                        != before
                    ):
                        raise ManagerStressError(
                            "DUPLICATE_ENTRY_REACHED_BROKER"
                        )

                    counts[
                        "duplicate_entry_rejections"
                    ] += 1

                if entry_case == 3:
                    result = (
                        entry_manager
                        .replace_manual(
                            client_order_id=(
                                entry_key
                            ),
                            quantity=3,
                            limit_price=19.5,
                            reason=(
                                "STRESS_REPLACE"
                            ),
                            account=(
                                _replacement_account()
                            ),
                            management_armed=True,
                        )
                    )

                    if (
                        result.quantity != 3
                        or abs(
                            result.limit_price
                            - 19.5
                        )
                        > 0.000001
                    ):
                        raise ManagerStressError(
                            "REPLACEMENT_NOT_APPLIED"
                        )

                    counts[
                        "successful_replacements"
                    ] += 1

                if entry_case == 4:
                    (
                        entry_client
                        .order_v3
                        .replace_behavior
                    ) = "DELAYED"

                    pending = (
                        entry_manager
                        .replace_manual(
                            client_order_id=(
                                entry_key
                            ),
                            quantity=3,
                            limit_price=19.5,
                            reason=(
                                "STRESS_DELAYED_REPLACE"
                            ),
                            account=(
                                _replacement_account()
                            ),
                            management_armed=True,
                        )
                    )

                    if (
                        pending.status
                        != "REPLACE_PENDING"
                    ):
                        raise ManagerStressError(
                            "REPLACE_DID_NOT_STAY_PENDING"
                        )

                    entry_client.order_v3.detail_payload[
                        "quantity"
                    ] = "3"

                    entry_client.order_v3.detail_payload[
                        "limit_price"
                    ] = "19.5000"

                    entry_manager, entry_ledger = (
                        _entry_manager(
                            path=entry_path,
                            client=entry_client,
                            clock=clock,
                        )
                    )

                    recovered = (
                        entry_manager
                        .reconcile_replacement(
                            client_order_id=(
                                entry_key
                            ),
                            quantity=3,
                            limit_price=19.5,
                        )
                    )

                    if (
                        recovered
                        .replace_requested_quantity
                        is not None
                    ):
                        raise ManagerStressError(
                            "REPLACE_REQUEST_NOT_CLEARED"
                        )

                    counts[
                        "pending_replacement_recoveries"
                    ] += 1

                    counts[
                        "durable_restart_recoveries"
                    ] += 1

                if entry_case == 5:
                    (
                        entry_client
                        .order_v3
                        .replace_behavior
                    ) = "TIMEOUT_ACCEPT"

                    try:
                        entry_manager.replace_manual(
                            client_order_id=(
                                entry_key
                            ),
                            quantity=3,
                            limit_price=19.5,
                            reason=(
                                "STRESS_AMBIGUOUS_REPLACE"
                            ),
                            account=(
                                _replacement_account()
                            ),
                            management_armed=True,
                        )

                    except WebullExecutionManagerError:
                        pass

                    else:
                        raise ManagerStressError(
                            "AMBIGUOUS_REPLACE_DID_NOT_FAIL"
                        )

                    stored = (
                        entry_ledger.load()[
                            entry_key
                        ]
                    )

                    if (
                        stored.status
                        != "BROKER_STATE_UNKNOWN"
                        or stored
                        .replace_requested_quantity
                        != 3
                    ):
                        raise ManagerStressError(
                            "AMBIGUOUS_REPLACE_NOT_DURABLE"
                        )

                    if (
                        len(
                            entry_client
                            .order_v3
                            .replace_calls
                        )
                        != 1
                    ):
                        raise ManagerStressError(
                            "AMBIGUOUS_REPLACE_RETRIED"
                        )

                    entry_manager, entry_ledger = (
                        _entry_manager(
                            path=entry_path,
                            client=entry_client,
                            clock=clock,
                        )
                    )

                    recovered = (
                        entry_manager
                        .reconcile_replacement(
                            client_order_id=(
                                entry_key
                            ),
                            quantity=3,
                            limit_price=19.5,
                        )
                    )

                    if (
                        recovered
                        .replace_requested_quantity
                        is not None
                    ):
                        raise ManagerStressError(
                            "AMBIGUOUS_REPLACE_NOT_RECOVERED"
                        )

                    counts[
                        "ambiguous_replacement_recoveries"
                    ] += 1

                    counts[
                        "durable_restart_recoveries"
                    ] += 1

                if entry_case == 6:
                    before = len(
                        entry_client
                        .order_v3
                        .replace_calls
                    )

                    try:
                        entry_manager.replace_manual(
                            client_order_id=(
                                entry_key
                            ),
                            quantity=3,
                            limit_price=19.5,
                            reason=(
                                "STRESS_DISARMED_REPLACE"
                            ),
                            account=(
                                _replacement_account()
                            ),
                            management_armed=False,
                        )

                    except WebullExecutionManagerError:
                        pass

                    else:
                        raise ManagerStressError(
                            "DISARMED_REPLACE_ACCEPTED"
                        )

                    if (
                        len(
                            entry_client
                            .order_v3
                            .replace_calls
                        )
                        != before
                    ):
                        raise ManagerStressError(
                            "DISARMED_REPLACE_REACHED_BROKER"
                        )

                    counts[
                        "disarmed_replacement_rejections"
                    ] += 1

                if entry_case == 7:
                    (
                        entry_client
                        .order_v3
                        .cancel_behavior
                    ) = "TIMEOUT_ACCEPT"

                    try:
                        entry_manager.cancel_manual(
                            client_order_id=(
                                entry_key
                            ),
                            reason=(
                                "STRESS_AMBIGUOUS_CANCEL"
                            ),
                        )

                    except WebullExecutionManagerError:
                        pass

                    else:
                        raise ManagerStressError(
                            "AMBIGUOUS_CANCEL_DID_NOT_FAIL"
                        )

                    if (
                        len(
                            entry_client
                            .order_v3
                            .cancel_calls
                        )
                        != 1
                    ):
                        raise ManagerStressError(
                            "AMBIGUOUS_CANCEL_RETRIED"
                        )

                    entry_manager, entry_ledger = (
                        _entry_manager(
                            path=entry_path,
                            client=entry_client,
                            clock=clock,
                        )
                    )

                    recovered = (
                        entry_manager.reconcile(
                            client_order_id=(
                                entry_key
                            )
                        )
                    )

                    if (
                        recovered.status
                        != "CANCELLED"
                    ):
                        raise ManagerStressError(
                            "AMBIGUOUS_CANCEL_NOT_RECOVERED"
                        )

                    counts[
                        "ambiguous_entry_cancel_recoveries"
                    ] += 1

                    counts[
                        "durable_restart_recoveries"
                    ] += 1

                elif entry_case == 8:
                    (
                        entry_client
                        .order_v3
                        .cancel_behavior
                    ) = "DELAYED"

                    pending = (
                        entry_manager.cancel_manual(
                            client_order_id=(
                                entry_key
                            ),
                            reason=(
                                "STRESS_DELAYED_CANCEL"
                            ),
                        )
                    )

                    if (
                        pending.status
                        != "CANCEL_PENDING"
                    ):
                        raise ManagerStressError(
                            "ENTRY_CANCEL_NOT_PENDING"
                        )

                    entry_client.order_v3.detail_payload[
                        "status"
                    ] = "CANCELLED"

                    entry_manager, entry_ledger = (
                        _entry_manager(
                            path=entry_path,
                            client=entry_client,
                            clock=clock,
                        )
                    )

                    recovered = (
                        entry_manager.reconcile(
                            client_order_id=(
                                entry_key
                            )
                        )
                    )

                    if (
                        recovered.status
                        != "CANCELLED"
                    ):
                        raise ManagerStressError(
                            "PENDING_CANCEL_NOT_RECOVERED"
                        )

                    counts[
                        "pending_entry_cancel_recoveries"
                    ] += 1

                    counts[
                        "durable_restart_recoveries"
                    ] += 1

                elif entry_case != 7:
                    result = (
                        entry_manager
                        .cancel_manual(
                            client_order_id=(
                                entry_key
                            ),
                            reason="STRESS_CLEANUP",
                        )
                    )

                    if (
                        result.status
                        != "CANCELLED"
                    ):
                        raise ManagerStressError(
                            "ENTRY_CLEANUP_NOT_CANCELLED"
                        )

                    counts[
                        "successful_entry_cancels"
                    ] += 1

            close_key = (
                f"close-{seed}-{index}"
            )

            close_client = (
                _FakeTradeClient(
                    detail_payload=(
                        _close_detail(
                            close_key
                        )
                    )
                )
            )

            snapshot_client = (
                _FakeSnapshotClient(
                    _snapshot()
                )
            )

            close_manager, close_ledger = (
                _close_manager(
                    path=close_path,
                    client=close_client,
                    snapshot_client=(
                        snapshot_client
                    ),
                    clock=clock,
                )
            )

            close_intent = (
                build_reduce_only_close_intent(
                    client_order_id=(
                        close_key
                    ),
                    positions=(
                        _position(),
                    ),
                    symbol="SOUN",
                    quantity=2,
                    limit_price=19.0,
                    created_at=now,
                )
            )

            close_case = (
                rng.randrange(10)
            )

            if close_case == 0:
                try:
                    close_manager.submit(
                        intent=close_intent,
                        management_armed=False,
                    )

                except WebullReduceOnlyCloseManagerError:
                    pass

                else:
                    raise ManagerStressError(
                        "DISARMED_CLOSE_ACCEPTED"
                    )

                if (
                    close_client
                    .order_v3
                    .place_calls
                ):
                    raise ManagerStressError(
                        "DISARMED_CLOSE_REACHED_BROKER"
                    )

                counts[
                    "disarmed_close_rejections"
                ] += 1

            elif close_case in {
                1,
                2,
                3,
                4,
            }:
                if close_case == 1:
                    snapshot_client.value = (
                        _snapshot(
                            current=False
                        )
                    )

                    counter = (
                        "stale_close_rejections"
                    )

                elif close_case == 2:
                    snapshot_client.value = (
                        _snapshot(
                            quantity=1.0
                        )
                    )

                    counter = (
                        "changed_position_rejections"
                    )

                elif close_case == 3:
                    snapshot_client.value = (
                        _snapshot(
                            open_sell=True
                        )
                    )

                    counter = (
                        "existing_sell_rejections"
                    )

                else:
                    snapshot_client.value = (
                        _snapshot(
                            account_type="MARGIN"
                        )
                    )

                    counter = (
                        "margin_close_rejections"
                    )

                try:
                    close_manager.submit(
                        intent=close_intent,
                        management_armed=True,
                    )

                except WebullReduceOnlyCloseManagerError:
                    pass

                else:
                    raise ManagerStressError(
                        "UNSAFE_CLOSE_ACCEPTED"
                    )

                if (
                    close_client
                    .order_v3
                    .place_calls
                ):
                    raise ManagerStressError(
                        "UNSAFE_CLOSE_REACHED_BROKER"
                    )

                counts[
                    counter
                ] += 1

            elif close_case == 5:
                close_manager.submit(
                    intent=close_intent,
                    management_armed=True,
                )

                close_client.order_v3.detail_payload.update({
                    "status": "FILLED",
                    "filled_quantity": "2",
                    "filled_price": "19.0000",
                })

                reconciled = (
                    close_manager.reconcile(
                        client_order_id=(
                            close_key
                        )
                    )
                )

                if (
                    reconciled.status
                    != "FILLED"
                ):
                    raise ManagerStressError(
                        "FULL_CLOSE_NOT_FILLED"
                    )

                close_manager, close_ledger = (
                    _close_manager(
                        path=close_path,
                        client=close_client,
                        snapshot_client=(
                            snapshot_client
                        ),
                        clock=clock,
                    )
                )

                final = (
                    close_manager
                    .reconcile_position(
                        client_order_id=(
                            close_key
                        ),
                        positions=(),
                    )
                )

                if not (
                    final.position_reconciled
                ):
                    raise ManagerStressError(
                        "FULL_CLOSE_POSITION_NOT_RECONCILED"
                    )

                counts[
                    "full_close_reconciliations"
                ] += 1

                counts[
                    "durable_restart_recoveries"
                ] += 1

            elif close_case == 6:
                close_manager.submit(
                    intent=close_intent,
                    management_armed=True,
                )

                close_client.order_v3.detail_payload.update({
                    "status": "PARTIALLY_FILLED",
                    "filled_quantity": "1",
                    "filled_price": "19.0000",
                })

                close_manager.reconcile(
                    client_order_id=(
                        close_key
                    )
                )

                close_manager, close_ledger = (
                    _close_manager(
                        path=close_path,
                        client=close_client,
                        snapshot_client=(
                            snapshot_client
                        ),
                        clock=clock,
                    )
                )

                cancelled = (
                    close_manager.cancel(
                        client_order_id=(
                            close_key
                        )
                    )
                )

                if (
                    cancelled.status
                    != "CANCELLED"
                ):
                    raise ManagerStressError(
                        "PARTIAL_CLOSE_NOT_CANCELLED"
                    )

                final = (
                    close_manager
                    .reconcile_position(
                        client_order_id=(
                            close_key
                        ),
                        positions=(
                            _position(
                                quantity=1.0
                            ),
                        ),
                    )
                )

                if not (
                    final.position_reconciled
                ):
                    raise ManagerStressError(
                        "PARTIAL_POSITION_NOT_RECONCILED"
                    )

                counts[
                    "partial_close_reconciliations"
                ] += 1

                counts[
                    "durable_restart_recoveries"
                ] += 1

            elif close_case == 7:
                (
                    close_client
                    .order_v3
                    .place_behavior
                ) = "TIMEOUT_ACCEPT"

                try:
                    close_manager.submit(
                        intent=close_intent,
                        management_armed=True,
                    )

                except WebullReduceOnlyCloseManagerError:
                    pass

                else:
                    raise ManagerStressError(
                        "AMBIGUOUS_CLOSE_DID_NOT_FAIL"
                    )

                if (
                    close_ledger.load()[
                        close_key
                    ].status
                    != "SUBMISSION_UNKNOWN"
                ):
                    raise ManagerStressError(
                        "AMBIGUOUS_CLOSE_NOT_DURABLE"
                    )

                before = len(
                    close_client
                    .order_v3
                    .place_calls
                )

                try:
                    close_manager.submit(
                        intent=close_intent,
                        management_armed=True,
                    )

                except WebullReduceOnlyCloseManagerError:
                    pass

                else:
                    raise ManagerStressError(
                        "DUPLICATE_CLOSE_ACCEPTED"
                    )

                if (
                    len(
                        close_client
                        .order_v3
                        .place_calls
                    )
                    != before
                ):
                    raise ManagerStressError(
                        "AMBIGUOUS_CLOSE_RETRIED"
                    )

                counts[
                    "duplicate_close_rejections"
                ] += 1

                close_manager, close_ledger = (
                    _close_manager(
                        path=close_path,
                        client=close_client,
                        snapshot_client=(
                            snapshot_client
                        ),
                        clock=clock,
                    )
                )

                recovered = (
                    close_manager.reconcile(
                        client_order_id=(
                            close_key
                        )
                    )
                )

                if (
                    recovered.status
                    != "SUBMITTED"
                ):
                    raise ManagerStressError(
                        "AMBIGUOUS_CLOSE_NOT_RECOVERED"
                    )

                close_manager.cancel(
                    client_order_id=(
                        close_key
                    )
                )

                counts[
                    "ambiguous_close_recoveries"
                ] += 1

                counts[
                    "durable_restart_recoveries"
                ] += 1

            elif close_case == 8:
                close_manager.submit(
                    intent=close_intent,
                    management_armed=True,
                )

                (
                    close_client
                    .order_v3
                    .cancel_behavior
                ) = "TIMEOUT_ACCEPT"

                try:
                    close_manager.cancel(
                        client_order_id=(
                            close_key
                        )
                    )

                except WebullReduceOnlyCloseManagerError:
                    pass

                else:
                    raise ManagerStressError(
                        "AMBIGUOUS_CLOSE_CANCEL_DID_NOT_FAIL"
                    )

                if (
                    len(
                        close_client
                        .order_v3
                        .cancel_calls
                    )
                    != 1
                ):
                    raise ManagerStressError(
                        "AMBIGUOUS_CLOSE_CANCEL_RETRIED"
                    )

                close_manager, close_ledger = (
                    _close_manager(
                        path=close_path,
                        client=close_client,
                        snapshot_client=(
                            snapshot_client
                        ),
                        clock=clock,
                    )
                )

                recovered = (
                    close_manager.reconcile(
                        client_order_id=(
                            close_key
                        )
                    )
                )

                if (
                    recovered.status
                    != "CANCELLED"
                ):
                    raise ManagerStressError(
                        "AMBIGUOUS_CLOSE_CANCEL_NOT_RECOVERED"
                    )

                counts[
                    "ambiguous_close_cancel_recoveries"
                ] += 1

                counts[
                    "durable_restart_recoveries"
                ] += 1

            else:
                close_manager.submit(
                    intent=close_intent,
                    management_armed=True,
                )

                (
                    close_client
                    .order_v3
                    .cancel_behavior
                ) = "DELAYED"

                pending = (
                    close_manager.cancel(
                        client_order_id=(
                            close_key
                        )
                    )
                )

                if (
                    pending.status
                    != "CANCEL_PENDING"
                ):
                    raise ManagerStressError(
                        "CLOSE_CANCEL_NOT_PENDING"
                    )

                close_client.order_v3.detail_payload[
                    "status"
                ] = "CANCELLED"

                close_manager, close_ledger = (
                    _close_manager(
                        path=close_path,
                        client=close_client,
                        snapshot_client=(
                            snapshot_client
                        ),
                        clock=clock,
                    )
                )

                recovered = (
                    close_manager.reconcile(
                        client_order_id=(
                            close_key
                        )
                    )
                )

                if (
                    recovered.status
                    != "CANCELLED"
                ):
                    raise ManagerStressError(
                        "PENDING_CLOSE_CANCEL_NOT_RECOVERED"
                    )

                counts[
                    "pending_close_cancel_recoveries"
                ] += 1

                counts[
                    "durable_restart_recoveries"
                ] += 1

    return WebullManagerStressReport(
        seed=seed,
        scenarios=scenarios,
        entry_cases=scenarios,
        close_cases=scenarios,
        **counts,
    )
