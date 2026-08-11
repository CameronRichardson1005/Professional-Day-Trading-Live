from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class WebullResponseError(ValueError):
    pass


@dataclass(frozen=True)
class ParsedWebullAccount:
    account_id: str
    account_type: str


@dataclass(frozen=True)
class ParsedWebullBalance:
    available_cash: float


@dataclass(frozen=True)
class ParsedWebullPosition:
    symbol: str
    quantity: float
    market_price: float
    market_value: float


@dataclass(frozen=True)
class ParsedWebullOpenOrder:
    symbol: str
    side: str
    remaining_quantity: float
    limit_price: float
    reserved_exposure: float


def _as_dict(
    payload: Any,
    *,
    label: str,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise WebullResponseError(
            f"{label} response must be an object."
        )

    return payload


def _first_present(
    payload: dict[str, Any],
    names: tuple[str, ...],
    *,
    label: str,
) -> Any:
    found = [
        payload[name]
        for name in names
        if name in payload
        and payload[name] not in {None, ""}
    ]

    if not found:
        raise WebullResponseError(
            f"{label} field was missing."
        )

    if len(found) > 1:
        normalized = {
            str(value).strip()
            for value in found
        }

        if len(normalized) > 1:
            raise WebullResponseError(
                f"{label} fields disagreed."
            )

    return found[0]


def _number(
    value: Any,
    *,
    label: str,
) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as error:
        raise WebullResponseError(
            f"{label} must be numeric."
        ) from error

    if result < 0:
        raise WebullResponseError(
            f"{label} cannot be negative."
        )

    return result


def _records(
    payload: Any,
    *,
    possible_keys: tuple[str, ...],
    label: str,
) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        records = payload
    elif isinstance(payload, dict):
        records = None

        for key in possible_keys:
            value = payload.get(key)

            if isinstance(value, list):
                records = value
                break

        if records is None:
            raise WebullResponseError(
                f"{label} response did not contain a list."
            )
    else:
        raise WebullResponseError(
            f"{label} response had an invalid type."
        )

    if not all(
        isinstance(record, dict)
        for record in records
    ):
        raise WebullResponseError(
            f"{label} records must be objects."
        )

    return records


def parse_account_list(
    payload: Any,
) -> ParsedWebullAccount:
    accounts = _records(
        payload,
        possible_keys=(
            "accounts",
            "account_list",
            "data",
        ),
        label="Account list",
    )

    if len(accounts) != 1:
        raise WebullResponseError(
            "Exactly one Webull trading account is required."
        )

    account = accounts[0]

    account_id = str(
        _first_present(
            account,
            (
                "account_id",
                "accountId",
            ),
            label="Account ID",
        )
    ).strip()

    account_type = str(
        _first_present(
            account,
            (
                "account_type",
                "accountType",
                "type",
            ),
            label="Account type",
        )
    ).strip().upper()

    if not account_id:
        raise WebullResponseError(
            "Account ID cannot be empty."
        )

    if account_type not in {"CASH", "MARGIN"}:
        raise WebullResponseError(
            "Webull account type was not CASH or MARGIN."
        )

    return ParsedWebullAccount(
        account_id=account_id,
        account_type=account_type,
    )


def parse_account_balance(
    payload: Any,
) -> ParsedWebullBalance:
    balance = _as_dict(
        payload,
        label="Account balance",
    )

    currency_assets = balance.get(
        "account_currency_assets"
    )

    if currency_assets is not None:
        if not isinstance(currency_assets, list):
            raise WebullResponseError(
                "Account currency assets must be a list."
            )

        if not all(
            isinstance(asset, dict)
            for asset in currency_assets
        ):
            raise WebullResponseError(
                "Account currency asset records "
                "must be objects."
            )

        usd_assets = [
            asset
            for asset in currency_assets
            if str(
                asset.get("currency", "")
            ).strip().upper() == "USD"
        ]

        if len(usd_assets) != 1:
            raise WebullResponseError(
                "Exactly one USD account currency "
                "asset is required."
            )

        total_asset_currency = str(
            balance.get(
                "total_asset_currency",
                "",
            )
        ).strip().upper()

        if (
            total_asset_currency
            and total_asset_currency != "USD"
        ):
            raise WebullResponseError(
                "Total asset currency must be USD."
            )

        usd_asset = usd_assets[0]

        settled_cash = _number(
            _first_present(
                usd_asset,
                (
                    "settled_cash",
                    "settledCash",
                ),
                label="USD settled cash",
            ),
            label="USD settled cash",
        )

        cash_balance = _number(
            _first_present(
                usd_asset,
                (
                    "cash_balance",
                    "cashBalance",
                ),
                label="USD cash balance",
            ),
            label="USD cash balance",
        )

        cash_candidates = [
            settled_cash,
            cash_balance,
        ]

        if (
            "total_cash_balance" in balance
            and balance["total_cash_balance"]
            not in {None, ""}
        ):
            cash_candidates.append(
                _number(
                    balance["total_cash_balance"],
                    label="Total cash balance",
                )
            )

        # Fail-safe rule: use the most conservative confirmed
        # cash figure. Never use buying power, option buying
        # power, or unsettled cash.
        available_cash = min(cash_candidates)

        return ParsedWebullBalance(
            available_cash=round(
                available_cash,
                2,
            ),
        )

    nested = balance.get("data")

    if isinstance(nested, dict):
        balance = nested

    available_cash = _number(
        _first_present(
            balance,
            (
                "available_cash",
                "availableCash",
                "cash_available",
                "cashAvailable",
                "settled_cash",
                "settledCash",
                "cash_balance",
                "cashBalance",
            ),
            label="Available cash",
        ),
        label="Available cash",
    )

    return ParsedWebullBalance(
        available_cash=round(
            available_cash,
            2,
        ),
    )

def parse_positions(
    payload: Any,
) -> list[ParsedWebullPosition]:
    positions = _records(
        payload,
        possible_keys=(
            "positions",
            "position_list",
            "data",
        ),
        label="Positions",
    )

    parsed: list[ParsedWebullPosition] = []

    for position in positions:
        symbol = str(
            _first_present(
                position,
                (
                    "symbol",
                    "ticker",
                ),
                label="Position symbol",
            )
        ).strip().upper()

        quantity = _number(
            _first_present(
                position,
                (
                    "quantity",
                    "position_quantity",
                    "positionQuantity",
                    "qty",
                ),
                label=f"{symbol} position quantity",
            ),
            label=f"{symbol} position quantity",
        )

        market_price = _number(
            _first_present(
                position,
                (
                    "market_price",
                    "marketPrice",
                    "last_price",
                    "lastPrice",
                ),
                label=f"{symbol} market price",
            ),
            label=f"{symbol} market price",
        )

        calculated_value = round(
            quantity * market_price,
            2,
        )

        raw_market_value = None

        for key in (
            "market_value",
            "marketValue",
            "position_value",
            "positionValue",
        ):
            if key in position:
                raw_market_value = _number(
                    position[key],
                    label=f"{symbol} market value",
                )
                break

        # Webull may calculate market value and market price
        # at slightly different moments or precision levels.
        # Use the larger confirmed value so exposure is never
        # understated.
        conservative_market_value = (
            calculated_value
            if raw_market_value is None
            else max(
                calculated_value,
                raw_market_value,
            )
        )

        parsed.append(
            ParsedWebullPosition(
                symbol=symbol,
                quantity=quantity,
                market_price=market_price,
                market_value=round(
                    conservative_market_value,
                    2,
                ),
            )
        )

    return parsed


def parse_open_orders(
    payload: Any,
) -> list[ParsedWebullOpenOrder]:
    raw_records = _records(
        payload,
        possible_keys=(
            "orders",
            "open_orders",
            "order_list",
            "data",
        ),
        label="Open orders",
    )

    orders: list[dict[str, Any]] = []

    for record in raw_records:
        nested_orders = record.get("orders")

        if nested_orders is None:
            orders.append(record)
            continue

        if not isinstance(nested_orders, list):
            raise WebullResponseError(
                "Nested open orders must be a list."
            )

        if not all(
            isinstance(order, dict)
            for order in nested_orders
        ):
            raise WebullResponseError(
                "Nested open-order records must be objects."
            )

        orders.extend(nested_orders)

    parsed: list[ParsedWebullOpenOrder] = []

    for order in orders:
        symbol = str(
            _first_present(
                order,
                (
                    "symbol",
                    "ticker",
                ),
                label="Order symbol",
            )
        ).strip().upper()

        side = str(
            _first_present(
                order,
                (
                    "side",
                    "order_side",
                    "orderSide",
                ),
                label=f"{symbol} order side",
            )
        ).strip().upper()

        if side not in {"BUY", "SELL"}:
            raise WebullResponseError(
                f"{symbol} order side was invalid."
            )

        total_quantity = _number(
            _first_present(
                order,
                (
                    "total_quantity",
                    "totalQuantity",
                    "quantity",
                    "order_quantity",
                    "orderQuantity",
                    "qty",
                ),
                label=f"{symbol} order quantity",
            ),
            label=f"{symbol} order quantity",
        )

        filled_quantity = 0.0

        for key in (
            "filled_quantity",
            "filledQuantity",
            "filled_qty",
            "filledQty",
        ):
            if (
                key in order
                and order[key] not in {None, ""}
            ):
                filled_quantity = _number(
                    order[key],
                    label=f"{symbol} filled quantity",
                )
                break

        calculated_remaining = (
            total_quantity - filled_quantity
        )

        if calculated_remaining < 0:
            raise WebullResponseError(
                f"{symbol} filled quantity exceeded "
                "the order quantity."
            )

        remaining_value = None

        for key in (
            "remain_quantity",
            "remainQuantity",
            "remaining_quantity",
            "remainingQuantity",
        ):
            if (
                key in order
                and order[key] not in {None, ""}
            ):
                remaining_value = _number(
                    order[key],
                    label=f"{symbol} remaining quantity",
                )
                break

        remaining_quantity = (
            calculated_remaining
            if remaining_value is None
            else remaining_value
        )

        if (
            remaining_value is not None
            and abs(
                remaining_value
                - calculated_remaining
            ) > 0.000001
        ):
            raise WebullResponseError(
                f"{symbol} remaining quantity fields "
                "disagreed."
            )

        limit_price = _number(
            _first_present(
                order,
                (
                    "limit_price",
                    "limitPrice",
                    "price",
                ),
                label=f"{symbol} limit price",
            ),
            label=f"{symbol} limit price",
        )

        reserved_exposure = (
            round(
                remaining_quantity * limit_price,
                2,
            )
            if side == "BUY"
            else 0.0
        )

        parsed.append(
            ParsedWebullOpenOrder(
                symbol=symbol,
                side=side,
                remaining_quantity=(
                    remaining_quantity
                ),
                limit_price=limit_price,
                reserved_exposure=(
                    reserved_exposure
                ),
            )
        )

    return parsed
