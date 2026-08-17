from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from .historical_execution_simulator import (
    HistoricalBar,
    HistoricalExecutionError,
    HistoricalExecutionSimulator,
)
from .webull_execution import (
    WebullTradeIntent,
)
from .webull_reduce_only_close import (
    WebullReduceOnlyCloseIntent,
)


EASTERN = ZoneInfo(
    "America/New_York"
)


class HistoricalReplayError(RuntimeError):
    pass


@dataclass(frozen=True)
class HistoricalReplayResult:
    date: str
    symbol: str
    strategy: str

    status: str

    quantity: int
    entry_price: float | None
    entry_filled: bool
    entry_fill_time: datetime | None

    exit_reason: str | None
    exit_price: float | None

    realized_pnl: float
    cash_before: float
    cash_after: float

    entry_order_id: str | None
    close_order_id: str | None


def _is_yes(
    value: object,
) -> bool:
    if isinstance(value, bool):
        return value

    return (
        str(value)
        .strip()
        .upper()
        in {
            "YES",
            "TRUE",
            "1",
            "Y",
        }
    )


def _optional_float(
    value: object,
) -> float | None:
    if value in {
        None,
        "",
    }:
        return None

    try:
        return float(value)

    except (
        TypeError,
        ValueError,
    ) as error:
        raise HistoricalReplayError(
            "INVALID_NUMERIC_FIELD"
        ) from error


def _parse_timestamp(
    value: object,
) -> datetime:
    text = str(value).strip()

    if not text:
        raise HistoricalReplayError(
            "TIMESTAMP_REQUIRED"
        )

    try:
        timestamp = (
            datetime.fromisoformat(
                text.replace(
                    "Z",
                    "+00:00",
                )
            )
        )

    except ValueError as error:
        raise HistoricalReplayError(
            "INVALID_TIMESTAMP"
        ) from error

    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(
            tzinfo=EASTERN
        )

    return timestamp.astimezone(
        UTC
    )


def _manipulation_entry_time(
    date_str: str,
) -> datetime:
    try:
        local = datetime.strptime(
            date_str,
            "%Y-%m-%d",
        )

    except ValueError as error:
        raise HistoricalReplayError(
            "INVALID_TRADING_DATE"
        ) from error

    return (
        local.replace(
            hour=9,
            minute=45,
            second=0,
            microsecond=0,
            tzinfo=EASTERN,
        )
        .astimezone(UTC)
    )


def _normalize_bars(
    *,
    symbol: str,
    minute_bars: list[dict],
) -> list[HistoricalBar]:
    result = []

    for raw in minute_bars:
        required = {
            "t",
            "o",
            "h",
            "l",
            "c",
        }

        if not required.issubset(
            raw
        ):
            continue

        try:
            result.append(
                HistoricalBar(
                    symbol=symbol,
                    timestamp=(
                        _parse_timestamp(
                            raw["t"]
                        )
                    ),
                    open=float(
                        raw["o"]
                    ),
                    high=float(
                        raw["h"]
                    ),
                    low=float(
                        raw["l"]
                    ),
                    close=float(
                        raw["c"]
                    ),
                    volume=float(
                        raw.get(
                            "v",
                            0.0,
                        )
                    ),
                )
            )

        except (
            TypeError,
            ValueError,
            HistoricalExecutionError,
            HistoricalReplayError,
        ):
            continue

    result.sort(
        key=lambda item: item.timestamp
    )

    return result


def _require_isolated_symbol(
    *,
    simulator: HistoricalExecutionSimulator,
    symbol: str,
) -> None:
    if simulator.held_quantity(
        symbol
    ) > 0.00001:
        raise HistoricalReplayError(
            "SYMBOL_ALREADY_HELD"
        )

    if any(
        order.active
        for order
        in simulator.orders.values()
    ):
        raise HistoricalReplayError(
            "ACTIVE_ORDER_ALREADY_EXISTS"
        )


def _process_until_buy_terminal(
    *,
    simulator: HistoricalExecutionSimulator,
    order_id: str,
    bars: list[HistoricalBar],
    start_time: datetime,
) -> datetime | None:
    for bar in bars:
        if bar.timestamp < start_time:
            continue

        simulator.process_bar(
            bar
        )

        order = simulator.orders[
            order_id
        ]

        if order.status == "FILLED":
            return bar.timestamp

    return None


def _close_position(
    *,
    simulator: HistoricalExecutionSimulator,
    symbol: str,
    quantity: int,
    limit_price: float,
    timestamp: datetime,
    bar: HistoricalBar,
    close_order_id: str,
) -> None:
    held = simulator.held_quantity(
        symbol
    )

    intent = WebullReduceOnlyCloseIntent(
        client_order_id=close_order_id,
        symbol=symbol,
        quantity=quantity,
        limit_price=limit_price,
        confirmed_position_quantity=held,
        created_at=timestamp,
    )

    simulator.place_reduce_only_close(
        intent
    )

    simulator.process_bar(
        bar
    )

    order = simulator.orders[
        close_order_id
    ]

    if order.status != "FILLED":
        raise HistoricalReplayError(
            "HISTORICAL_CLOSE_DID_NOT_FILL"
        )

    simulator.assert_invariants()


def replay_master_row_strategy(
    *,
    simulator: HistoricalExecutionSimulator,
    row: dict[str, object],
    minute_bars: list[dict],
    strategy: str,
    quantity: int = 1,
) -> HistoricalReplayResult:
    """
    Replay one already-computed historical strategy observation
    through the deterministic execution simulator.

    This function does not recalculate the strategy signal.
    It consumes the existing master-dataset observation so the
    strategy research and execution replay cannot silently drift.

    Manipulation:
      - entry begins at 09:45 ET;
      - existing historical TARGET/STOP outcome chooses the
        corresponding historical exit trigger.

    Quick Flip:
      - entry begins at the existing confirmation timestamp;
      - there is intentionally no automatic stop;
      - the existing historical endpoint price is used to flatten
        at the final supplied session bar.

    The endpoint flatten for Quick Flip is a historical benchmark,
    not a new live Quick Flip exit rule.
    """

    key = strategy.strip().upper()

    if key not in {
        "MANIPULATION",
        "QUICK_FLIP",
    }:
        raise HistoricalReplayError(
            "UNSUPPORTED_HISTORICAL_STRATEGY"
        )

    if (
        isinstance(quantity, bool)
        or not isinstance(quantity, int)
        or quantity <= 0
    ):
        raise HistoricalReplayError(
            "INVALID_REPLAY_QUANTITY"
        )

    date_str = str(
        row.get(
            "date",
            "",
        )
    ).strip()

    symbol = (
        str(
            row.get(
                "symbol",
                "",
            )
        )
        .strip()
        .upper()
    )

    if not date_str:
        raise HistoricalReplayError(
            "TRADING_DATE_REQUIRED"
        )

    if not symbol:
        raise HistoricalReplayError(
            "SYMBOL_REQUIRED"
        )

    cash_before = float(
        simulator.cash
    )

    if (
        str(
            row.get(
                "evaluation_status",
                "",
            )
        )
        .strip()
        .upper()
        != "OK"
    ):
        return HistoricalReplayResult(
            date=date_str,
            symbol=symbol,
            strategy=key,
            status="SKIPPED_DATA_QUALITY",
            quantity=quantity,
            entry_price=None,
            entry_filled=False,
            entry_fill_time=None,
            exit_reason=None,
            exit_price=None,
            realized_pnl=0.0,
            cash_before=cash_before,
            cash_after=cash_before,
            entry_order_id=None,
            close_order_id=None,
        )

    _require_isolated_symbol(
        simulator=simulator,
        symbol=symbol,
    )

    bars = _normalize_bars(
        symbol=symbol,
        minute_bars=minute_bars,
    )

    if not bars:
        raise HistoricalReplayError(
            "NO_VALID_MINUTE_BARS"
        )

    if key == "MANIPULATION":
        signal = (
            str(
                row.get(
                    "manipulation_signal",
                    "",
                )
            )
            .strip()
            .upper()
        )

        entry = _optional_float(
            row.get(
                "manipulation_entry"
            )
        )

        if signal != "INVEST":
            return HistoricalReplayResult(
                date=date_str,
                symbol=symbol,
                strategy=key,
                status="NO_SIGNAL",
                quantity=quantity,
                entry_price=entry,
                entry_filled=False,
                entry_fill_time=None,
                exit_reason=None,
                exit_price=None,
                realized_pnl=0.0,
                cash_before=cash_before,
                cash_after=cash_before,
                entry_order_id=None,
                close_order_id=None,
            )

        target = _optional_float(
            row.get(
                "manipulation_target"
            )
        )

        stop = _optional_float(
            row.get(
                "manipulation_trading_stop"
            )
        )

        if (
            entry is None
            or target is None
            or stop is None
        ):
            raise HistoricalReplayError(
                "MANIPULATION_PRICE_FIELDS_REQUIRED"
            )

        created_at = (
            _manipulation_entry_time(
                date_str
            )
        )

        historical_filled = _is_yes(
            row.get(
                "manipulation_filled"
            )
        )

        historical_outcome = (
            str(
                row.get(
                    "manipulation_outcome",
                    "",
                )
            )
            .strip()
            .upper()
        )

    else:
        signal = (
            str(
                row.get(
                    "quick_flip_signal",
                    "",
                )
            )
            .strip()
            .upper()
        )

        entry = _optional_float(
            row.get(
                "quick_flip_entry"
            )
        )

        if signal != "INVEST":
            return HistoricalReplayResult(
                date=date_str,
                symbol=symbol,
                strategy=key,
                status="NO_SIGNAL",
                quantity=quantity,
                entry_price=entry,
                entry_filled=False,
                entry_fill_time=None,
                exit_reason=None,
                exit_price=None,
                realized_pnl=0.0,
                cash_before=cash_before,
                cash_after=cash_before,
                entry_order_id=None,
                close_order_id=None,
            )

        confirmation = (
            row.get(
                "quick_flip_confirmation_time"
            )
            or row.get(
                "quick_flip_reversal_time"
            )
        )

        if (
            entry is None
            or not confirmation
        ):
            raise HistoricalReplayError(
                "QUICK_FLIP_ENTRY_FIELDS_REQUIRED"
            )

        created_at = (
            _parse_timestamp(
                confirmation
            )
        )

        historical_filled = _is_yes(
            row.get(
                "quick_flip_filled"
            )
        )

        historical_outcome = (
            "SESSION_ENDPOINT"
        )

    entry_order_id = (
        f"HIST-{date_str}-{symbol}-"
        f"{key}-BUY"
    )

    close_order_id = (
        f"HIST-{date_str}-{symbol}-"
        f"{key}-CLOSE"
    )

    simulator.place_buy(
        WebullTradeIntent(
            client_order_id=entry_order_id,
            strategy_name=key,
            symbol=symbol,
            side="BUY",
            quantity=quantity,
            limit_price=entry,
            created_at=created_at,
        )
    )

    entry_fill_time = (
        _process_until_buy_terminal(
            simulator=simulator,
            order_id=entry_order_id,
            bars=bars,
            start_time=created_at,
        )
    )

    if entry_fill_time is None:
        simulator.cancel(
            entry_order_id
        )

        if historical_filled:
            raise HistoricalReplayError(
                "REPLAY_FILL_DISAGREES_WITH_HISTORY"
            )

        return HistoricalReplayResult(
            date=date_str,
            symbol=symbol,
            strategy=key,
            status="ENTRY_NOT_FILLED",
            quantity=quantity,
            entry_price=entry,
            entry_filled=False,
            entry_fill_time=None,
            exit_reason=None,
            exit_price=None,
            realized_pnl=0.0,
            cash_before=cash_before,
            cash_after=float(
                simulator.cash
            ),
            entry_order_id=entry_order_id,
            close_order_id=None,
        )

    if not historical_filled:
        raise HistoricalReplayError(
            "REPLAY_FILL_DISAGREES_WITH_HISTORY"
        )

    post_fill = [
        bar
        for bar in bars
        if bar.timestamp
        >= entry_fill_time
    ]

    if not post_fill:
        raise HistoricalReplayError(
            "NO_POST_FILL_BARS"
        )

    exit_reason = None
    exit_price = None
    exit_bar = None

    if key == "MANIPULATION":
        if "TARGET" in historical_outcome:
            exit_reason = "TARGET"
            exit_price = float(
                target
            )

            for bar in post_fill:
                if bar.high >= exit_price:
                    exit_bar = bar
                    break

        elif (
            "STOP" in historical_outcome
        ):
            exit_reason = "TRADING_STOP"
            stop_price = float(
                stop
            )

            for bar in post_fill:
                if bar.low <= stop_price:
                    exit_bar = bar

                    exit_price = min(
                        stop_price,
                        float(
                            bar.open
                        ),
                    )

                    break

        else:
            exit_reason = (
                "SESSION_ENDPOINT"
            )

            exit_bar = (
                post_fill[-1]
            )

            exit_price = float(
                exit_bar.close
            )

    else:
        exit_reason = (
            "SESSION_ENDPOINT"
        )

        exit_bar = (
            post_fill[-1]
        )

        endpoint = _optional_float(
            row.get(
                "quick_flip_endpoint_price"
            )
        )

        exit_price = (
            float(exit_bar.close)
            if endpoint is None
            else float(endpoint)
        )

        if not (
            exit_bar.low
            <= exit_price
            <= exit_bar.high
        ):
            exit_price = float(
                exit_bar.close
            )

    if (
        exit_bar is None
        or exit_price is None
    ):
        raise HistoricalReplayError(
            "HISTORICAL_EXIT_NOT_FOUND"
        )

    _close_position(
        simulator=simulator,
        symbol=symbol,
        quantity=quantity,
        limit_price=exit_price,
        timestamp=exit_bar.timestamp,
        bar=exit_bar,
        close_order_id=close_order_id,
    )

    if (
        simulator.held_quantity(
            symbol
        )
        > 0.00001
    ):
        raise HistoricalReplayError(
            "POSITION_NOT_FLAT_AFTER_REPLAY"
        )

    cash_after = float(
        simulator.cash
    )

    return HistoricalReplayResult(
        date=date_str,
        symbol=symbol,
        strategy=key,
        status="COMPLETED",
        quantity=quantity,
        entry_price=entry,
        entry_filled=True,
        entry_fill_time=(
            entry_fill_time
        ),
        exit_reason=exit_reason,
        exit_price=exit_price,
        realized_pnl=round(
            cash_after
            - cash_before,
            6,
        ),
        cash_before=round(
            cash_before,
            6,
        ),
        cash_after=round(
            cash_after,
            6,
        ),
        entry_order_id=entry_order_id,
        close_order_id=close_order_id,
    )
