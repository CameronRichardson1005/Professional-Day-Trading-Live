import json

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from trading_bot.webull_account_risk import (
    WebullExecutionRiskLimits,
    WebullExecutionRiskState,
)
from trading_bot.webull_execution import (
    WebullTradeIntent,
)
from trading_bot.webull_safety import (
    WebullAccountState,
)
from trading_bot.webull_shadow_execution import (
    WebullShadowExecutionCoordinator,
    WebullShadowExecutionError,
    WebullShadowExecutionJournal,
)


NOW = datetime(
    2026,
    8,
    18,
    18,
    20,
    tzinfo=UTC,
)


def make_intent(
    *,
    client_order_id="shadow-1",
    strategy_name="MANIPULATION",
    symbol="OPEN",
    quantity=10,
    limit_price=10.0,
):
    return WebullTradeIntent(
        client_order_id=(
            client_order_id
        ),
        strategy_name=(
            strategy_name
        ),
        symbol=symbol,
        side="BUY",
        quantity=quantity,
        limit_price=limit_price,
        created_at=NOW,
    )


def make_account():
    return WebullAccountState(
        account_type="CASH",
        available_cash=1000.0,
        position_exposure=0.0,
        open_buy_order_exposure=0.0,
        data_is_current=True,
        buying_power=1000.0,
    )


def make_risk_state():
    return WebullExecutionRiskState(
        daily_realized_pnl=0.0,
        open_position_symbols=(),
        open_order_symbols=(),
        pending_buy_symbols=(),
        position_exposures=(),
        pending_buy_exposures=(),
        kill_switch_active=False,
        data_is_current=True,
    )


def make_limits():
    return WebullExecutionRiskLimits(
        max_daily_loss=100.0,
        max_open_positions=3,
        max_open_orders=3,
        max_position_exposure=500.0,
    )


def decision(
    *,
    allowed,
    reason,
):
    return SimpleNamespace(
        allowed=allowed,
        reason=reason,
    )


def test_missing_journal_is_empty(
    tmp_path,
):
    journal = (
        WebullShadowExecutionJournal(
            tmp_path
            / "shadow.json"
        )
    )

    assert journal.load() == ()


def test_accepted_shadow_is_durable_and_never_submitted(
    tmp_path,
):
    risk_calls = []
    safety_calls = []

    def risk_evaluator(
        **kwargs,
    ):
        risk_calls.append(
            kwargs
        )

        return decision(
            allowed=True,
            reason=(
                "APPROVED_BY_ACCOUNT_RISK"
            ),
        )

    def safety_evaluator(
        **kwargs,
    ):
        safety_calls.append(
            kwargs
        )

        return decision(
            allowed=True,
            reason=(
                "APPROVED_BY_SAFETY_GATE"
            ),
        )

    journal = (
        WebullShadowExecutionJournal(
            tmp_path
            / "shadow.json"
        )
    )

    coordinator = (
        WebullShadowExecutionCoordinator(
            journal=journal,
            risk_evaluator=(
                risk_evaluator
            ),
            safety_evaluator=(
                safety_evaluator
            ),
            clock=lambda: NOW,
        )
    )

    record = coordinator.evaluate(
        intent=make_intent(),
        account=make_account(),
        risk_state=(
            make_risk_state()
        ),
        risk_limits=(
            make_limits()
        ),
    )

    assert (
        record.status
        == "ACCEPTED_SHADOW"
    )

    assert (
        record.decision_reason
        == "SHADOW_APPROVED"
    )

    assert (
        record.risk_allowed
        is True
    )

    assert (
        record.safety_allowed
        is True
    )

    assert (
        record.broker_submission_attempted
        is False
    )

    assert len(
        risk_calls
    ) == 1

    assert len(
        safety_calls
    ) == 1

    assert (
        safety_calls[0][
            "require_manual_approval"
        ]
        is False
    )

    persisted = journal.load()

    assert len(
        persisted
    ) == 1

    assert (
        persisted[0]["status"]
        == "ACCEPTED_SHADOW"
    )

    assert (
        persisted[0][
            "broker_submission_attempted"
        ]
        is False
    )


def test_risk_rejection_never_calls_safety(
    tmp_path,
):
    def risk_evaluator(
        **kwargs,
    ):
        del kwargs

        return decision(
            allowed=False,
            reason="DAILY_LIMIT",
        )

    def forbidden_safety(
        **kwargs,
    ):
        del kwargs

        raise AssertionError(
            "Safety must not run after "
            "risk rejection."
        )

    coordinator = (
        WebullShadowExecutionCoordinator(
            journal=(
                WebullShadowExecutionJournal(
                    tmp_path
                    / "shadow.json"
                )
            ),
            risk_evaluator=(
                risk_evaluator
            ),
            safety_evaluator=(
                forbidden_safety
            ),
            clock=lambda: NOW,
        )
    )

    record = coordinator.evaluate(
        intent=make_intent(),
        account=make_account(),
        risk_state=(
            make_risk_state()
        ),
        risk_limits=(
            make_limits()
        ),
    )

    assert (
        record.status
        == "REJECTED_SHADOW"
    )

    assert (
        record.decision_reason
        == (
            "ACCOUNT_RISK_GATE_REJECTED:"
            "DAILY_LIMIT"
        )
    )

    assert (
        record.risk_allowed
        is False
    )

    assert (
        record.safety_allowed
        is None
    )

    assert (
        record.safety_reason
        == "NOT_EVALUATED"
    )

    assert (
        record.broker_submission_attempted
        is False
    )


def test_safety_rejection_is_persisted_after_risk_pass(
    tmp_path,
):
    coordinator = (
        WebullShadowExecutionCoordinator(
            journal=(
                WebullShadowExecutionJournal(
                    tmp_path
                    / "shadow.json"
                )
            ),
            risk_evaluator=(
                lambda **kwargs: decision(
                    allowed=True,
                    reason=(
                        "RISK_APPROVED"
                    ),
                )
            ),
            safety_evaluator=(
                lambda **kwargs: decision(
                    allowed=False,
                    reason=(
                        "OPERATIONAL_"
                        "EXPOSURE_CAP_EXCEEDED"
                    ),
                )
            ),
            clock=lambda: NOW,
        )
    )

    record = coordinator.evaluate(
        intent=make_intent(),
        account=make_account(),
        risk_state=(
            make_risk_state()
        ),
        risk_limits=(
            make_limits()
        ),
    )

    assert (
        record.status
        == "REJECTED_SHADOW"
    )

    assert (
        record.decision_reason
        == (
            "SAFETY_GATE_REJECTED:"
            "OPERATIONAL_"
            "EXPOSURE_CAP_EXCEEDED"
        )
    )

    assert (
        record.risk_allowed
        is True
    )

    assert (
        record.safety_allowed
        is False
    )

    assert (
        record.broker_submission_attempted
        is False
    )


def test_duplicate_client_order_id_fails_closed(
    tmp_path,
):
    journal = (
        WebullShadowExecutionJournal(
            tmp_path
            / "shadow.json"
        )
    )

    coordinator = (
        WebullShadowExecutionCoordinator(
            journal=journal,
            risk_evaluator=(
                lambda **kwargs: decision(
                    allowed=True,
                    reason="RISK_OK",
                )
            ),
            safety_evaluator=(
                lambda **kwargs: decision(
                    allowed=True,
                    reason="SAFETY_OK",
                )
            ),
            clock=lambda: NOW,
        )
    )

    intent = make_intent()

    coordinator.evaluate(
        intent=intent,
        account=make_account(),
        risk_state=(
            make_risk_state()
        ),
        risk_limits=(
            make_limits()
        ),
    )

    with pytest.raises(
        WebullShadowExecutionError,
        match=(
            "^SHADOW_CLIENT_ORDER_ID_"
            "ALREADY_RECORDED$"
        ),
    ):
        coordinator.evaluate(
            intent=intent,
            account=make_account(),
            risk_state=(
                make_risk_state()
            ),
            risk_limits=(
                make_limits()
            ),
        )

    assert len(
        journal.load()
    ) == 1


def test_two_strategies_can_be_recorded_separately(
    tmp_path,
):
    journal = (
        WebullShadowExecutionJournal(
            tmp_path
            / "shadow.json"
        )
    )

    coordinator = (
        WebullShadowExecutionCoordinator(
            journal=journal,
            risk_evaluator=(
                lambda **kwargs: decision(
                    allowed=True,
                    reason="RISK_OK",
                )
            ),
            safety_evaluator=(
                lambda **kwargs: decision(
                    allowed=True,
                    reason="SAFETY_OK",
                )
            ),
            clock=lambda: NOW,
        )
    )

    coordinator.evaluate(
        intent=make_intent(
            client_order_id=(
                "manipulation-1"
            ),
            strategy_name=(
                "MANIPULATION"
            ),
        ),
        account=make_account(),
        risk_state=(
            make_risk_state()
        ),
        risk_limits=(
            make_limits()
        ),
    )

    coordinator.evaluate(
        intent=make_intent(
            client_order_id=(
                "quick-flip-1"
            ),
            strategy_name=(
                "QUICK_FLIP"
            ),
            symbol="SOUN",
        ),
        account=make_account(),
        risk_state=(
            make_risk_state()
        ),
        risk_limits=(
            make_limits()
        ),
    )

    records = journal.load()

    assert len(
        records
    ) == 2

    assert {
        record[
            "strategy_name"
        ]
        for record in records
    } == {
        "MANIPULATION",
        "QUICK_FLIP",
    }


def test_corrupt_shadow_journal_fails_closed(
    tmp_path,
):
    path = (
        tmp_path
        / "shadow.json"
    )

    path.write_text(
        json.dumps({
            "version": 1,
            "records": [
                {
                    "record_type": (
                        "SHADOW_EXECUTION"
                    ),
                    "client_order_id": (
                        "bad"
                    ),
                    "status": (
                        "ACCEPTED_SHADOW"
                    ),

                    # A shadow journal is invalid
                    # if it claims broker mutation.
                    "broker_submission_attempted": (
                        True
                    ),
                }
            ],
        }),
        encoding="utf-8",
    )

    journal = (
        WebullShadowExecutionJournal(
            path
        )
    )

    with pytest.raises(
        WebullShadowExecutionError,
        match=(
            "^SHADOW_BROKER_SUBMISSION_"
            "FLAG_INVALID$"
        ),
    ):
        journal.load()


def test_naive_clock_fails_before_persistence(
    tmp_path,
):
    path = (
        tmp_path
        / "shadow.json"
    )

    coordinator = (
        WebullShadowExecutionCoordinator(
            journal=(
                WebullShadowExecutionJournal(
                    path
                )
            ),
            risk_evaluator=(
                lambda **kwargs: decision(
                    allowed=True,
                    reason="RISK_OK",
                )
            ),
            safety_evaluator=(
                lambda **kwargs: decision(
                    allowed=True,
                    reason="SAFETY_OK",
                )
            ),
            clock=lambda: datetime(
                2026,
                8,
                18,
                14,
                20,
            ),
        )
    )

    with pytest.raises(
        WebullShadowExecutionError,
        match=(
            "^SHADOW_CLOCK_MUST_BE_"
            "TIMEZONE_AWARE$"
        ),
    ):
        coordinator.evaluate(
            intent=make_intent(),
            account=make_account(),
            risk_state=(
                make_risk_state()
            ),
            risk_limits=(
                make_limits()
            ),
        )

    assert not path.exists()


def test_invalid_gate_decision_fails_closed(
    tmp_path,
):
    coordinator = (
        WebullShadowExecutionCoordinator(
            journal=(
                WebullShadowExecutionJournal(
                    tmp_path
                    / "shadow.json"
                )
            ),
            risk_evaluator=(
                lambda **kwargs: (
                    SimpleNamespace(
                        allowed="yes",
                        reason="invalid",
                    )
                )
            ),
            safety_evaluator=(
                lambda **kwargs: decision(
                    allowed=True,
                    reason="SAFETY_OK",
                )
            ),
            clock=lambda: NOW,
        )
    )

    with pytest.raises(
        WebullShadowExecutionError,
        match=(
            "^SHADOW_RISK_DECISION_INVALID$"
        ),
    ):
        coordinator.evaluate(
            intent=make_intent(),
            account=make_account(),
            risk_state=(
                make_risk_state()
            ),
            risk_limits=(
                make_limits()
            ),
        )
