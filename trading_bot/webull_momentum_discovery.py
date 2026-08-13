from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WebullMomentumCandidate:
    symbol: str
    price: float
    percent_gain: float
    relative_volume_10d: float
    volume: float
    previous_close: float | None = None
    market_value: float | None = None


def _to_float(
    value,
) -> float | None:
    if value in (
        None,
        "",
    ):
        return None

    try:
        return float(
            value
        )
    except (
        TypeError,
        ValueError,
    ):
        return None


def _response_payload(
    response,
) -> dict:
    status = getattr(
        response,
        "status_code",
        None,
    )

    if status != 200:
        raise RuntimeError(
            "Webull screener request "
            f"failed with HTTP {status}."
        )

    payload = response.json()

    if not isinstance(
        payload,
        dict,
    ):
        raise RuntimeError(
            "Malformed Webull screener response."
        )

    return payload


def _records(
    payload: dict,
) -> list[dict]:
    data = payload.get(
        "data",
        [],
    )

    if not isinstance(
        data,
        list,
    ):
        raise RuntimeError(
            "Malformed Webull screener data."
        )

    return [
        record
        for record in data
        if isinstance(
            record,
            dict,
        )
    ]


class WebullMomentumDiscovery:
    """
    Read-only whole-market Momentum Pullback discovery.

    Webull provides:
      - daily percentage gainers
      - 10-day relative-volume leaders

    We intersect those datasets and apply the
    mechanical Momentum Pullback discovery rules.

    change_ratio from Webull is a decimal ratio:
        0.10 == +10%

    relative_volume_10d is already a multiple:
        5.0 == 5x RVOL

    Float and catalyst confirmation are deliberately
    NOT inferred here.
    """

    def __init__(
        self,
        *,
        screener,
        minimum_price: float = 1.0,
        maximum_price: float | None = 20.0,
        minimum_percent_gain: float = 10.0,
        minimum_relative_volume: float = 5.0,
        page_size: int = 50,
        maximum_pages: int = 4,
    ) -> None:
        if minimum_price < 0:
            raise ValueError(
                "minimum_price cannot be negative."
            )

        if (
            maximum_price is not None
            and maximum_price < minimum_price
        ):
            raise ValueError(
                "maximum_price cannot be "
                "below minimum_price."
            )

        if minimum_percent_gain < 0:
            raise ValueError(
                "minimum_percent_gain "
                "cannot be negative."
            )

        if minimum_relative_volume < 0:
            raise ValueError(
                "minimum_relative_volume "
                "cannot be negative."
            )

        if page_size < 1:
            raise ValueError(
                "page_size must be positive."
            )

        if maximum_pages < 1:
            raise ValueError(
                "maximum_pages must be positive."
            )

        self.screener = screener

        self.minimum_price = (
            minimum_price
        )

        self.maximum_price = (
            maximum_price
        )

        self.minimum_percent_gain = (
            minimum_percent_gain
        )

        self.minimum_relative_volume = (
            minimum_relative_volume
        )

        self.page_size = page_size
        self.maximum_pages = (
            maximum_pages
        )

    def discover(
        self,
    ) -> list[
        WebullMomentumCandidate
    ]:
        gainers = (
            self._fetch_gainers()
        )

        relative_volume = (
            self._fetch_relative_volume()
        )

        rvol_by_symbol = {
            str(
                record.get(
                    "symbol",
                    "",
                )
            ).strip().upper(): record
            for record in relative_volume
            if str(
                record.get(
                    "symbol",
                    "",
                )
            ).strip()
        }

        candidates = []

        for gainer in gainers:
            symbol = str(
                gainer.get(
                    "symbol",
                    "",
                )
            ).strip().upper()

            if not symbol:
                continue

            rvol_record = (
                rvol_by_symbol.get(
                    symbol
                )
            )

            if rvol_record is None:
                continue

            candidate = (
                self._candidate_from_records(
                    gainer=gainer,
                    rvol_record=(
                        rvol_record
                    ),
                )
            )

            if candidate is not None:
                candidates.append(
                    candidate
                )

        candidates.sort(
            key=lambda item: (
                -item.percent_gain,
                -item.relative_volume_10d,
                item.symbol,
            )
        )

        return candidates

    def _fetch_gainers(
        self,
    ) -> list[dict]:
        results = []

        minimum_ratio = (
            self.minimum_percent_gain
            / 100.0
        )

        for page in range(
            1,
            self.maximum_pages + 1,
        ):
            response = (
                self.screener
                .get_gainers_losers(
                    rank_type="DAY_1",
                    category="US_STOCK",
                    sort_by="CHANGE_RATIO",
                    page_index=page,
                    page_size=(
                        self.page_size
                    ),
                    direction="DESC",
                )
            )

            payload = (
                _response_payload(
                    response
                )
            )

            page_records = (
                _records(
                    payload
                )
            )

            if not page_records:
                break

            below_threshold = False

            for record in page_records:
                ratio = _to_float(
                    record.get(
                        "change_ratio"
                    )
                )

                if ratio is None:
                    continue

                if ratio < minimum_ratio:
                    below_threshold = True
                    continue

                results.append(
                    record
                )

            if below_threshold:
                break

            if not payload.get(
                "has_more",
                False,
            ):
                break

        return results

    def _fetch_relative_volume(
        self,
    ) -> list[dict]:
        results = []

        for page in range(
            1,
            self.maximum_pages + 1,
        ):
            response = (
                self.screener
                .get_most_active(
                    category="US_STOCK",
                    rank_type=(
                        "RELATIVE_VOLUME_10D"
                    ),
                    sort_by=(
                        "RELATIVE_VOLUME_10D"
                    ),
                    page_index=page,
                    page_size=(
                        self.page_size
                    ),
                    direction="DESC",
                )
            )

            payload = (
                _response_payload(
                    response
                )
            )

            page_records = (
                _records(
                    payload
                )
            )

            if not page_records:
                break

            below_threshold = False

            for record in page_records:
                rvol = _to_float(
                    record.get(
                        "relative_volume_10d"
                    )
                )

                if rvol is None:
                    continue

                if (
                    rvol
                    < self.minimum_relative_volume
                ):
                    below_threshold = True
                    continue

                results.append(
                    record
                )

            if below_threshold:
                break

            if not payload.get(
                "has_more",
                False,
            ):
                break

        return results

    def _candidate_from_records(
        self,
        *,
        gainer: dict,
        rvol_record: dict,
    ) -> WebullMomentumCandidate | None:
        symbol = str(
            gainer.get(
                "symbol",
                "",
            )
        ).strip().upper()

        price = _to_float(
            rvol_record.get(
                "price",
                gainer.get(
                    "price"
                ),
            )
        )

        ratio = _to_float(
            rvol_record.get(
                "change_ratio",
                gainer.get(
                    "change_ratio"
                ),
            )
        )

        rvol = _to_float(
            rvol_record.get(
                "relative_volume_10d"
            )
        )

        volume = _to_float(
            rvol_record.get(
                "volume",
                gainer.get(
                    "volume"
                ),
            )
        )

        if (
            not symbol
            or price is None
            or ratio is None
            or rvol is None
            or volume is None
        ):
            return None

        percent_gain = (
            ratio * 100.0
        )

        if price < self.minimum_price:
            return None

        if (
            self.maximum_price
            is not None
            and price
            > self.maximum_price
        ):
            return None

        if (
            percent_gain
            < self.minimum_percent_gain
        ):
            return None

        if (
            rvol
            < self.minimum_relative_volume
        ):
            return None

        return (
            WebullMomentumCandidate(
                symbol=symbol,
                price=price,
                percent_gain=(
                    percent_gain
                ),
                relative_volume_10d=(
                    rvol
                ),
                volume=volume,
                previous_close=(
                    _to_float(
                        rvol_record.get(
                            "pre_close",
                            gainer.get(
                                "pre_close"
                            ),
                        )
                    )
                ),
                market_value=(
                    _to_float(
                        rvol_record.get(
                            "market_value",
                            gainer.get(
                                "market_value"
                            ),
                        )
                    )
                ),
            )
        )
