from dataclasses import replace
from datetime import UTC, datetime

import pytest

from trading_bot.webull_approval import (
    WebullApprovalQueue,
)
from trading_bot.webull_paper_order_service import (
    WebullPaperOrderService,
    WebullPaperOrderServiceError,
)
from trading_bot.webull_paper_order_store import (
    WebullPaperOrderRecord,
    WebullPaperOrderStore,
)
from trading_bot.webull_preview_store import (
    WebullPreviewStore,
)
from trading_bot.webull_safety import (
    WebullAccountState,
    WebullOrderProposal,
)


class FakeSnapshotClient:
    def __init__(
        self,
        account: WebullAccountState,
    ) -> None:
        self.account = account
        self.calls = 0

    def get_account_state(
        self,
    ) -> WebullAccountState:
        self.calls += 1
        return self.account


def cash_account(
    *,
    available_cash: float = 500.0,
    position_exposure: float = 0.0,
    open_buy_order_exposure: float = 0.0,
) -> WebullAccountState:
    return WebullAccountState(
        account_type="CASH",
        available_cash=available_cash,
        position_exposure=position_exposure,
        open_buy_order_exposure=(
            open_buy_order_exposure
        ),
        data_is_current=True,
    )


def build_service(tmp_path):
    preview_store = WebullPreviewStore(
        tmp_path / "previews.json"
    )

    preview_store.save_previews([
        {
            "symbol": "OPEN",
            "quantity": 10,
            "limitPrice": 4.25,
            "targetPrice": 4.60,
            "tradingStopPrice": 4.10,
            "proposedExposure": 42.50,
            "status": "PREVIEW READY",
            "createdAt": (
                "2026-08-06T20:00:00Z"
            ),
        }
    ])

    queue = WebullApprovalQueue()

    proposal = WebullOrderProposal(
        symbol="OPEN",
        side="BUY",
        quantity=10,
        limit_price=4.25,
        manually_approved=False,
    )

    ticket = queue.create(
        proposal=proposal,
        account=cash_account(),
    )

    queue.approve(
        approval_id=ticket.approval_id,
        approval_token=ticket.approval_token,
    )

    snapshot = FakeSnapshotClient(
        cash_account()
    )

    store = WebullPaperOrderStore(
        tmp_path / "paper-orders.json"
    )

    service = WebullPaperOrderService(
        approval_queue=queue,
        preview_store=preview_store,
        snapshot_client=snapshot,
        paper_order_store=store,
        clock=lambda: datetime(
            2026,
            8,
            6,
            20,
            1,
            tzinfo=UTC,
        ),
        id_factory=lambda: "paper-order-1",
    )

    return (
        service,
        queue,
        ticket,
        snapshot,
        store,
    )


def test_approved_preview_creates_paper_order(
    tmp_path,
):
    service, queue, ticket, snapshot, store = (
        build_service(tmp_path)
    )

    result = service.submit_paper_order(
        symbol="open",
        approval_id=ticket.approval_id,
        approval_token=ticket.approval_token,
    )

    assert result.paper_order_id == "paper-order-1"
    assert result.symbol == "OPEN"
    assert result.side == "BUY"
    assert result.quantity == 10
    assert result.limit_price == 4.25
    assert result.proposed_exposure == 42.50
    assert result.status == "PAPER SUBMITTED"
    assert snapshot.calls == 1
    assert queue.status(ticket.approval_id) == (
        "CONSUMED"
    )

    persisted = store.load()["paper-order-1"]

    assert persisted == result


def test_duplicate_paper_submission_is_blocked(
    tmp_path,
):
    service, _, ticket, _, _ = (
        build_service(tmp_path)
    )

    service.submit_paper_order(
        symbol="OPEN",
        approval_id=ticket.approval_id,
        approval_token=ticket.approval_token,
    )

    with pytest.raises(
        WebullPaperOrderServiceError,
        match="DUPLICATE_PAPER_SUBMISSION",
    ):
        service.submit_paper_order(
            symbol="OPEN",
            approval_id=ticket.approval_id,
            approval_token=ticket.approval_token,
        )


def test_unapproved_ticket_is_rejected(tmp_path):
    preview_store = WebullPreviewStore(
        tmp_path / "previews.json"
    )

    preview_store.save_previews([
        {
            "symbol": "OPEN",
            "quantity": 10,
            "limitPrice": 4.25,
            "targetPrice": 4.60,
            "tradingStopPrice": 4.10,
            "proposedExposure": 42.50,
            "status": "PREVIEW READY",
            "createdAt": (
                "2026-08-06T20:00:00Z"
            ),
        }
    ])

    queue = WebullApprovalQueue()

    proposal = WebullOrderProposal(
        symbol="OPEN",
        side="BUY",
        quantity=10,
        limit_price=4.25,
    )

    ticket = queue.create(
        proposal=proposal,
        account=cash_account(),
    )

    service = WebullPaperOrderService(
        approval_queue=queue,
        preview_store=preview_store,
        snapshot_client=FakeSnapshotClient(
            cash_account()
        ),
        paper_order_store=WebullPaperOrderStore(
            tmp_path / "paper-orders.json"
        ),
    )

    with pytest.raises(
        WebullPaperOrderServiceError,
        match="APPROVAL_NOT_APPROVED",
    ):
        service.submit_paper_order(
            symbol="OPEN",
            approval_id=ticket.approval_id,
            approval_token=ticket.approval_token,
        )


def test_changed_preview_is_rejected(tmp_path):
    service, _, ticket, _, _ = (
        build_service(tmp_path)
    )

    service.preview_store.save_previews([
        {
            "symbol": "OPEN",
            "quantity": 11,
            "limitPrice": 4.25,
            "targetPrice": 4.60,
            "tradingStopPrice": 4.10,
            "proposedExposure": 46.75,
            "status": "PREVIEW READY",
            "createdAt": (
                "2026-08-06T20:00:00Z"
            ),
        }
    ])

    with pytest.raises(
        WebullPaperOrderServiceError,
        match="ORDER_CHANGED_AFTER_APPROVAL",
    ):
        service.submit_paper_order(
            symbol="OPEN",
            approval_id=ticket.approval_id,
            approval_token=ticket.approval_token,
        )


def test_fresh_account_recheck_can_block_order(
    tmp_path,
):
    service, _, ticket, _, _ = (
        build_service(tmp_path)
    )

    service.snapshot_client = FakeSnapshotClient(
        cash_account(
            position_exposure=470.0
        )
    )

    with pytest.raises(
        WebullPaperOrderServiceError,
        match="FINAL_SAFETY_RECHECK_FAILED",
    ):
        service.submit_paper_order(
            symbol="OPEN",
            approval_id=ticket.approval_id,
            approval_token=ticket.approval_token,
        )


def test_missing_preview_is_rejected(tmp_path):
    queue = WebullApprovalQueue()

    service = WebullPaperOrderService(
        approval_queue=queue,
        preview_store=WebullPreviewStore(
            tmp_path / "missing.json"
        ),
        snapshot_client=FakeSnapshotClient(
            cash_account()
        ),
        paper_order_store=WebullPaperOrderStore(
            tmp_path / "paper-orders.json"
        ),
    )

    with pytest.raises(
        WebullPaperOrderServiceError,
        match="PREVIEW_NOT_FOUND",
    ):
        service.submit_paper_order(
            symbol="OPEN",
            approval_id="approval",
            approval_token="token",
        )


def test_service_exposes_no_broker_actions(
    tmp_path,
):
    service, _, _, _, _ = build_service(
        tmp_path
    )

    assert not hasattr(service, "place_order")
    assert not hasattr(service, "replace_order")
    assert not hasattr(service, "cancel_order")
    assert not hasattr(service, "submit_order")


class FailingPaperOrderStore:
    def load(self):
        return {}

    def add(self, record):
        from trading_bot.webull_paper_order_store import (
            WebullPaperOrderStoreError,
        )

        raise WebullPaperOrderStoreError(
            "SIMULATED_DISK_FAILURE"
        )


def test_persistence_failure_restores_approval(
    tmp_path,
):
    service, queue, ticket, _, _ = (
        build_service(tmp_path)
    )

    service.paper_order_store = (
        FailingPaperOrderStore()
    )

    with pytest.raises(
        WebullPaperOrderServiceError,
        match="PAPER_ORDER_PERSISTENCE_FAILED",
    ):
        service.submit_paper_order(
            symbol="OPEN",
            approval_id=ticket.approval_id,
            approval_token=ticket.approval_token,
        )

    assert queue.status(ticket.approval_id) == (
        "APPROVED"
    )


class WroteThenFailedPaperOrderStore:
    def __init__(self):
        self.records = {}

    def load(self):
        return self.records

    def add(self, record):
        from trading_bot.webull_paper_order_store import (
            WebullPaperOrderStoreError,
        )

        self.records[record.paper_order_id] = record

        raise WebullPaperOrderStoreError(
            "SIMULATED_POST_WRITE_FAILURE"
        )


def test_post_write_failure_keeps_approval_consumed(
    tmp_path,
):
    service, queue, ticket, _, _ = (
        build_service(tmp_path)
    )

    store = WroteThenFailedPaperOrderStore()
    service.paper_order_store = store

    result = service.submit_paper_order(
        symbol="OPEN",
        approval_id=ticket.approval_id,
        approval_token=ticket.approval_token,
    )

    assert result.status == "PAPER SUBMITTED"
    assert queue.status(ticket.approval_id) == (
        "CONSUMED"
    )
    assert len(store.records) == 1


def test_missing_lifecycle_data_is_rejected(
    tmp_path,
):
    service, _, ticket, _, _ = (
        build_service(tmp_path)
    )

    service.preview_store.save_previews([
        {
            "symbol": "OPEN",
            "quantity": 10,
            "limitPrice": 4.25,
            "proposedExposure": 42.50,
            "status": "PREVIEW READY",
            "createdAt": (
                "2026-08-06T20:00:00Z"
            ),
        }
    ])

    with pytest.raises(
        WebullPaperOrderServiceError,
        match="PREVIEW_LIFECYCLE_DATA_MISSING",
    ):
        service.submit_paper_order(
            symbol="OPEN",
            approval_id=ticket.approval_id,
            approval_token=ticket.approval_token,
        )


def test_paper_submission_blocks_when_simulated_cash_is_insufficient(
    tmp_path,
    monkeypatch,
):
    service, queue, ticket, _, store = (
        build_service(tmp_path)
    )

    monkeypatch.setenv(
        "WEBULL_PAPER_STARTING_CASH",
        "40",
    )
    monkeypatch.setenv(
        "WEBULL_PAPER_MAX_DAILY_LOSS",
        "50",
    )

    with pytest.raises(
        WebullPaperOrderServiceError,
        match="PAPER_INSUFFICIENT_AVAILABLE_CASH",
    ):
        service.submit_paper_order(
            symbol="OPEN",
            approval_id=ticket.approval_id,
            approval_token=ticket.approval_token,
        )

    assert queue.status(ticket.approval_id) == (
        "APPROVED"
    )
    assert store.load() == {}


def test_pending_paper_order_reserves_cash_before_second_submission(
    tmp_path,
    monkeypatch,
):
    service, queue, ticket, _, store = (
        build_service(tmp_path)
    )

    monkeypatch.setenv(
        "WEBULL_PAPER_STARTING_CASH",
        "80",
    )
    monkeypatch.setenv(
        "WEBULL_PAPER_MAX_DAILY_LOSS",
        "50",
    )

    first = service.submit_paper_order(
        symbol="OPEN",
        approval_id=ticket.approval_id,
        approval_token=ticket.approval_token,
    )

    assert first.lifecycle_status == (
        "ENTRY PENDING"
    )

    second_preview = WebullPreviewStore(
        service.preview_store.path
    )

    second_preview.save_previews([
        {
            "symbol": "SOUN",
            "quantity": 10,
            "limitPrice": 4.25,
            "targetPrice": 4.50,
            "tradingStopPrice": 4.00,
            "proposedExposure": 42.50,
            "status": "PREVIEW READY",
            "createdAt": "2026-08-06T20:02:00Z",
        }
    ])

    second_proposal = WebullOrderProposal(
        symbol="SOUN",
        side="BUY",
        quantity=10,
        limit_price=4.25,
        manually_approved=False,
    )

    second_ticket = queue.create(
        proposal=second_proposal,
        account=cash_account(),
    )

    queue.approve(
        approval_id=second_ticket.approval_id,
        approval_token=(
            second_ticket.approval_token
        ),
    )

    with pytest.raises(
        WebullPaperOrderServiceError,
        match="PAPER_INSUFFICIENT_AVAILABLE_CASH",
    ):
        service.submit_paper_order(
            symbol="SOUN",
            approval_id=second_ticket.approval_id,
            approval_token=(
                second_ticket.approval_token
            ),
        )

    assert queue.status(
        second_ticket.approval_id
    ) == "APPROVED"

    assert len(store.load()) == 1


def test_daily_loss_halt_blocks_service_before_approval_consumption(
    tmp_path,
    monkeypatch,
):
    service, queue, ticket, snapshot, store = (
        build_service(tmp_path)
    )

    monkeypatch.setenv(
        "WEBULL_PAPER_STARTING_CASH",
        "10000",
    )
    monkeypatch.setenv(
        "WEBULL_PAPER_MAX_DAILY_LOSS",
        "50",
    )

    loss_time = datetime(
        2026,
        8,
        6,
        19,
        30,
        tzinfo=UTC,
    )

    prior = WebullPaperOrderRecord(
        paper_order_id="prior-loss",
        approval_reference="prior-approval",
        idempotency_key="prior-key",
        symbol="SOUN",
        side="BUY",
        quantity=10,
        limit_price=10.0,
        proposed_exposure=100.0,
        status="PAPER SUBMITTED",
        created_at=loss_time,
        submitted_at=loss_time,
        safety_reason="APPROVED_BY_SAFETY_GATE",
        target_price=11.0,
        stop_price=5.0,
        lifecycle_status="CLOSED",
        filled_at=loss_time,
        fill_price=10.0,
        highest_price=10.0,
        lowest_price=5.0,
        mfe_pct=0.0,
        mae_pct=-50.0,
        closed_at=loss_time,
        exit_price=5.0,
        exit_reason="STOP",
        realized_pnl=-50.0,
        return_pct=-50.0,
    )

    store.add(prior)

    with pytest.raises(
        WebullPaperOrderServiceError,
        match="PAPER_DAILY_LOSS_LIMIT_REACHED",
    ):
        service.submit_paper_order(
            symbol="OPEN",
            approval_id=ticket.approval_id,
            approval_token=ticket.approval_token,
        )

    # Portfolio risk is checked before the existing
    # Webull account snapshot / approval claim.
    assert snapshot.calls == 0

    # The user's approval remains available rather than being
    # incorrectly consumed by a blocked paper submission.
    assert queue.status(ticket.approval_id) == (
        "APPROVED"
    )

    persisted = store.load()

    assert set(persisted) == {
        "prior-loss",
    }
