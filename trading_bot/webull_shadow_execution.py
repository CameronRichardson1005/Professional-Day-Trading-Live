from __future__ import annotations

import json
import os

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from .webull_account_risk import (
    WebullAccountRiskGate,
    WebullExecutionRiskLimits,
    WebullExecutionRiskState,
)
from .webull_execution import (
    WebullTradeIntent,
)
from .webull_safety import (
    WebullAccountState,
    WebullOrderProposal,
    WebullSafetyGate,
)


DEFAULT_WEBULL_SHADOW_EXECUTION_FILE = (
    Path("runtime")
    / "webull_shadow_execution.json"
)


class WebullShadowExecutionError(
    RuntimeError
):
    pass


@dataclass(frozen=True)
class WebullShadowExecutionRecord:
    """
    Observation-only execution decision.

    This record explicitly represents an order that was NOT sent
    to Webull.

    It is intentionally separate from WebullExecutionLedger so
    broker reconciliation can never mistake a shadow decision for
    a real submitted order.
    """

    record_type: str

    client_order_id: str
    strategy_name: str
    symbol: str
    side: str

    quantity: int
    limit_price: float
    proposed_exposure: float

    intent_created_at: str
    recorded_at: str

    status: str
    decision_reason: str

    risk_allowed: bool
    risk_reason: str

    safety_allowed: bool | None
    safety_reason: str | None

    account_type: str
    account_available_cash: float
    account_buying_power: float | None
    account_current_exposure: float
    account_data_is_current: bool

    daily_realized_pnl: float
    risk_kill_switch_active: bool
    risk_data_is_current: bool

    max_daily_loss: float
    max_open_positions: int
    max_open_orders: int
    max_position_exposure: float

    broker_submission_attempted: bool = False

    def to_dict(
        self,
    ) -> dict[str, Any]:
        return asdict(
            self
        )


class WebullShadowExecutionJournal:
    """
    Durable JSON journal containing shadow decisions only.

    This journal:
    - contains no broker-order state;
    - is not read by Webull execution reconciliation;
    - rejects duplicate client_order_id values;
    - writes atomically through an ignored *.json temp file.
    """

    VERSION = 1

    def __init__(
        self,
        path: str | Path = (
            DEFAULT_WEBULL_SHADOW_EXECUTION_FILE
        ),
    ) -> None:
        self.path = Path(
            path
        )

    @staticmethod
    def _validate_record(
        record: Any,
    ) -> dict[str, Any]:
        if not isinstance(
            record,
            dict,
        ):
            raise WebullShadowExecutionError(
                "SHADOW_JOURNAL_RECORD_INVALID"
            )

        if (
            record.get("record_type")
            != "SHADOW_EXECUTION"
        ):
            raise WebullShadowExecutionError(
                "SHADOW_JOURNAL_RECORD_TYPE_INVALID"
            )

        client_order_id = str(
            record.get(
                "client_order_id",
                "",
            )
        ).strip()

        if not client_order_id:
            raise WebullShadowExecutionError(
                "SHADOW_CLIENT_ORDER_ID_REQUIRED"
            )

        if record.get(
            "status"
        ) not in {
            "ACCEPTED_SHADOW",
            "REJECTED_SHADOW",
        }:
            raise WebullShadowExecutionError(
                "SHADOW_STATUS_INVALID"
            )

        if (
            record.get(
                "broker_submission_attempted"
            )
            is not False
        ):
            raise WebullShadowExecutionError(
                "SHADOW_BROKER_SUBMISSION_FLAG_INVALID"
            )

        return dict(
            record
        )

    def load(
        self,
    ) -> tuple[
        dict[str, Any],
        ...
    ]:
        if not self.path.exists():
            return ()

        try:
            payload = json.loads(
                self.path.read_text(
                    encoding="utf-8"
                )
            )
        except Exception as error:
            raise WebullShadowExecutionError(
                "SHADOW_JOURNAL_READ_FAILED"
            ) from error

        if not isinstance(
            payload,
            dict,
        ):
            raise WebullShadowExecutionError(
                "SHADOW_JOURNAL_INVALID"
            )

        if (
            payload.get("version")
            != self.VERSION
        ):
            raise WebullShadowExecutionError(
                "SHADOW_JOURNAL_VERSION_INVALID"
            )

        records = payload.get(
            "records"
        )

        if not isinstance(
            records,
            list,
        ):
            raise WebullShadowExecutionError(
                "SHADOW_JOURNAL_RECORDS_INVALID"
            )

        validated = []
        seen_ids = set()

        for raw_record in records:
            record = self._validate_record(
                raw_record
            )

            client_order_id = (
                record[
                    "client_order_id"
                ]
            )

            if client_order_id in seen_ids:
                raise WebullShadowExecutionError(
                    "SHADOW_DUPLICATE_CLIENT_ORDER_ID"
                )

            seen_ids.add(
                client_order_id
            )

            validated.append(
                record
            )

        return tuple(
            validated
        )

    def _write(
        self,
        records: list[
            dict[str, Any]
        ],
    ) -> None:
        self.path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        temporary_path = (
            self.path.with_name(
                self.path.stem
                + ".tmp"
                + self.path.suffix
            )
        )

        payload = {
            "version": self.VERSION,
            "records": records,
        }

        serialized = (
            json.dumps(
                payload,
                sort_keys=True,
                separators=(
                    ",",
                    ":",
                ),
            )
            + "\n"
        )

        try:
            with temporary_path.open(
                "w",
                encoding="utf-8",
            ) as handle:
                handle.write(
                    serialized
                )

                handle.flush()

                os.fsync(
                    handle.fileno()
                )

            os.replace(
                temporary_path,
                self.path,
            )

            directory_fd = os.open(
                self.path.parent,
                os.O_RDONLY,
            )

            try:
                os.fsync(
                    directory_fd
                )
            finally:
                os.close(
                    directory_fd
                )

        except Exception as error:
            try:
                temporary_path.unlink(
                    missing_ok=True
                )
            except Exception:
                pass

            raise WebullShadowExecutionError(
                "SHADOW_JOURNAL_WRITE_FAILED"
            ) from error

    def append(
        self,
        record: WebullShadowExecutionRecord,
    ) -> WebullShadowExecutionRecord:
        records = list(
            self.load()
        )

        client_order_id = (
            record.client_order_id
        )

        if any(
            existing[
                "client_order_id"
            ]
            == client_order_id
            for existing in records
        ):
            raise WebullShadowExecutionError(
                "SHADOW_CLIENT_ORDER_ID_ALREADY_RECORDED"
            )

        serialized_record = (
            self._validate_record(
                record.to_dict()
            )
        )

        records.append(
            serialized_record
        )

        self._write(
            records
        )

        return record


class WebullShadowExecutionCoordinator:
    """
    Pure shadow decision boundary for a normalized trade intent.

    Evaluation order deliberately mirrors the protected automatic
    execution path:

        account risk
            -> normal execution safety
            -> SHADOW journal

    It NEVER calls WebullSandboxExecutionManager.submit(),
    never writes WebullExecutionLedger, and has no broker object.
    """

    def __init__(
        self,
        *,
        journal: (
            WebullShadowExecutionJournal
            | None
        ) = None,
        risk_evaluator: (
            Callable[..., Any]
            | None
        ) = None,
        safety_evaluator: (
            Callable[..., Any]
            | None
        ) = None,
        clock: (
            Callable[
                [],
                datetime,
            ]
            | None
        ) = None,
    ) -> None:
        self.journal = (
            journal
            if journal is not None
            else WebullShadowExecutionJournal()
        )

        self.risk_evaluator = (
            risk_evaluator
            if risk_evaluator is not None
            else (
                WebullAccountRiskGate
                .evaluate_new_buy
            )
        )

        self.safety_evaluator = (
            safety_evaluator
            if safety_evaluator is not None
            else WebullSafetyGate.evaluate
        )

        self.clock = (
            clock
            if clock is not None
            else lambda: datetime.now(
                UTC
            )
        )

        if not callable(
            self.risk_evaluator
        ):
            raise WebullShadowExecutionError(
                "SHADOW_RISK_EVALUATOR_INVALID"
            )

        if not callable(
            self.safety_evaluator
        ):
            raise WebullShadowExecutionError(
                "SHADOW_SAFETY_EVALUATOR_INVALID"
            )

        if not callable(
            self.clock
        ):
            raise WebullShadowExecutionError(
                "SHADOW_CLOCK_INVALID"
            )

    @staticmethod
    def _decision(
        decision: Any,
        *,
        invalid_reason: str,
    ) -> tuple[
        bool,
        str,
    ]:
        allowed = getattr(
            decision,
            "allowed",
            None,
        )

        reason = str(
            getattr(
                decision,
                "reason",
                "",
            )
        ).strip()

        if (
            not isinstance(
                allowed,
                bool,
            )
            or not reason
        ):
            raise WebullShadowExecutionError(
                invalid_reason
            )

        return (
            allowed,
            reason,
        )

    def evaluate(
        self,
        *,
        intent: WebullTradeIntent,
        account: WebullAccountState,
        risk_state: WebullExecutionRiskState,
        risk_limits: WebullExecutionRiskLimits,
    ) -> WebullShadowExecutionRecord:
        now = self.clock()

        if (
            not isinstance(
                now,
                datetime,
            )
            or now.tzinfo is None
        ):
            raise WebullShadowExecutionError(
                "SHADOW_CLOCK_MUST_BE_TIMEZONE_AWARE"
            )

        proposal = WebullOrderProposal(
            symbol=intent.symbol,
            side=intent.side,
            quantity=intent.quantity,
            limit_price=(
                intent.limit_price
            ),
            manually_approved=False,
        )

        try:
            risk_decision = (
                self.risk_evaluator(
                    account=account,
                    proposal=proposal,
                    risk_state=risk_state,
                    limits=risk_limits,
                )
            )
        except WebullShadowExecutionError:
            raise
        except Exception as error:
            raise WebullShadowExecutionError(
                "SHADOW_RISK_EVALUATION_FAILED"
            ) from error

        (
            risk_allowed,
            risk_reason,
        ) = self._decision(
            risk_decision,
            invalid_reason=(
                "SHADOW_RISK_DECISION_INVALID"
            ),
        )

        safety_allowed: (
            bool | None
        ) = None

        safety_reason: (
            str | None
        ) = "NOT_EVALUATED"

        if not risk_allowed:
            status = (
                "REJECTED_SHADOW"
            )

            decision_reason = (
                "ACCOUNT_RISK_GATE_REJECTED:"
                f"{risk_reason}"
            )

        else:
            try:
                safety_decision = (
                    self.safety_evaluator(
                        account=account,
                        proposal=proposal,
                        require_manual_approval=(
                            False
                        ),
                    )
                )
            except WebullShadowExecutionError:
                raise
            except Exception as error:
                raise WebullShadowExecutionError(
                    "SHADOW_SAFETY_EVALUATION_FAILED"
                ) from error

            (
                safety_allowed,
                safety_reason,
            ) = self._decision(
                safety_decision,
                invalid_reason=(
                    "SHADOW_SAFETY_DECISION_INVALID"
                ),
            )

            if not safety_allowed:
                status = (
                    "REJECTED_SHADOW"
                )

                decision_reason = (
                    "SAFETY_GATE_REJECTED:"
                    f"{safety_reason}"
                )
            else:
                status = (
                    "ACCEPTED_SHADOW"
                )

                decision_reason = (
                    "SHADOW_APPROVED"
                )

        account_buying_power = (
            None
            if account.buying_power
            is None
            else round(
                float(
                    account.buying_power
                ),
                2,
            )
        )

        record = (
            WebullShadowExecutionRecord(
                record_type=(
                    "SHADOW_EXECUTION"
                ),
                client_order_id=(
                    intent.client_order_id
                ),
                strategy_name=(
                    intent.strategy_name
                ),
                symbol=intent.symbol,
                side=intent.side,
                quantity=(
                    intent.quantity
                ),
                limit_price=(
                    intent.limit_price
                ),
                proposed_exposure=(
                    intent.proposed_exposure
                ),
                intent_created_at=(
                    intent.created_at
                    .astimezone(UTC)
                    .isoformat()
                    .replace(
                        "+00:00",
                        "Z",
                    )
                ),
                recorded_at=(
                    now
                    .astimezone(UTC)
                    .isoformat()
                    .replace(
                        "+00:00",
                        "Z",
                    )
                ),
                status=status,
                decision_reason=(
                    decision_reason
                ),
                risk_allowed=(
                    risk_allowed
                ),
                risk_reason=(
                    risk_reason
                ),
                safety_allowed=(
                    safety_allowed
                ),
                safety_reason=(
                    safety_reason
                ),
                account_type=(
                    account.account_type
                    .strip()
                    .upper()
                ),
                account_available_cash=(
                    round(
                        float(
                            account
                            .available_cash
                        ),
                        2,
                    )
                ),
                account_buying_power=(
                    account_buying_power
                ),
                account_current_exposure=(
                    account
                    .current_total_exposure
                ),
                account_data_is_current=(
                    bool(
                        account
                        .data_is_current
                    )
                ),
                daily_realized_pnl=(
                    round(
                        float(
                            risk_state
                            .daily_realized_pnl
                        ),
                        6,
                    )
                ),
                risk_kill_switch_active=(
                    bool(
                        risk_state
                        .kill_switch_active
                    )
                ),
                risk_data_is_current=(
                    bool(
                        risk_state
                        .data_is_current
                    )
                ),
                max_daily_loss=(
                    risk_limits
                    .max_daily_loss
                ),
                max_open_positions=(
                    risk_limits
                    .max_open_positions
                ),
                max_open_orders=(
                    risk_limits
                    .max_open_orders
                ),
                max_position_exposure=(
                    risk_limits
                    .max_position_exposure
                ),
                broker_submission_attempted=(
                    False
                ),
            )
        )

        return self.journal.append(
            record
        )
