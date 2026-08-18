from __future__ import annotations

from datetime import date
from typing import Any


class WebullBrokerHistoryError(RuntimeError):
    pass


class WebullStrictBrokerHistoryReader:
    """
    Read-only paginated Webull Order History reader.

    This layer only acquires broker history. It does not
    calculate P&L and cannot place, replace, cancel, or close
    orders.

    Pagination fails closed if cursor progression or response
    completeness cannot be proven.
    """

    def __init__(
        self,
        *,
        trade_client: Any,
        account_id: str,
        page_size: int = 100,
        max_pages: int = 1000,
    ) -> None:
        account_id = str(
            account_id
        ).strip()

        if not account_id:
            raise WebullBrokerHistoryError(
                "HISTORY_ACCOUNT_ID_REQUIRED"
            )

        if (
            isinstance(
                page_size,
                bool,
            )
            or not isinstance(
                page_size,
                int,
            )
            or page_size <= 0
            or page_size > 100
        ):
            raise WebullBrokerHistoryError(
                "HISTORY_PAGE_SIZE_INVALID"
            )

        if (
            isinstance(
                max_pages,
                bool,
            )
            or not isinstance(
                max_pages,
                int,
            )
            or max_pages <= 0
        ):
            raise WebullBrokerHistoryError(
                "HISTORY_MAX_PAGES_INVALID"
            )

        self.trade_client = (
            trade_client
        )

        self.account_id = (
            account_id
        )

        self.page_size = (
            page_size
        )

        self.max_pages = (
            max_pages
        )

    @staticmethod
    def _parse_date(
        value: str,
        *,
        field: str,
    ) -> date:
        if not isinstance(
            value,
            str,
        ):
            raise WebullBrokerHistoryError(
                f"HISTORY_{field}_INVALID"
            )

        try:
            return date.fromisoformat(
                value
            )
        except ValueError as error:
            raise WebullBrokerHistoryError(
                f"HISTORY_{field}_INVALID"
            ) from error

    @classmethod
    def _validate_range(
        cls,
        *,
        start_date: str,
        end_date: str,
    ) -> None:
        start = cls._parse_date(
            start_date,
            field="START_DATE",
        )

        end = cls._parse_date(
            end_date,
            field="END_DATE",
        )

        if end <= start:
            raise WebullBrokerHistoryError(
                "HISTORY_DATE_RANGE_INVALID"
            )

        if (
            end.year
            - start.year
            > 2
        ):
            raise WebullBrokerHistoryError(
                "HISTORY_DATE_RANGE_TOO_LARGE"
            )

        two_year_anniversary = (
            start.replace(
                year=start.year + 2
            )
            if not (
                start.month == 2
                and start.day == 29
            )
            else start.replace(
                year=start.year + 2,
                day=28,
            )
        )

        if end > two_year_anniversary:
            raise WebullBrokerHistoryError(
                "HISTORY_DATE_RANGE_TOO_LARGE"
            )

    @staticmethod
    def _group_cursor(
        group: Any,
    ) -> str:
        if not isinstance(
            group,
            dict,
        ):
            raise WebullBrokerHistoryError(
                "HISTORY_GROUP_INVALID"
            )

        direct = str(
            group.get(
                "client_order_id",
                "",
            )
        ).strip()

        if direct:
            return direct

        orders = group.get(
            "orders"
        )

        if not isinstance(
            orders,
            list,
        ):
            raise WebullBrokerHistoryError(
                "HISTORY_GROUP_CURSOR_MISSING"
            )

        nested_ids = []

        for order in orders:
            if not isinstance(
                order,
                dict,
            ):
                raise WebullBrokerHistoryError(
                    "HISTORY_ORDER_INVALID"
                )

            value = str(
                order.get(
                    "client_order_id",
                    "",
                )
            ).strip()

            if value:
                nested_ids.append(
                    value
                )

        unique = list(
            dict.fromkeys(
                nested_ids
            )
        )

        if len(unique) != 1:
            raise WebullBrokerHistoryError(
                "HISTORY_GROUP_CURSOR_MISSING"
            )

        return unique[0]

    def get_history_payload(
        self,
        *,
        start_date: str,
        end_date: str,
    ) -> list[dict[str, Any]]:
        self._validate_range(
            start_date=start_date,
            end_date=end_date,
        )

        combined: list[
            dict[str, Any]
        ] = []

        groups_by_cursor: dict[
            str,
            dict[str, Any],
        ] = {}

        previous_page_cursor: (
            str | None
        ) = None

        for page_number in range(
            1,
            self.max_pages + 1,
        ):
            try:
                response = (
                    self.trade_client
                    .order_v3
                    .get_order_history(
                        self.account_id,
                        page_size=(
                            self.page_size
                        ),
                        start_date=(
                            start_date
                        ),
                        end_date=(
                            end_date
                        ),
                        last_client_order_id=(
                            previous_page_cursor
                        ),
                    )
                )
            except Exception as error:
                raise WebullBrokerHistoryError(
                    "HISTORY_REQUEST_FAILED"
                ) from error

            if (
                getattr(
                    response,
                    "status_code",
                    None,
                )
                != 200
            ):
                raise WebullBrokerHistoryError(
                    "HISTORY_REQUEST_FAILED"
                )

            try:
                payload = (
                    response.json()
                )
            except Exception as error:
                raise WebullBrokerHistoryError(
                    "HISTORY_RESPONSE_JSON_INVALID"
                ) from error

            if not isinstance(
                payload,
                list,
            ):
                raise WebullBrokerHistoryError(
                    "HISTORY_RESPONSE_NOT_LIST"
                )

            if not payload:
                return combined

            page_last_cursor = None

            for group in payload:
                cursor = (
                    self._group_cursor(
                        group
                    )
                )

                page_last_cursor = (
                    cursor
                )

                prior = (
                    groups_by_cursor.get(
                        cursor
                    )
                )

                if prior is not None:
                    if prior != group:
                        raise WebullBrokerHistoryError(
                            "HISTORY_DUPLICATE_GROUP_CONFLICT"
                        )

                    continue

                groups_by_cursor[
                    cursor
                ] = group

                combined.append(
                    group
                )

            if not page_last_cursor:
                raise WebullBrokerHistoryError(
                    "HISTORY_PAGE_CURSOR_MISSING"
                )

            if (
                page_last_cursor
                == previous_page_cursor
            ):
                raise WebullBrokerHistoryError(
                    "HISTORY_CURSOR_DID_NOT_ADVANCE"
                )

            previous_page_cursor = (
                page_last_cursor
            )

        raise WebullBrokerHistoryError(
            "HISTORY_MAX_PAGES_EXCEEDED"
        )
