from datetime import datetime
from zoneinfo import ZoneInfo

from trading_bot.momentum_pullback_catalyst import (
    MomentumCatalystArticle,
)
from trading_bot.momentum_pullback_qualification import (
    MomentumPullbackQualificationService,
    MomentumQualificationStatus,
)
from trading_bot.momentum_pullback_scanner import (
    MomentumPullbackScanner,
    MomentumScannerRules,
)
from trading_bot.webull_momentum_discovery import (
    WebullMomentumCandidate,
)


UTC = ZoneInfo("UTC")


def candidate(
    symbol,
    *,
    price=5.0,
    gain=25.0,
    rvol=7.0,
    volume=1_000_000,
):
    return WebullMomentumCandidate(
        symbol=symbol,
        price=price,
        percent_gain=gain,
        relative_volume_10d=rvol,
        volume=volume,
    )


def article(
    symbol,
    headline,
):
    return MomentumCatalystArticle(
        symbol=symbol,
        created_at=(
            "2026-08-13T12:00:00Z"
        ),
        headline=headline,
        source="benzinga",
        summary="",
        url="https://example.com",
    )


class FakeDiscovery:
    def __init__(
        self,
        candidates,
    ):
        self.candidates = list(
            candidates
        )
        self.calls = 0

    def discover(self):
        self.calls += 1
        return list(
            self.candidates
        )


class FakeCatalystClient:
    def __init__(
        self,
        articles_by_symbol,
    ):
        self.articles_by_symbol = (
            articles_by_symbol
        )
        self.calls = []

    def get_articles_by_symbol(
        self,
        *,
        symbols,
        start,
        end=None,
        limit=50,
    ):
        self.calls.append({
            "symbols": tuple(
                symbols
            ),
            "start": start,
            "end": end,
            "limit": limit,
        })

        return {
            symbol: list(
                self.articles_by_symbol
                .get(
                    symbol,
                    [],
                )
            )
            for symbol in symbols
        }


def start_time():
    return datetime(
        2026,
        8,
        13,
        11,
        0,
        tzinfo=UTC,
    )


def test_empty_discovery_returns_empty():
    discovery = FakeDiscovery([])

    catalyst = (
        FakeCatalystClient({})
    )

    service = (
        MomentumPullbackQualificationService(
            discovery=discovery,
            catalyst_client=catalyst,
        )
    )

    result = service.qualify(
        catalyst_start=start_time()
    )

    assert result.results == ()
    assert (
        result.selected_symbols
        == ()
    )

    assert catalyst.calls == []


def test_positive_catalyst_is_qualified_except_float():
    discovery = FakeDiscovery([
        candidate("AAA")
    ])

    catalyst = (
        FakeCatalystClient({
            "AAA": [
                article(
                    "AAA",
                    (
                        "AAA Awarded "
                        "Contract With "
                        "U.S. Agency"
                    ),
                )
            ]
        })
    )

    service = (
        MomentumPullbackQualificationService(
            discovery=discovery,
            catalyst_client=catalyst,
        )
    )

    run = service.qualify(
        catalyst_start=start_time()
    )

    result = run.results[0]

    assert (
        result.status
        == MomentumQualificationStatus
        .QUALIFIED_EXCEPT_FLOAT
    )

    assert (
        result.provisionally_qualified
        is True
    )

    assert result.failures == (
        "FLOAT UNCONFIRMED",
    )

    assert (
        run.selected_symbols
        == ("AAA",)
    )


def test_generic_news_does_not_qualify():
    discovery = FakeDiscovery([
        candidate("AAA")
    ])

    catalyst = (
        FakeCatalystClient({
            "AAA": [
                article(
                    "AAA",
                    (
                        "AAA Shares Halted "
                        "On Circuit Breaker "
                        "To The Upside"
                    ),
                )
            ]
        })
    )

    service = (
        MomentumPullbackQualificationService(
            discovery=discovery,
            catalyst_client=catalyst,
        )
    )

    run = service.qualify(
        catalyst_start=start_time()
    )

    result = run.results[0]

    assert (
        result.status
        == MomentumQualificationStatus
        .CATALYST_UNCONFIRMED
    )

    assert (
        result.provisionally_qualified
        is False
    )

    assert (
        run.selected_symbols
        == ()
    )


def test_no_news_does_not_qualify():
    service = (
        MomentumPullbackQualificationService(
            discovery=FakeDiscovery([
                candidate("AAA")
            ]),
            catalyst_client=(
                FakeCatalystClient({})
            ),
        )
    )

    result = service.qualify(
        catalyst_start=start_time()
    )

    assert (
        result.results[0].status
        == MomentumQualificationStatus
        .CATALYST_UNCONFIRMED
    )


def test_snapshot_preserves_webull_market_data():
    original = candidate(
        "AAA",
        price=4.25,
        gain=42.5,
        rvol=8.5,
        volume=2_500_000,
    )

    service = (
        MomentumPullbackQualificationService(
            discovery=(
                FakeDiscovery([
                    original
                ])
            ),
            catalyst_client=(
                FakeCatalystClient({
                    "AAA": [
                        article(
                            "AAA",
                            (
                                "AAA Wins "
                                "Contract"
                            ),
                        )
                    ]
                })
            ),
        )
    )

    result = service.qualify(
        catalyst_start=start_time()
    )

    snapshot = (
        result.results[0]
        .snapshot
    )

    assert snapshot.symbol == "AAA"
    assert snapshot.price == 4.25

    assert (
        snapshot.percent_gain
        == 42.5
    )

    assert (
        snapshot.relative_volume
        == 8.5
    )

    assert (
        snapshot.current_volume
        == 2_500_000
    )

    assert (
        snapshot.float_shares
        is None
    )


def test_positive_headline_is_saved_as_catalyst():
    service = (
        MomentumPullbackQualificationService(
            discovery=FakeDiscovery([
                candidate("AAA")
            ]),
            catalyst_client=(
                FakeCatalystClient({
                    "AAA": [
                        article(
                            "AAA",
                            (
                                "AAA Raises "
                                "Guidance"
                            ),
                        )
                    ]
                })
            ),
        )
    )

    result = service.qualify(
        catalyst_start=start_time()
    )

    assert (
        result.results[0]
        .snapshot
        .catalyst
        == "AAA Raises Guidance"
    )


def test_market_rules_are_rechecked():
    discovery = FakeDiscovery([
        candidate(
            "AAA",
            price=25.0,
        )
    ])

    catalyst = (
        FakeCatalystClient({
            "AAA": [
                article(
                    "AAA",
                    "AAA Wins Contract",
                )
            ]
        })
    )

    service = (
        MomentumPullbackQualificationService(
            discovery=discovery,
            catalyst_client=catalyst,
        )
    )

    run = service.qualify(
        catalyst_start=start_time()
    )

    result = run.results[0]

    assert (
        result.status
        == MomentumQualificationStatus
        .REJECTED_MARKET_DATA
    )

    assert (
        "PRICE ABOVE MAXIMUM"
        in result.failures
    )

    assert (
        run.selected_symbols
        == ()
    )


def test_candidates_rank_by_gain_then_rvol():
    candidates = [
        candidate(
            "BBB",
            gain=30,
            rvol=8,
        ),
        candidate(
            "AAA",
            gain=40,
            rvol=6,
        ),
        candidate(
            "CCC",
            gain=30,
            rvol=9,
        ),
    ]

    catalyst_data = {
        symbol: [
            article(
                symbol,
                (
                    f"{symbol} "
                    "Wins Contract"
                ),
            )
        ]
        for symbol in (
            "AAA",
            "BBB",
            "CCC",
        )
    }

    service = (
        MomentumPullbackQualificationService(
            discovery=(
                FakeDiscovery(
                    candidates
                )
            ),
            catalyst_client=(
                FakeCatalystClient(
                    catalyst_data
                )
            ),
        )
    )

    run = service.qualify(
        catalyst_start=start_time()
    )

    assert [
        item.symbol
        for item in run.results
    ] == [
        "AAA",
        "CCC",
        "BBB",
    ]


def test_candidate_limit_is_respected():
    candidates = [
        candidate(
            "AAA",
            gain=50,
        ),
        candidate(
            "BBB",
            gain=40,
        ),
        candidate(
            "CCC",
            gain=30,
        ),
    ]

    catalyst_data = {
        symbol: [
            article(
                symbol,
                (
                    f"{symbol} "
                    "Awarded Contract"
                ),
            )
        ]
        for symbol in (
            "AAA",
            "BBB",
            "CCC",
        )
    }

    scanner = (
        MomentumPullbackScanner(
            MomentumScannerRules(
                candidate_limit=2,
            )
        )
    )

    service = (
        MomentumPullbackQualificationService(
            discovery=(
                FakeDiscovery(
                    candidates
                )
            ),
            catalyst_client=(
                FakeCatalystClient(
                    catalyst_data
                )
            ),
            scanner=scanner,
        )
    )

    run = service.qualify(
        catalyst_start=start_time()
    )

    assert (
        run.selected_symbols
        == (
            "AAA",
            "BBB",
        )
    )


def test_unconfirmed_catalyst_is_not_selected_over_lower_ranked_positive():
    candidates = [
        candidate(
            "AAA",
            gain=100,
        ),
        candidate(
            "BBB",
            gain=50,
        ),
    ]

    catalyst = (
        FakeCatalystClient({
            "AAA": [
                article(
                    "AAA",
                    (
                        "AAA Shares Halted "
                        "On Circuit Breaker"
                    ),
                )
            ],
            "BBB": [
                article(
                    "BBB",
                    (
                        "BBB Awarded "
                        "Contract"
                    ),
                )
            ],
        })
    )

    service = (
        MomentumPullbackQualificationService(
            discovery=(
                FakeDiscovery(
                    candidates
                )
            ),
            catalyst_client=catalyst,
        )
    )

    run = service.qualify(
        catalyst_start=start_time()
    )

    assert (
        run.selected_symbols
        == ("BBB",)
    )


def test_news_request_receives_all_discovered_symbols():
    discovery = FakeDiscovery([
        candidate("AAA"),
        candidate("BBB"),
    ])

    catalyst = (
        FakeCatalystClient({})
    )

    service = (
        MomentumPullbackQualificationService(
            discovery=discovery,
            catalyst_client=catalyst,
        )
    )

    start = start_time()

    service.qualify(
        catalyst_start=start,
        news_limit=75,
    )

    call = catalyst.calls[0]

    assert call["symbols"] == (
        "AAA",
        "BBB",
    )

    assert call["start"] == start
    assert call["limit"] == 75


def test_discovered_count_includes_rejected_names():
    service = (
        MomentumPullbackQualificationService(
            discovery=FakeDiscovery([
                candidate("AAA"),
                candidate("BBB"),
            ]),
            catalyst_client=(
                FakeCatalystClient({})
            ),
        )
    )

    run = service.qualify(
        catalyst_start=start_time()
    )

    assert (
        run.discovered_count
        == 2
    )
