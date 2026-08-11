from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from trading_bot.webull_approval import (
    WebullApprovalError,
    WebullApprovalQueue,
)
from trading_bot.webull_safety import (
    WebullAccountState,
    WebullOrderProposal,
)


class MutableClock:
    def __init__(self):
        self.value = datetime(
            2026,
            8,
            6,
            14,
            0,
            tzinfo=UTC,
        )

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += timedelta(
            seconds=seconds
        )


def cash_account(
    *,
    available_cash=1000.0,
    position_exposure=0.0,
    open_buy_order_exposure=0.0,
):
    return WebullAccountState(
        account_type="CASH",
        available_cash=available_cash,
        position_exposure=position_exposure,
        open_buy_order_exposure=(
            open_buy_order_exposure
        ),
        data_is_current=True,
    )


def proposal(
    *,
    symbol="OPEN",
    quantity=10,
    limit_price=4.0,
):
    return WebullOrderProposal(
        symbol=symbol,
        side="BUY",
        quantity=quantity,
        limit_price=limit_price,
        manually_approved=False,
    )


def approved_ticket(
    *,
    clock=None,
    order=None,
    account=None,
):
    queue = WebullApprovalQueue(
        clock=clock,
        ttl_seconds=300,
    )

    order = order or proposal()
    account = account or cash_account()

    ticket = queue.create(
        proposal=order,
        account=account,
    )

    queue.approve(
        approval_id=ticket.approval_id,
        approval_token=ticket.approval_token,
    )

    return queue, ticket, order


def test_creates_pending_one_time_ticket():
    queue = WebullApprovalQueue()

    ticket = queue.create(
        proposal=proposal(),
        account=cash_account(),
    )

    assert ticket.status == "PENDING"
    assert ticket.symbol == "OPEN"
    assert ticket.proposed_exposure == 40.0
    assert ticket.approval_token
    assert queue.status(ticket.approval_id) == (
        "PENDING"
    )


def test_margin_account_cannot_create_approval():
    queue = WebullApprovalQueue()

    with pytest.raises(
        WebullApprovalError,
        match="CASH_ACCOUNT_REQUIRED",
    ):
        queue.create(
            proposal=proposal(),
            account=WebullAccountState(
                account_type="MARGIN",
                available_cash=1000.0,
                position_exposure=0.0,
                open_buy_order_exposure=0.0,
            ),
        )


def test_invalid_token_is_rejected():
    queue = WebullApprovalQueue()

    ticket = queue.create(
        proposal=proposal(),
        account=cash_account(),
    )

    with pytest.raises(
        WebullApprovalError,
        match="INVALID_APPROVAL_TOKEN",
    ):
        queue.approve(
            approval_id=ticket.approval_id,
            approval_token="wrong-token",
        )


def test_approval_expires():
    clock = MutableClock()
    queue = WebullApprovalQueue(
        clock=clock,
        ttl_seconds=60,
    )

    ticket = queue.create(
        proposal=proposal(),
        account=cash_account(),
    )

    clock.advance(60)

    with pytest.raises(
        WebullApprovalError,
        match="APPROVAL_EXPIRED",
    ):
        queue.approve(
            approval_id=ticket.approval_id,
            approval_token=ticket.approval_token,
        )

    assert queue.status(ticket.approval_id) == (
        "EXPIRED"
    )


def test_approval_cannot_be_approved_twice():
    queue, ticket, _ = approved_ticket()

    with pytest.raises(
        WebullApprovalError,
        match="APPROVAL_ALREADY_APPROVED",
    ):
        queue.approve(
            approval_id=ticket.approval_id,
            approval_token=ticket.approval_token,
        )


def test_kill_switch_blocks_claim():
    queue, ticket, order = approved_ticket()

    with pytest.raises(
        WebullApprovalError,
        match="TRADING_KILL_SWITCH_ACTIVE",
    ):
        queue.claim_for_submission(
            approval_id=ticket.approval_id,
            approval_token=ticket.approval_token,
            proposal=order,
            current_account=cash_account(),
        )


def test_submission_disabled_blocks_claim():
    queue, ticket, order = approved_ticket()

    with (
        patch(
            "trading_bot.webull_approval."
            "WEBULL_TRADING_KILL_SWITCH",
            False,
        ),
        pytest.raises(
            WebullApprovalError,
            match="REAL_ORDER_SUBMISSION_DISABLED",
        ),
    ):
        queue.claim_for_submission(
            approval_id=ticket.approval_id,
            approval_token=ticket.approval_token,
            proposal=order,
            current_account=cash_account(),
        )


def test_order_change_after_approval_is_rejected():
    queue, ticket, _ = approved_ticket()

    changed = proposal(
        quantity=11,
    )

    with (
        patch(
            "trading_bot.webull_approval."
            "WEBULL_TRADING_KILL_SWITCH",
            False,
        ),
        patch(
            "trading_bot.webull_approval."
            "WEBULL_ORDER_SUBMISSION_ENABLED",
            True,
        ),
        pytest.raises(
            WebullApprovalError,
            match="ORDER_CHANGED_AFTER_APPROVAL",
        ),
    ):
        queue.claim_for_submission(
            approval_id=ticket.approval_id,
            approval_token=ticket.approval_token,
            proposal=changed,
            current_account=cash_account(),
        )


def test_final_account_recheck_blocks_new_exposure():
    queue, ticket, order = approved_ticket()

    changed_account = cash_account(
        position_exposure=470.0,
    )

    with (
        patch(
            "trading_bot.webull_approval."
            "WEBULL_TRADING_KILL_SWITCH",
            False,
        ),
        patch(
            "trading_bot.webull_approval."
            "WEBULL_ORDER_SUBMISSION_ENABLED",
            True,
        ),
        pytest.raises(
            WebullApprovalError,
            match="FINAL_SAFETY_RECHECK_FAILED",
        ),
    ):
        queue.claim_for_submission(
            approval_id=ticket.approval_id,
            approval_token=ticket.approval_token,
            proposal=order,
            current_account=changed_account,
        )


def test_successful_claim_is_consumed_once():
    queue, ticket, order = approved_ticket()

    with (
        patch(
            "trading_bot.webull_approval."
            "WEBULL_TRADING_KILL_SWITCH",
            False,
        ),
        patch(
            "trading_bot.webull_approval."
            "WEBULL_ORDER_SUBMISSION_ENABLED",
            True,
        ),
    ):
        decision = queue.claim_for_submission(
            approval_id=ticket.approval_id,
            approval_token=ticket.approval_token,
            proposal=order,
            current_account=cash_account(),
        )

        assert decision.allowed
        assert queue.status(ticket.approval_id) == (
            "CONSUMED"
        )

        with pytest.raises(
            WebullApprovalError,
            match="APPROVAL_ALREADY_CONSUMED",
        ):
            queue.claim_for_submission(
                approval_id=ticket.approval_id,
                approval_token=ticket.approval_token,
                proposal=order,
                current_account=cash_account(),
            )


def test_queue_exposes_no_broker_actions():
    queue = WebullApprovalQueue()

    assert not hasattr(queue, "place_order")
    assert not hasattr(queue, "replace_order")
    assert not hasattr(queue, "cancel_order")
    assert not hasattr(queue, "submit_order")


def test_detects_active_duplicate_proposal():
    queue = WebullApprovalQueue()
    order = proposal()

    queue.create(
        proposal=order,
        account=cash_account(),
    )

    assert queue.has_active_duplicate(order)


def test_changed_proposal_is_not_duplicate():
    queue = WebullApprovalQueue()

    queue.create(
        proposal=proposal(),
        account=cash_account(),
    )

    changed = proposal(quantity=11)

    assert not queue.has_active_duplicate(changed)


def test_expired_proposal_is_not_active_duplicate():
    clock = MutableClock()
    queue = WebullApprovalQueue(
        clock=clock,
        ttl_seconds=60,
    )
    order = proposal()

    queue.create(
        proposal=order,
        account=cash_account(),
    )

    clock.advance(61)

    assert not queue.has_active_duplicate(order)


def test_paper_claim_consumes_approved_ticket():
    queue, ticket, order = approved_ticket()

    decision = queue.claim_for_paper_submission(
        approval_id=ticket.approval_id,
        approval_token=ticket.approval_token,
        proposal=order,
        current_account=cash_account(),
    )

    assert decision.allowed
    assert queue.status(ticket.approval_id) == (
        "CONSUMED"
    )


def test_paper_claim_does_not_require_real_submission_flags():
    queue, ticket, order = approved_ticket()

    with (
        patch(
            "trading_bot.webull_approval."
            "WEBULL_TRADING_KILL_SWITCH",
            True,
        ),
        patch(
            "trading_bot.webull_approval."
            "WEBULL_ORDER_SUBMISSION_ENABLED",
            False,
        ),
    ):
        decision = queue.claim_for_paper_submission(
            approval_id=ticket.approval_id,
            approval_token=ticket.approval_token,
            proposal=order,
            current_account=cash_account(),
        )

    assert decision.allowed


def test_paper_claim_rejects_changed_order():
    queue, ticket, _ = approved_ticket()

    changed = proposal(quantity=11)

    with pytest.raises(
        WebullApprovalError,
        match="ORDER_CHANGED_AFTER_APPROVAL",
    ):
        queue.claim_for_paper_submission(
            approval_id=ticket.approval_id,
            approval_token=ticket.approval_token,
            proposal=changed,
            current_account=cash_account(),
        )


def test_paper_claim_rechecks_current_account():
    queue, ticket, order = approved_ticket()

    changed_account = cash_account(
        position_exposure=470.0,
    )

    with pytest.raises(
        WebullApprovalError,
        match="FINAL_SAFETY_RECHECK_FAILED",
    ):
        queue.claim_for_paper_submission(
            approval_id=ticket.approval_id,
            approval_token=ticket.approval_token,
            proposal=order,
            current_account=changed_account,
        )


def test_paper_claim_can_only_be_consumed_once():
    queue, ticket, order = approved_ticket()

    queue.claim_for_paper_submission(
        approval_id=ticket.approval_id,
        approval_token=ticket.approval_token,
        proposal=order,
        current_account=cash_account(),
    )

    with pytest.raises(
        WebullApprovalError,
        match="APPROVAL_ALREADY_CONSUMED",
    ):
        queue.claim_for_paper_submission(
            approval_id=ticket.approval_id,
            approval_token=ticket.approval_token,
            proposal=order,
            current_account=cash_account(),
        )


def test_failed_paper_persistence_can_restore_approval():
    queue, ticket, order = approved_ticket()

    queue.claim_for_paper_submission(
        approval_id=ticket.approval_id,
        approval_token=ticket.approval_token,
        proposal=order,
        current_account=cash_account(),
    )

    assert queue.status(ticket.approval_id) == (
        "CONSUMED"
    )

    queue.restore_after_failed_paper_submission(
        approval_id=ticket.approval_id,
        approval_token=ticket.approval_token,
        proposal=order,
    )

    assert queue.status(ticket.approval_id) == (
        "APPROVED"
    )


def test_paper_restore_rejects_changed_proposal():
    queue, ticket, order = approved_ticket()

    queue.claim_for_paper_submission(
        approval_id=ticket.approval_id,
        approval_token=ticket.approval_token,
        proposal=order,
        current_account=cash_account(),
    )

    with pytest.raises(
        WebullApprovalError,
        match="ORDER_CHANGED_AFTER_APPROVAL",
    ):
        queue.restore_after_failed_paper_submission(
            approval_id=ticket.approval_id,
            approval_token=ticket.approval_token,
            proposal=proposal(quantity=11),
        )
