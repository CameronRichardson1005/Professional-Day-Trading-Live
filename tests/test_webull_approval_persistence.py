from datetime import UTC, datetime, timedelta

from trading_bot.webull_approval import (
    WebullApprovalQueue,
)
from trading_bot.webull_approval_store import (
    WebullApprovalStore,
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
            15,
            0,
            tzinfo=UTC,
        )

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += timedelta(seconds=seconds)


def account():
    return WebullAccountState(
        account_type="CASH",
        available_cash=1000.0,
        position_exposure=0.0,
        open_buy_order_exposure=0.0,
        data_is_current=True,
    )


def proposal():
    return WebullOrderProposal(
        symbol="OPEN",
        side="BUY",
        quantity=10,
        limit_price=4.0,
        manually_approved=False,
    )


def test_pending_approval_survives_restart(tmp_path):
    store = WebullApprovalStore(
        tmp_path / "approvals.json"
    )

    first_queue = WebullApprovalQueue(
        store=store
    )

    ticket = first_queue.create(
        proposal=proposal(),
        account=account(),
    )

    restarted_queue = WebullApprovalQueue(
        store=store
    )

    assert (
        restarted_queue.status(ticket.approval_id)
        == "PENDING"
    )


def test_approved_ticket_survives_restart(tmp_path):
    store = WebullApprovalStore(
        tmp_path / "approvals.json"
    )

    first_queue = WebullApprovalQueue(
        store=store
    )

    ticket = first_queue.create(
        proposal=proposal(),
        account=account(),
    )

    first_queue.approve(
        approval_id=ticket.approval_id,
        approval_token=ticket.approval_token,
    )

    restarted_queue = WebullApprovalQueue(
        store=store
    )

    assert (
        restarted_queue.status(ticket.approval_id)
        == "APPROVED"
    )


def test_plain_token_is_not_persisted(tmp_path):
    path = tmp_path / "approvals.json"
    store = WebullApprovalStore(path)

    queue = WebullApprovalQueue(
        store=store
    )

    ticket = queue.create(
        proposal=proposal(),
        account=account(),
    )

    stored_text = path.read_text(
        encoding="utf-8"
    )

    assert ticket.approval_token not in stored_text
    assert "token_hash" in stored_text


def test_expired_ticket_is_updated_on_restart(tmp_path):
    path = tmp_path / "approvals.json"
    store = WebullApprovalStore(path)
    clock = MutableClock()

    queue = WebullApprovalQueue(
        store=store,
        clock=clock,
        ttl_seconds=60,
    )

    ticket = queue.create(
        proposal=proposal(),
        account=account(),
    )

    clock.advance(61)

    restarted_queue = WebullApprovalQueue(
        store=store,
        clock=clock,
        ttl_seconds=60,
    )

    assert (
        restarted_queue.status(ticket.approval_id)
        == "EXPIRED"
    )


def test_in_memory_queue_still_supported():
    queue = WebullApprovalQueue()

    ticket = queue.create(
        proposal=proposal(),
        account=account(),
    )

    assert queue.status(ticket.approval_id) == (
        "PENDING"
    )


def test_public_records_are_redacted(tmp_path):
    store = WebullApprovalStore(
        tmp_path / "approvals.json"
    )

    queue = WebullApprovalQueue(
        store=store
    )

    ticket = queue.create(
        proposal=proposal(),
        account=account(),
    )

    records = queue.list_public_records()

    assert records == [
        {
            "symbol": "OPEN",
            "quantity": 10,
            "limitPrice": 4.0,
            "proposedExposure": 40.0,
            "status": "PENDING",
            "createdAt": (
                ticket.created_at
                .isoformat(timespec="seconds")
                .replace("+00:00", "Z")
            ),
            "expiresAt": (
                ticket.expires_at
                .isoformat(timespec="seconds")
                .replace("+00:00", "Z")
            ),
        }
    ]

    serialized = str(records)

    assert ticket.approval_token not in serialized
    assert "token_hash" not in serialized
    assert "proposal_fingerprint" not in serialized
    assert "approval_id" not in serialized


def test_public_records_update_expired_status(tmp_path):
    store = WebullApprovalStore(
        tmp_path / "approvals.json"
    )
    clock = MutableClock()

    queue = WebullApprovalQueue(
        store=store,
        clock=clock,
        ttl_seconds=60,
    )

    queue.create(
        proposal=proposal(),
        account=account(),
    )

    clock.advance(61)

    records = queue.list_public_records()

    assert records[0]["status"] == "EXPIRED"
