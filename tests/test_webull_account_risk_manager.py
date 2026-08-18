import random

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from trading_bot.webull_account_risk import (
    WebullAccountRiskGate,
    WebullExecutionRiskLimits,
    WebullExecutionRiskState,
)
from trading_bot.webull_execution import (
    WebullTradeIntent,
)
from trading_bot.webull_execution_ledger import (
    WebullExecutionLedger,
)
from trading_bot.webull_execution_manager import (
    WebullExecutionManagerError,
    WebullSandboxExecutionManager,
)
from trading_bot.webull_safety import (
    WebullAccountState,
    WebullOrderProposal,
)


NOW = datetime(
    2026,
    8,
    17,
    20,
    0,
    tzinfo=UTC,
)


class FakeBroker:
    def __init__(self):
        self.place_calls = []
        self.detail_calls = []

    def place_order(self, intent):
        self.place_calls.append(
            intent.client_order_id
        )

    def get_order_detail(
        self,
        *,
        client_order_id,
    ):
        self.detail_calls.append(
            client_order_id
        )

        return SimpleNamespace(
            client_order_id=(
                client_order_id
            ),
            broker_status="SUBMITTED",
            broker_order_id=(
                "broker-"
                + client_order_id
            ),
            filled_quantity=0.0,
            average_fill_price=None,
            quantity=5,
            limit_price=20.0,
        )


def account(
    *,
    cash=1000.0,
    buying_power=1000.0,
    exposure=0.0,
    open_exposure=0.0,
):
    return WebullAccountState(
        account_type="CASH",
        available_cash=cash,
        position_exposure=exposure,
        open_buy_order_exposure=(
            open_exposure
        ),
        data_is_current=True,
        buying_power=buying_power,
    )


def intent(
    key="risk-order",
):
    return WebullTradeIntent(
        client_order_id=key,
        strategy_name="RISK_INTEGRATION",
        symbol="SOUN",
        side="BUY",
        quantity=5,
        limit_price=20.0,
        created_at=NOW,
    )


def limits():
    return WebullExecutionRiskLimits(
        max_daily_loss=50.0,
        max_open_positions=2,
        max_open_orders=2,
        max_position_exposure=225.0,
    )


def risk_state(
    *,
    pnl=0.0,
    positions=(),
    orders=(),
    pending_buys=(),
    position_exposures=None,
    pending_buy_exposures=None,
    kill=False,
    current=True,
):
    if position_exposures is None:
        position_exposures = tuple(
            (
                symbol,
                0.0,
            )
            for symbol
            in positions
        )

    if pending_buy_exposures is None:
        pending_buy_exposures = tuple(
            (
                symbol,
                0.0,
            )
            for symbol
            in pending_buys
        )

    return WebullExecutionRiskState(
        daily_realized_pnl=pnl,
        open_position_symbols=(
            positions
        ),
        open_order_symbols=orders,
        kill_switch_active=kill,
        pending_buy_symbols=(
            pending_buys
        ),
        position_exposures=(
            position_exposures
        ),
        pending_buy_exposures=(
            pending_buy_exposures
        ),
        data_is_current=current,
    )


def manager(
    tmp_path,
):
    broker = FakeBroker()

    ledger = WebullExecutionLedger(
        tmp_path / "execution.json",
        clock=lambda: NOW,
    )

    result = (
        WebullSandboxExecutionManager(
            broker=broker,
            ledger=ledger,
        )
    )

    return result, broker, ledger


def test_account_risk_approved_order_submits(
    tmp_path,
):
    execution, broker, ledger = (
        manager(tmp_path)
    )

    result = (
        execution
        .submit_with_account_risk(
            intent=intent(),
            account=account(),
            risk_state=risk_state(),
            risk_limits=limits(),
        )
    )

    assert result.status == "SUBMITTED"

    assert broker.place_calls == [
        "risk-order"
    ]

    assert (
        ledger.load()[
            "risk-order"
        ].status
        == "SUBMITTED"
    )


@pytest.mark.parametrize(
    ("state", "reason"),
    [
        (
            risk_state(kill=True),
            "TRADING_KILL_SWITCH_ACTIVE",
        ),
        (
            risk_state(pnl=-50.0),
            "DAILY_LOSS_LIMIT_REACHED",
        ),
        (
            risk_state(
                orders=("SOUN",)
            ),
            "OPEN_ORDER_ALREADY_EXISTS_FOR_SYMBOL",
        ),
        (
            risk_state(
                orders=(
                    "OPEN",
                    "BBAI",
                )
            ),
            "MAX_OPEN_ORDERS_EXCEEDED",
        ),
        (
            risk_state(
                positions=(
                    "OPEN",
                    "BBAI",
                )
            ),
            "MAX_OPEN_POSITIONS_EXCEEDED",
        ),
        (
            risk_state(
                current=False
            ),
            "ACCOUNT_RISK_DATA_STALE_OR_UNKNOWN",
        ),
    ],
)
def test_account_risk_rejection_occurs_before_mutation(
    tmp_path,
    state,
    reason,
):
    execution, broker, ledger = (
        manager(tmp_path)
    )

    with pytest.raises(
        WebullExecutionManagerError,
        match=(
            "ACCOUNT_RISK_GATE_REJECTED:"
            + reason
        ),
    ):
        execution.submit_with_account_risk(
            intent=intent(),
            account=account(),
            risk_state=state,
            risk_limits=limits(),
        )

    assert broker.place_calls == []
    assert broker.detail_calls == []
    assert ledger.load() == {}


def test_buying_power_overlay_blocks_before_broker(
    tmp_path,
):
    execution, broker, ledger = (
        manager(tmp_path)
    )

    with pytest.raises(
        WebullExecutionManagerError,
        match=(
            "ACCOUNT_RISK_GATE_REJECTED:"
            "INSUFFICIENT_SAFE_EXECUTION_CAPITAL"
        ),
    ):
        execution.submit_with_account_risk(
            intent=intent(),
            account=account(
                cash=1000.0,
                buying_power=75.0,
            ),
            risk_state=risk_state(),
            risk_limits=limits(),
        )

    assert broker.place_calls == []
    assert ledger.load() == {}


def test_existing_exposure_safety_still_runs_after_account_risk(
    tmp_path,
):
    execution, broker, ledger = (
        manager(tmp_path)
    )

    with pytest.raises(
        WebullExecutionManagerError,
        match=(
            "SAFETY_GATE_REJECTED:"
            "OPERATIONAL_EXPOSURE_CAP_EXCEEDED"
        ),
    ):
        execution.submit_with_account_risk(
            intent=intent(),
            account=account(
                exposure=400.0,
            ),
            risk_state=risk_state(
                positions=("OPEN",)
            ),
            risk_limits=WebullExecutionRiskLimits(
                max_daily_loss=50.0,
                max_open_positions=3,
                max_open_orders=3,
                max_position_exposure=225.0,
            ),
        )

    assert broker.place_calls == []
    assert ledger.load() == {}


def test_1000_randomized_account_risk_manager_scenarios(
    tmp_path,
):
    rng = random.Random(
        20260817
    )

    allowed = 0
    rejected = 0

    rejection_reasons = set()

    for index in range(1000):
        ledger_path = (
            tmp_path
            / "execution.json"
        )

        ledger_path.unlink(
            missing_ok=True
        )

        broker = FakeBroker()

        ledger = WebullExecutionLedger(
            ledger_path,
            clock=lambda: NOW,
        )

        execution = (
            WebullSandboxExecutionManager(
                broker=broker,
                ledger=ledger,
            )
        )

        key = (
            f"random-risk-{index}"
        )

        order_intent = intent(
            key=key
        )

        max_positions = rng.randint(
            1,
            4,
        )

        max_orders = rng.randint(
            1,
            4,
        )

        position_count = rng.randint(
            0,
            5,
        )

        order_count = rng.randint(
            0,
            5,
        )

        positions = tuple(
            f"P{number}"
            for number
            in range(
                position_count
            )
        )

        orders = tuple(
            f"O{number}"
            for number
            in range(
                order_count
            )
        )

        if rng.random() < 0.15:
            orders = (
                orders
                + ("SOUN",)
            )

        daily_loss = 50.0

        pnl = round(
            rng.uniform(
                -80.0,
                40.0,
            ),
            2,
        )

        kill = (
            rng.random()
            < 0.08
        )

        current = (
            rng.random()
            >= 0.08
        )

        buying_power = round(
            rng.uniform(
                25.0,
                500.0,
            ),
            2,
        )

        account_value = account(
            cash=1000.0,
            buying_power=buying_power,
        )

        state_value = (
            risk_state(
                pnl=pnl,
                positions=positions,
                orders=orders,
                kill=kill,
                current=current,
            )
        )

        limit_value = (
            WebullExecutionRiskLimits(
                max_daily_loss=(
                    daily_loss
                ),
                max_open_positions=(
                    max_positions
                ),
                max_open_orders=(
                    max_orders
                ),
                max_position_exposure=225.0,
            )
        )

        expected = (
            WebullAccountRiskGate
            .evaluate_new_buy(
                account=account_value,
                proposal=WebullOrderProposal(
                    symbol="SOUN",
                    side="BUY",
                    quantity=5,
                    limit_price=20.0,
                    manually_approved=False,
                ),
                risk_state=state_value,
                limits=limit_value,
            )
        )

        if expected.allowed:
            result = (
                execution
                .submit_with_account_risk(
                    intent=order_intent,
                    account=account_value,
                    risk_state=state_value,
                    risk_limits=limit_value,
                )
            )

            assert result.status == (
                "SUBMITTED"
            )

            assert broker.place_calls == [
                key
            ]

            allowed += 1

        else:
            with pytest.raises(
                WebullExecutionManagerError,
                match=(
                    "ACCOUNT_RISK_GATE_REJECTED:"
                    + expected.reason
                ),
            ):
                execution.submit_with_account_risk(
                    intent=order_intent,
                    account=account_value,
                    risk_state=state_value,
                    risk_limits=limit_value,
                )

            assert broker.place_calls == []
            assert ledger.load() == {}

            rejected += 1

            rejection_reasons.add(
                expected.reason
            )

    assert allowed > 0
    assert rejected > 0

    assert (
        "TRADING_KILL_SWITCH_ACTIVE"
        in rejection_reasons
    )

    assert (
        "DAILY_LOSS_LIMIT_REACHED"
        in rejection_reasons
    )

    assert (
        "MAX_OPEN_ORDERS_EXCEEDED"
        in rejection_reasons
    )

    assert (
        "MAX_OPEN_POSITIONS_EXCEEDED"
        in rejection_reasons
    )

    assert (
        "INSUFFICIENT_SAFE_EXECUTION_CAPITAL"
        in rejection_reasons
    )


def test_pending_buy_slot_rejection_occurs_before_mutation(
    tmp_path,
):
    execution, broker, ledger = (
        manager(tmp_path)
    )

    with pytest.raises(
        WebullExecutionManagerError,
        match=(
            "ACCOUNT_RISK_GATE_REJECTED:"
            "MAX_OPEN_POSITIONS_EXCEEDED"
        ),
    ):
        execution.submit_with_account_risk(
            intent=intent(),
            account=account(
                cash=1000.0,
                buying_power=1000.0,
                exposure=50.0,
                open_exposure=50.0,
            ),
            risk_state=risk_state(
                positions=("AAPL",),
                orders=("MSFT",),
                pending_buys=("MSFT",),
            ),
            risk_limits=limits(),
        )

    assert broker.place_calls == []
    assert broker.detail_calls == []
    assert ledger.load() == {}
