from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class WebullPreviewStoreError(RuntimeError):
    pass


class WebullPreviewStore:
    """
    Local persistence for redacted Webull preview proposals.

    This store never contains approval tokens, account IDs,
    credentials, broker responses, or order-submission data.
    """

    def __init__(
        self,
        path: Path | str = (
            "state/webull_preview_proposals.json"
        ),
    ) -> None:
        self.path = Path(path)
        self.temp_path = self.path.with_suffix(
            self.path.suffix + ".tmp"
        )

    @staticmethod
    def _validate_preview(
        preview: Any,
    ) -> dict[str, Any]:
        if not isinstance(preview, dict):
            raise WebullPreviewStoreError(
                "Preview record must be an object."
            )

        required = {
            "symbol",
            "quantity",
            "limitPrice",
            "proposedExposure",
            "status",
            "createdAt",
        }

        optional = {
            "targetPrice",
            "tradingStopPrice",
            "takeProfit1",
            "takeProfit2",
            "strategyName",
            "rewardRisk",
            "confirmationTime",
            "retracementPrice",
            "impulseAtrMultiple",
            "pullbackVolumeRatio",
        }

        unknown = set(preview) - required - optional

        if unknown:
            raise WebullPreviewStoreError(
                "Preview record contains unsupported fields: "
                + ", ".join(sorted(unknown))
            )

        missing = required - set(preview)

        if missing:
            raise WebullPreviewStoreError(
                "Preview record is missing fields: "
                + ", ".join(sorted(missing))
            )

        symbol = str(preview["symbol"]).strip().upper()
        status = str(preview["status"]).strip().upper()

        try:
            quantity = int(preview["quantity"])
            limit_price = float(preview["limitPrice"])
            proposed_exposure = float(
                preview["proposedExposure"]
            )

            raw_target_price = preview.get(
                "targetPrice"
            )
            raw_stop_price = preview.get(
                "tradingStopPrice"
            )
            raw_take_profit_1 = preview.get(
                "takeProfit1"
            )
            raw_take_profit_2 = preview.get(
                "takeProfit2"
            )

            target_price = (
                None
                if raw_target_price is None
                else float(raw_target_price)
            )
            stop_price = (
                None
                if raw_stop_price is None
                else float(raw_stop_price)
            )
            take_profit_1 = (
                None
                if raw_take_profit_1 is None
                else float(raw_take_profit_1)
            )
            take_profit_2 = (
                None
                if raw_take_profit_2 is None
                else float(raw_take_profit_2)
            )
        except (TypeError, ValueError) as error:
            raise WebullPreviewStoreError(
                "Preview numeric fields are invalid."
            ) from error

        if not symbol:
            raise WebullPreviewStoreError(
                "Preview symbol is required."
            )

        if status != "PREVIEW READY":
            raise WebullPreviewStoreError(
                "Only PREVIEW READY records may be stored."
            )

        if quantity <= 0:
            raise WebullPreviewStoreError(
                "Preview quantity must be positive."
            )

        if limit_price <= 0:
            raise WebullPreviewStoreError(
                "Preview limit price must be positive."
            )

        if (
            (target_price is None)
            != (stop_price is None)
        ):
            raise WebullPreviewStoreError(
                "Preview target and trading stop must "
                "either both be present or both be absent."
            )

        if target_price is not None:
            if target_price <= limit_price:
                raise WebullPreviewStoreError(
                    "Preview target must be above "
                    "the BUY limit price."
                )

            if stop_price <= 0:
                raise WebullPreviewStoreError(
                    "Preview trading stop must be positive."
                )

            if stop_price >= limit_price:
                raise WebullPreviewStoreError(
                    "Preview trading stop must be below "
                    "the BUY limit price."
                )

        if (
            (take_profit_1 is None)
            != (take_profit_2 is None)
        ):
            raise WebullPreviewStoreError(
                "Quick Flip take-profit levels must "
                "either both be present or both be absent."
            )

        if take_profit_1 is not None:
            if take_profit_1 <= 0:
                raise WebullPreviewStoreError(
                    "Quick Flip takeProfit1 must be positive."
                )

            if take_profit_2 <= 0:
                raise WebullPreviewStoreError(
                    "Quick Flip takeProfit2 must be positive."
                )

            if take_profit_2 <= take_profit_1:
                raise WebullPreviewStoreError(
                    "Quick Flip takeProfit2 must be above "
                    "takeProfit1."
                )

        expected_exposure = round(
            quantity * limit_price,
            2,
        )

        if round(proposed_exposure, 2) != expected_exposure:
            raise WebullPreviewStoreError(
                "Preview proposed exposure does not match "
                "quantity multiplied by limit price."
            )

        strategy_name = preview.get(
            "strategyName"
        )
        confirmation_time = preview.get(
            "confirmationTime"
        )

        if strategy_name is not None:
            if (
                not isinstance(strategy_name, str)
                or not strategy_name.strip()
            ):
                raise WebullPreviewStoreError(
                    "Preview strategyName must be a "
                    "non-empty string when provided."
                )

            strategy_name = strategy_name.strip()

        if confirmation_time is not None:
            if (
                not isinstance(confirmation_time, str)
                or not confirmation_time.strip()
            ):
                raise WebullPreviewStoreError(
                    "Preview confirmationTime must be a "
                    "non-empty string when provided."
                )

            confirmation_time = (
                confirmation_time.strip()
            )

        metadata_numbers = {}

        for field in (
            "rewardRisk",
            "retracementPrice",
            "impulseAtrMultiple",
            "pullbackVolumeRatio",
        ):
            raw_value = preview.get(field)

            if raw_value is None:
                metadata_numbers[field] = None
                continue

            try:
                value = float(raw_value)
            except (TypeError, ValueError) as error:
                raise WebullPreviewStoreError(
                    f"Preview {field} is invalid."
                ) from error

            if not (
                float("-inf") < value < float("inf")
            ):
                raise WebullPreviewStoreError(
                    f"Preview {field} must be finite."
                )

            metadata_numbers[field] = value

        if (
            metadata_numbers["rewardRisk"] is not None
            and metadata_numbers["rewardRisk"] <= 0
        ):
            raise WebullPreviewStoreError(
                "Preview rewardRisk must be positive."
            )

        if (
            metadata_numbers["retracementPrice"] is not None
            and metadata_numbers["retracementPrice"] <= 0
        ):
            raise WebullPreviewStoreError(
                "Preview retracementPrice must be positive."
            )

        if (
            metadata_numbers["impulseAtrMultiple"] is not None
            and metadata_numbers["impulseAtrMultiple"] < 0
        ):
            raise WebullPreviewStoreError(
                "Preview impulseAtrMultiple cannot be negative."
            )

        if (
            metadata_numbers["pullbackVolumeRatio"] is not None
            and metadata_numbers["pullbackVolumeRatio"] < 0
        ):
            raise WebullPreviewStoreError(
                "Preview pullbackVolumeRatio cannot be negative."
            )

        created_at = preview["createdAt"]

        if not isinstance(created_at, str):
            raise WebullPreviewStoreError(
                "Preview createdAt must be a string."
            )

        try:
            parsed = datetime.fromisoformat(
                created_at.replace("Z", "+00:00")
            )
        except ValueError as error:
            raise WebullPreviewStoreError(
                "Preview createdAt is invalid."
            ) from error

        if parsed.tzinfo is None:
            raise WebullPreviewStoreError(
                "Preview createdAt must include a timezone."
            )

        validated = {
            "symbol": symbol,
            "quantity": quantity,
            "limitPrice": round(limit_price, 4),
            "proposedExposure": expected_exposure,
            "status": "PREVIEW READY",
            "createdAt": (
                parsed.astimezone(UTC)
                .isoformat(timespec="seconds")
                .replace("+00:00", "Z")
            ),
        }

        # Strategy metadata is optional so legacy version-1
        # previews continue to load unchanged.
        if strategy_name is not None:
            validated["strategyName"] = strategy_name

        if confirmation_time is not None:
            validated["confirmationTime"] = (
                confirmation_time
            )

        for field, value in metadata_numbers.items():
            if value is not None:
                validated[field] = round(
                    value,
                    6,
                )

        # Legacy version-1 previews may not contain lifecycle
        # prices. Preserve compatibility when reading them.
        if target_price is not None:
            validated["targetPrice"] = round(
                target_price,
                4,
            )
            validated["tradingStopPrice"] = round(
                stop_price,
                4,
            )

        if take_profit_1 is not None:
            validated["takeProfit1"] = round(
                take_profit_1,
                4,
            )
            validated["takeProfit2"] = round(
                take_profit_2,
                4,
            )

        return validated

    def save_previews(
        self,
        previews: list[dict[str, Any]],
    ) -> None:
        validated = [
            self._validate_preview(preview)
            for preview in previews
        ]

        payload = {
            "version": 1,
            "previews": sorted(
                validated,
                key=lambda item: item["symbol"],
            ),
        }

        self.path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        encoded = json.dumps(
            payload,
            indent=2,
            sort_keys=True,
        ) + "\n"

        try:
            self.temp_path.write_text(
                encoded,
                encoding="utf-8",
            )
            os.chmod(self.temp_path, 0o600)
            os.replace(
                self.temp_path,
                self.path,
            )
        except OSError as error:
            raise WebullPreviewStoreError(
                "Preview store could not be written."
            ) from error

    def load_preview(
        self,
        symbol: str,
    ) -> dict[str, Any] | None:
        if not self.path.exists():
            return None

        try:
            payload = json.loads(
                self.path.read_text(
                    encoding="utf-8"
                )
            )
        except (
            OSError,
            json.JSONDecodeError,
        ) as error:
            raise WebullPreviewStoreError(
                "Preview store could not be read."
            ) from error

        if not isinstance(payload, dict):
            raise WebullPreviewStoreError(
                "Preview store root must be an object."
            )

        if payload.get("version") != 1:
            raise WebullPreviewStoreError(
                "Unsupported preview store version."
            )

        previews = payload.get("previews")

        if not isinstance(previews, list):
            raise WebullPreviewStoreError(
                "Preview store previews must be a list."
            )

        normalized_symbol = symbol.strip().upper()

        for raw_preview in previews:
            preview = self._validate_preview(
                raw_preview
            )

            if preview["symbol"] == normalized_symbol:
                return preview

        return None
