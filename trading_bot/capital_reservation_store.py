from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


EASTERN = ZoneInfo("America/New_York")


class CapitalReservationStoreError(RuntimeError):
    pass


class DailyCapitalReservationStore:
    """
    Persistent preview-capital reservations for one trading day.

    This is not a broker-order ledger. It stores only recommended
    preview exposure so separate strategies cannot independently
    recommend the same daily capital.

    A new New York trading date starts with zero reservations.
    """

    def __init__(
        self,
        path: Path | str = (
            "state/webull_daily_capital_reservations.json"
        ),
    ) -> None:
        self.path = Path(path)
        self.temp_path = self.path.with_suffix(
            self.path.suffix + ".tmp"
        )

    @staticmethod
    def current_trading_date() -> str:
        return datetime.now(EASTERN).date().isoformat()

    @staticmethod
    def _validate_date(date_str: str) -> str:
        normalized = str(date_str).strip()

        try:
            datetime.strptime(
                normalized,
                "%Y-%m-%d",
            )
        except ValueError as error:
            raise CapitalReservationStoreError(
                "Capital reservation date must be YYYY-MM-DD."
            ) from error

        return normalized

    def _read(
        self,
    ) -> dict:
        if not self.path.exists():
            return {
                "version": 1,
                "date": None,
                "reservations": [],
            }

        try:
            payload = json.loads(
                self.path.read_text(
                    encoding="utf-8",
                )
            )
        except (
            OSError,
            json.JSONDecodeError,
        ) as error:
            raise CapitalReservationStoreError(
                "Capital reservation store could not be read."
            ) from error

        if not isinstance(payload, dict):
            raise CapitalReservationStoreError(
                "Capital reservation store root must be an object."
            )

        if payload.get("version") != 1:
            raise CapitalReservationStoreError(
                "Unsupported capital reservation store version."
            )

        reservations = payload.get(
            "reservations"
        )

        if not isinstance(reservations, list):
            raise CapitalReservationStoreError(
                "Capital reservations must be a list."
            )

        for record in reservations:
            if not isinstance(record, dict):
                raise CapitalReservationStoreError(
                    "Capital reservation records must be objects."
                )

            required = {
                "reservationId",
                "strategy",
                "symbol",
                "exposure",
            }

            if set(record) != required:
                raise CapitalReservationStoreError(
                    "Capital reservation record has "
                    "unexpected fields."
                )

            if not str(
                record["reservationId"]
            ).strip():
                raise CapitalReservationStoreError(
                    "Capital reservation ID is required."
                )

            if not str(
                record["strategy"]
            ).strip():
                raise CapitalReservationStoreError(
                    "Capital reservation strategy is required."
                )

            if not str(
                record["symbol"]
            ).strip():
                raise CapitalReservationStoreError(
                    "Capital reservation symbol is required."
                )

            try:
                exposure = float(
                    record["exposure"]
                )
            except (
                TypeError,
                ValueError,
            ) as error:
                raise CapitalReservationStoreError(
                    "Capital reservation exposure "
                    "must be numeric."
                ) from error

            if exposure <= 0:
                raise CapitalReservationStoreError(
                    "Capital reservation exposure "
                    "must be positive."
                )

        stored_date = payload.get("date")

        if stored_date is not None:
            self._validate_date(stored_date)

        return payload

    def total_reserved_exposure(
        self,
        date_str: str,
    ) -> float:
        date_str = self._validate_date(
            date_str
        )

        payload = self._read()

        if payload.get("date") != date_str:
            return 0.0

        return round(
            sum(
                float(record["exposure"])
                for record
                in payload["reservations"]
            ),
            2,
        )

    def reserve(
        self,
        *,
        date_str: str,
        reservation_id: str,
        strategy: str,
        symbol: str,
        exposure: float,
    ) -> None:
        date_str = self._validate_date(
            date_str
        )

        reservation_id = str(
            reservation_id
        ).strip()

        strategy = str(strategy).strip().upper()
        symbol = str(symbol).strip().upper()

        try:
            exposure = float(exposure)
        except (
            TypeError,
            ValueError,
        ) as error:
            raise CapitalReservationStoreError(
                "Capital reservation exposure "
                "must be numeric."
            ) from error

        if not reservation_id:
            raise CapitalReservationStoreError(
                "Capital reservation ID is required."
            )

        if not strategy:
            raise CapitalReservationStoreError(
                "Capital reservation strategy is required."
            )

        if not symbol:
            raise CapitalReservationStoreError(
                "Capital reservation symbol is required."
            )

        if exposure <= 0:
            raise CapitalReservationStoreError(
                "Capital reservation exposure "
                "must be positive."
            )

        payload = self._read()

        if payload.get("date") == date_str:
            reservations = list(
                payload["reservations"]
            )
        else:
            # A new New York trading date starts a fresh pool.
            reservations = []

        record = {
            "reservationId": reservation_id,
            "strategy": strategy,
            "symbol": symbol,
            "exposure": round(
                exposure,
                2,
            ),
        }

        # Idempotent upsert. Re-running the same signal updates its
        # reservation instead of consuming the capital twice.
        reservations = [
            existing
            for existing in reservations
            if existing["reservationId"]
            != reservation_id
        ]

        reservations.append(record)

        reservations.sort(
            key=lambda item: (
                item["strategy"],
                item["symbol"],
                item["reservationId"],
            )
        )

        new_payload = {
            "version": 1,
            "date": date_str,
            "reservations": reservations,
        }

        self.path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        encoded = json.dumps(
            new_payload,
            indent=2,
            sort_keys=True,
        ) + "\n"

        try:
            self.temp_path.write_text(
                encoded,
                encoding="utf-8",
            )
            os.chmod(
                self.temp_path,
                0o600,
            )
            os.replace(
                self.temp_path,
                self.path,
            )
        except OSError as error:
            raise CapitalReservationStoreError(
                "Capital reservation store "
                "could not be written."
            ) from error
