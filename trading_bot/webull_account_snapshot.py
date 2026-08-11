from __future__ import annotations

from typing import Any

from webull.core.client import ApiClient
from webull.trade.trade_client import TradeClient

from .config import (
    WEBULL_APP_KEY,
    WEBULL_APP_SECRET,
)
from .webull_account_parser import (
    WebullResponseError,
    parse_account_balance,
    parse_account_list,
    parse_open_orders,
    parse_positions,
)
from .webull_safety import WebullAccountState


class WebullAccountSnapshotError(RuntimeError):
    pass


class WebullAccountSnapshotClient:
    """
    Read-only Webull account snapshot adapter.

    It reads account metadata, balance, positions, and open
    orders. It cannot preview, submit, replace, or cancel orders.
    """

    def __init__(
        self,
        trade_client: Any | None = None,
    ) -> None:
        if trade_client is not None:
            self._trade_client = trade_client
            return

        if not WEBULL_APP_KEY:
            raise WebullAccountSnapshotError(
                "WEBULL_APP_KEY is not configured."
            )

        if not WEBULL_APP_SECRET:
            raise WebullAccountSnapshotError(
                "WEBULL_APP_SECRET is not configured."
            )

        api_client = ApiClient(
            WEBULL_APP_KEY,
            WEBULL_APP_SECRET,
            "us",
        )

        api_client.add_endpoint(
            "us",
            "api.webull.com",
        )

        self._trade_client = TradeClient(api_client)

    @staticmethod
    def _read_json_response(
        response: Any,
        *,
        label: str,
    ) -> Any:
        status_code = getattr(
            response,
            "status_code",
            None,
        )

        if status_code != 200:
            raise WebullAccountSnapshotError(
                f"{label} failed with HTTP "
                f"{status_code!r}."
            )

        try:
            return response.json()
        except Exception as error:
            raise WebullAccountSnapshotError(
                f"{label} returned invalid JSON."
            ) from error

    def get_account_state(
        self,
    ) -> WebullAccountState:
        try:
            account_payload = self._read_json_response(
                self._trade_client.account_v2
                .get_account_list(),
                label="Webull account lookup",
            )

            account = parse_account_list(
                account_payload
            )

            balance_payload = self._read_json_response(
                self._trade_client.account_v2
                .get_account_balance(
                    account.account_id
                ),
                label="Webull balance lookup",
            )

            balance = parse_account_balance(
                balance_payload
            )

            positions_payload = (
                self._read_json_response(
                    self._trade_client.account_v2
                    .get_account_position(
                        account.account_id
                    ),
                    label="Webull positions lookup",
                )
            )

            positions = parse_positions(
                positions_payload
            )

            open_orders_payload = (
                self._read_json_response(
                    self._trade_client.order_v3
                    .get_order_open(
                        account.account_id,
                        page_size=100,
                    ),
                    label="Webull open-orders lookup",
                )
            )

            open_orders = parse_open_orders(
                open_orders_payload
            )

        except WebullResponseError as error:
            raise WebullAccountSnapshotError(
                "Webull account data failed strict "
                f"validation: {error}"
            ) from error

        position_exposure = round(
            sum(
                position.market_value
                for position in positions
            ),
            2,
        )

        open_buy_order_exposure = round(
            sum(
                order.reserved_exposure
                for order in open_orders
            ),
            2,
        )

        return WebullAccountState(
            account_type=account.account_type,
            available_cash=balance.available_cash,
            position_exposure=position_exposure,
            open_buy_order_exposure=(
                open_buy_order_exposure
            ),
            data_is_current=True,
        )
