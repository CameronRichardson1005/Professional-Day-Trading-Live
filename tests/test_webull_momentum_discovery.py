import pytest

from trading_bot.webull_momentum_discovery import (
    WebullMomentumDiscovery,
)


class FakeResponse:
    def __init__(
        self,
        payload,
        status_code=200,
    ):
        self._payload = payload
        self.status_code = (
            status_code
        )

    def json(self):
        return self._payload


class FakeScreener:
    def __init__(
        self,
        *,
        gainers,
        active,
    ):
        self.gainers = gainers
        self.active = active
        self.gainer_calls = []
        self.active_calls = []

    def get_gainers_losers(
        self,
        **kwargs,
    ):
        self.gainer_calls.append(
            kwargs
        )

        page = kwargs[
            "page_index"
        ]

        payload = (
            self.gainers[
                page - 1
            ]
            if page
            <= len(self.gainers)
            else {
                "data": [],
                "has_more": False,
            }
        )

        return FakeResponse(
            payload
        )

    def get_most_active(
        self,
        **kwargs,
    ):
        self.active_calls.append(
            kwargs
        )

        page = kwargs[
            "page_index"
        ]

        payload = (
            self.active[
                page - 1
            ]
            if page
            <= len(self.active)
            else {
                "data": [],
                "has_more": False,
            }
        )

        return FakeResponse(
            payload
        )


def record(
    symbol,
    *,
    price,
    ratio,
    rvol=None,
    volume=1_000_000,
):
    result = {
        "symbol": symbol,
        "price": str(price),
        "pre_close": "1",
        "change_ratio": (
            str(ratio)
        ),
        "volume": str(volume),
        "market_value": "10000000",
    }

    if rvol is not None:
        result[
            "relative_volume_10d"
        ] = str(rvol)

    return result


def test_discovers_intersection():
    screener = FakeScreener(
        gainers=[
            {
                "data": [
                    record(
                        "AAA",
                        price=5,
                        ratio=.50,
                    ),
                    record(
                        "BBB",
                        price=10,
                        ratio=.20,
                    ),
                ],
                "has_more": False,
            }
        ],
        active=[
            {
                "data": [
                    record(
                        "AAA",
                        price=5,
                        ratio=.50,
                        rvol=7,
                    ),
                    record(
                        "BBB",
                        price=10,
                        ratio=.20,
                        rvol=6,
                    ),
                ],
                "has_more": False,
            }
        ],
    )

    discovery = (
        WebullMomentumDiscovery(
            screener=screener
        )
    )

    result = (
        discovery.discover()
    )

    assert [
        item.symbol
        for item in result
    ] == [
        "AAA",
        "BBB",
    ]

    assert (
        result[0].percent_gain
        == pytest.approx(50)
    )

    assert (
        result[0]
        .relative_volume_10d
        == pytest.approx(7)
    )


def test_requires_both_gainer_and_rvol_membership():
    screener = FakeScreener(
        gainers=[
            {
                "data": [
                    record(
                        "GAIN_ONLY",
                        price=5,
                        ratio=.50,
                    ),
                    record(
                        "BOTH",
                        price=5,
                        ratio=.30,
                    ),
                ],
                "has_more": False,
            }
        ],
        active=[
            {
                "data": [
                    record(
                        "RVOL_ONLY",
                        price=5,
                        ratio=.20,
                        rvol=7,
                    ),
                    record(
                        "BOTH",
                        price=5,
                        ratio=.30,
                        rvol=6,
                    ),
                ],
                "has_more": False,
            }
        ],
    )

    result = (
        WebullMomentumDiscovery(
            screener=screener
        ).discover()
    )

    assert [
        item.symbol
        for item in result
    ] == ["BOTH"]


def test_price_filter():
    screener = FakeScreener(
        gainers=[
            {
                "data": [
                    record(
                        "LOW",
                        price=.50,
                        ratio=.50,
                    ),
                    record(
                        "GOOD",
                        price=5,
                        ratio=.40,
                    ),
                    record(
                        "HIGH",
                        price=25,
                        ratio=.30,
                    ),
                ],
                "has_more": False,
            }
        ],
        active=[
            {
                "data": [
                    record(
                        "LOW",
                        price=.50,
                        ratio=.50,
                        rvol=7,
                    ),
                    record(
                        "GOOD",
                        price=5,
                        ratio=.40,
                        rvol=7,
                    ),
                    record(
                        "HIGH",
                        price=25,
                        ratio=.30,
                        rvol=7,
                    ),
                ],
                "has_more": False,
            }
        ],
    )

    result = (
        WebullMomentumDiscovery(
            screener=screener
        ).discover()
    )

    assert [
        item.symbol
        for item in result
    ] == ["GOOD"]


def test_gain_threshold_is_decimal_to_percent():
    screener = FakeScreener(
        gainers=[
            {
                "data": [
                    record(
                        "PASS",
                        price=5,
                        ratio=.10,
                    ),
                    record(
                        "FAIL",
                        price=5,
                        ratio=.099,
                    ),
                ],
                "has_more": False,
            }
        ],
        active=[
            {
                "data": [
                    record(
                        "PASS",
                        price=5,
                        ratio=.10,
                        rvol=5,
                    ),
                    record(
                        "FAIL",
                        price=5,
                        ratio=.099,
                        rvol=7,
                    ),
                ],
                "has_more": False,
            }
        ],
    )

    result = (
        WebullMomentumDiscovery(
            screener=screener
        ).discover()
    )

    assert [
        item.symbol
        for item in result
    ] == ["PASS"]

    assert (
        result[0].percent_gain
        == pytest.approx(10)
    )


def test_rvol_threshold():
    screener = FakeScreener(
        gainers=[
            {
                "data": [
                    record(
                        "PASS",
                        price=5,
                        ratio=.20,
                    ),
                    record(
                        "FAIL",
                        price=5,
                        ratio=.30,
                    ),
                ],
                "has_more": False,
            }
        ],
        active=[
            {
                "data": [
                    record(
                        "PASS",
                        price=5,
                        ratio=.20,
                        rvol=5,
                    ),
                    record(
                        "FAIL",
                        price=5,
                        ratio=.30,
                        rvol=4.99,
                    ),
                ],
                "has_more": False,
            }
        ],
    )

    result = (
        WebullMomentumDiscovery(
            screener=screener
        ).discover()
    )

    assert [
        item.symbol
        for item in result
    ] == ["PASS"]


def test_sorted_by_gain_then_rvol():
    screener = FakeScreener(
        gainers=[
            {
                "data": [
                    record(
                        "AAA",
                        price=5,
                        ratio=.20,
                    ),
                    record(
                        "BBB",
                        price=5,
                        ratio=.30,
                    ),
                    record(
                        "CCC",
                        price=5,
                        ratio=.30,
                    ),
                ],
                "has_more": False,
            }
        ],
        active=[
            {
                "data": [
                    record(
                        "AAA",
                        price=5,
                        ratio=.20,
                        rvol=8,
                    ),
                    record(
                        "BBB",
                        price=5,
                        ratio=.30,
                        rvol=6,
                    ),
                    record(
                        "CCC",
                        price=5,
                        ratio=.30,
                        rvol=7,
                    ),
                ],
                "has_more": False,
            }
        ],
    )

    result = (
        WebullMomentumDiscovery(
            screener=screener
        ).discover()
    )

    assert [
        item.symbol
        for item in result
    ] == [
        "CCC",
        "BBB",
        "AAA",
    ]


def test_stops_gainers_after_threshold_crossed():
    screener = FakeScreener(
        gainers=[
            {
                "data": [
                    record(
                        "PASS",
                        price=5,
                        ratio=.20,
                    ),
                    record(
                        "LOW",
                        price=5,
                        ratio=.05,
                    ),
                ],
                "has_more": True,
            },
            {
                "data": [
                    record(
                        "SHOULD_NOT_FETCH",
                        price=5,
                        ratio=.30,
                    )
                ],
                "has_more": False,
            },
        ],
        active=[
            {
                "data": [
                    record(
                        "PASS",
                        price=5,
                        ratio=.20,
                        rvol=6,
                    )
                ],
                "has_more": False,
            }
        ],
    )

    WebullMomentumDiscovery(
        screener=screener
    ).discover()

    assert len(
        screener.gainer_calls
    ) == 1


def test_stops_rvol_after_threshold_crossed():
    screener = FakeScreener(
        gainers=[
            {
                "data": [
                    record(
                        "PASS",
                        price=5,
                        ratio=.20,
                    )
                ],
                "has_more": False,
            }
        ],
        active=[
            {
                "data": [
                    record(
                        "PASS",
                        price=5,
                        ratio=.20,
                        rvol=6,
                    ),
                    record(
                        "LOW",
                        price=5,
                        ratio=.20,
                        rvol=4,
                    ),
                ],
                "has_more": True,
            },
            {
                "data": [
                    record(
                        "SHOULD_NOT_FETCH",
                        price=5,
                        ratio=.20,
                        rvol=8,
                    )
                ],
                "has_more": False,
            },
        ],
    )

    WebullMomentumDiscovery(
        screener=screener
    ).discover()

    assert len(
        screener.active_calls
    ) == 1


def test_maximum_price_can_be_disabled():
    screener = FakeScreener(
        gainers=[
            {
                "data": [
                    record(
                        "HIGH",
                        price=30,
                        ratio=.20,
                    )
                ],
                "has_more": False,
            }
        ],
        active=[
            {
                "data": [
                    record(
                        "HIGH",
                        price=30,
                        ratio=.20,
                        rvol=6,
                    )
                ],
                "has_more": False,
            }
        ],
    )

    result = (
        WebullMomentumDiscovery(
            screener=screener,
            maximum_price=None,
        ).discover()
    )

    assert [
        item.symbol
        for item in result
    ] == ["HIGH"]
