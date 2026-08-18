from __future__ import annotations

import copy
import math
from typing import Any


class WebullOrderDetailReconciliationError(
    RuntimeError
):
    pass


class WebullOrderDetailReconciler:
    """
    Read-only reconciliation of delayed Order History records
    against authoritative per-order Order Detail responses.

    This class:
    - cannot submit orders
    - cannot replace orders
    - cannot cancel orders
    - cannot close positions
    - does not calculate realized P&L

    It only returns a reconciled history payload suitable for
    later strict fill parsing.
    """

    def __init__(
        self,
        *,
        trade_client: Any,
        account_id: str,
    ) -> None:
        account_id = str(
            account_id
        ).strip()

        if not account_id:
            raise (
                WebullOrderDetailReconciliationError(
                    "DETAIL_ACCOUNT_ID_REQUIRED"
                )
            )

        self.trade_client = (
            trade_client
        )

        self.account_id = (
            account_id
        )

    @staticmethod
    def _quantity(
        value: Any,
        *,
        field: str,
    ) -> float:
        try:
            result = float(
                value
            )
        except (
            TypeError,
            ValueError,
        ) as error:
            raise (
                WebullOrderDetailReconciliationError(
                    f"{field}_INVALID"
                )
            ) from error

        if (
            not math.isfinite(
                result
            )
            or result < 0
        ):
            raise (
                WebullOrderDetailReconciliationError(
                    f"{field}_INVALID"
                )
            )

        return result

    @staticmethod
    def _positive_price(
        value: Any,
    ) -> float:
        try:
            result = float(
                value
            )
        except (
            TypeError,
            ValueError,
        ) as error:
            raise (
                WebullOrderDetailReconciliationError(
                    "DETAIL_FILLED_PRICE_INVALID"
                )
            ) from error

        if (
            not math.isfinite(
                result
            )
            or result <= 0
        ):
            raise (
                WebullOrderDetailReconciliationError(
                    "DETAIL_FILLED_PRICE_INVALID"
                )
            )

        return result

    @staticmethod
    def _client_order_id(
        order: dict[str, Any],
    ) -> str:
        return str(
            order.get(
                "client_order_id",
                "",
            )
        ).strip()

    @classmethod
    def _index_history(
        cls,
        payload: Any,
    ) -> dict[
        str,
        dict[str, Any],
    ]:
        if not isinstance(
            payload,
            list,
        ):
            raise (
                WebullOrderDetailReconciliationError(
                    "DETAIL_HISTORY_PAYLOAD_NOT_LIST"
                )
            )

        index: dict[
            str,
            dict[str, Any],
        ] = {}

        for group in payload:
            if not isinstance(
                group,
                dict,
            ):
                raise (
                    WebullOrderDetailReconciliationError(
                        "DETAIL_HISTORY_GROUP_INVALID"
                    )
                )

            orders = group.get(
                "orders"
            )

            if not isinstance(
                orders,
                list,
            ):
                raise (
                    WebullOrderDetailReconciliationError(
                        "DETAIL_HISTORY_ORDERS_INVALID"
                    )
                )

            for order in orders:
                if not isinstance(
                    order,
                    dict,
                ):
                    raise (
                        WebullOrderDetailReconciliationError(
                            "DETAIL_HISTORY_ORDER_INVALID"
                        )
                    )

                key = (
                    cls._client_order_id(
                        order
                    )
                )

                if not key:
                    continue

                if key in index:
                    raise (
                        WebullOrderDetailReconciliationError(
                            "DETAIL_DUPLICATE_CLIENT_ORDER_ID"
                        )
                    )

                index[
                    key
                ] = order

        return index

    @staticmethod
    def _extract_detail_order(
        payload: Any,
    ) -> dict[str, Any]:
        if isinstance(
            payload,
            dict,
        ):
            if "orders" not in payload:
                return payload

            orders = payload[
                "orders"
            ]

            if (
                not isinstance(
                    orders,
                    list,
                )
                or len(
                    orders
                ) != 1
                or not isinstance(
                    orders[0],
                    dict,
                )
            ):
                raise (
                    WebullOrderDetailReconciliationError(
                        "DETAIL_RESPONSE_SHAPE_INVALID"
                    )
                )

            return orders[0]

        if (
            isinstance(
                payload,
                list,
            )
            and len(
                payload
            ) == 1
            and isinstance(
                payload[0],
                dict,
            )
        ):
            return payload[0]

        raise (
            WebullOrderDetailReconciliationError(
                "DETAIL_RESPONSE_SHAPE_INVALID"
            )
        )

    def _get_detail(
        self,
        client_order_id: str,
    ) -> dict[str, Any]:
        try:
            response = (
                self.trade_client
                .order_v3
                .get_order_detail(
                    self.account_id,
                    client_order_id,
                )
            )
        except Exception as error:
            raise (
                WebullOrderDetailReconciliationError(
                    "DETAIL_REQUEST_FAILED"
                )
            ) from error

        if (
            getattr(
                response,
                "status_code",
                None,
            )
            != 200
        ):
            raise (
                WebullOrderDetailReconciliationError(
                    "DETAIL_REQUEST_FAILED"
                )
            )

        try:
            payload = (
                response.json()
            )
        except Exception as error:
            raise (
                WebullOrderDetailReconciliationError(
                    "DETAIL_RESPONSE_JSON_INVALID"
                )
            ) from error

        order = (
            self._extract_detail_order(
                payload
            )
        )

        returned_key = (
            self._client_order_id(
                order
            )
        )

        if (
            not returned_key
            or returned_key
            != client_order_id
        ):
            raise (
                WebullOrderDetailReconciliationError(
                    "DETAIL_CLIENT_ORDER_ID_MISMATCH"
                )
            )

        return order

    @staticmethod
    def _identity(
        order: dict[str, Any],
        field: str,
    ) -> str:
        return str(
            order.get(
                field,
                "",
            )
        ).strip().upper()

    @classmethod
    def _reconcile_existing(
        cls,
        *,
        historical: dict[str, Any],
        detail: dict[str, Any],
    ) -> None:
        for field, reason in (
            (
                "symbol",
                "DETAIL_SYMBOL_MISMATCH",
            ),
            (
                "side",
                "DETAIL_SIDE_MISMATCH",
            ),
        ):
            old_value = cls._identity(
                historical,
                field,
            )

            new_value = cls._identity(
                detail,
                field,
            )

            if (
                old_value
                and new_value
                and old_value != new_value
            ):
                raise (
                    WebullOrderDetailReconciliationError(
                        reason
                    )
                )

        historical_quantity = (
            cls._quantity(
                historical.get(
                    "filled_quantity",
                    0,
                ),
                field=(
                    "HISTORY_FILLED_QUANTITY"
                ),
            )
        )

        if "filled_quantity" not in detail:
            raise (
                WebullOrderDetailReconciliationError(
                    "DETAIL_FILLED_QUANTITY_MISSING"
                )
            )

        detail_quantity = (
            cls._quantity(
                detail.get(
                    "filled_quantity"
                ),
                field=(
                    "DETAIL_FILLED_QUANTITY"
                ),
            )
        )

        tolerance = 1e-9

        if (
            detail_quantity
            + tolerance
            < historical_quantity
        ):
            raise (
                WebullOrderDetailReconciliationError(
                    "DETAIL_FILL_QUANTITY_REGRESSION"
                )
            )

        if detail_quantity > 0:
            cls._positive_price(
                detail.get(
                    "filled_price"
                )
            )

        if (
            detail_quantity
            > historical_quantity
            + tolerance
        ):
            filled_time = (
                detail.get(
                    "filled_time"
                )
            )

            if filled_time in {
                None,
                "",
            }:
                raise (
                    WebullOrderDetailReconciliationError(
                        "DETAIL_NEW_FILL_TIME_MISSING"
                    )
                )

        preserve_fields = {
            "client_order_id",
        }

        for key, value in detail.items():
            if key in preserve_fields:
                continue

            if (
                key == "filled_time"
                and value in {
                    None,
                    "",
                }
            ):
                continue

            historical[
                key
            ] = value

    @classmethod
    def _new_history_group(
        cls,
        detail: dict[str, Any],
    ) -> dict[str, Any] | None:
        if "filled_quantity" not in detail:
            raise (
                WebullOrderDetailReconciliationError(
                    "DETAIL_FILLED_QUANTITY_MISSING"
                )
            )

        quantity = cls._quantity(
            detail.get(
                "filled_quantity"
            ),
            field=(
                "DETAIL_FILLED_QUANTITY"
            ),
        )

        if quantity == 0:
            return None

        symbol = cls._identity(
            detail,
            "symbol",
        )

        side = cls._identity(
            detail,
            "side",
        )

        if not symbol:
            raise (
                WebullOrderDetailReconciliationError(
                    "DETAIL_SYMBOL_MISSING"
                )
            )

        if side not in {
            "BUY",
            "SELL",
        }:
            raise (
                WebullOrderDetailReconciliationError(
                    "DETAIL_SIDE_INVALID"
                )
            )

        cls._positive_price(
            detail.get(
                "filled_price"
            )
        )

        if detail.get(
            "filled_time"
        ) in {
            None,
            "",
        }:
            raise (
                WebullOrderDetailReconciliationError(
                    "DETAIL_NEW_FILL_TIME_MISSING"
                )
            )

        return {
            "client_order_id": (
                cls._client_order_id(
                    detail
                )
            ),
            "combo_type": "NORMAL",
            "orders": [
                copy.deepcopy(
                    detail
                )
            ],
        }

    def reconcile(
        self,
        *,
        history_payload: Any,
        client_order_ids: list[str]
        | tuple[str, ...],
    ) -> list[dict[str, Any]]:
        reconciled = copy.deepcopy(
            history_payload
        )

        history_index = (
            self._index_history(
                reconciled
            )
        )

        requested: list[str] = []

        seen: set[str] = set()

        for raw_key in client_order_ids:
            key = str(
                raw_key
            ).strip()

            if not key:
                raise (
                    WebullOrderDetailReconciliationError(
                        "DETAIL_CLIENT_ORDER_ID_REQUIRED"
                    )
                )

            if key in seen:
                continue

            seen.add(
                key
            )

            requested.append(
                key
            )

        for key in requested:
            detail = self._get_detail(
                key
            )

            existing = (
                history_index.get(
                    key
                )
            )

            if existing is not None:
                self._reconcile_existing(
                    historical=existing,
                    detail=detail,
                )

                continue

            new_group = (
                self._new_history_group(
                    detail
                )
            )

            if new_group is None:
                continue

            reconciled.append(
                new_group
            )

            history_index[
                key
            ] = new_group[
                "orders"
            ][0]

        return reconciled
