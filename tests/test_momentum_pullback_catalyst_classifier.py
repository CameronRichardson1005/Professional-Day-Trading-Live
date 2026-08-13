import pytest

from trading_bot.momentum_pullback_catalyst import (
    MomentumCatalystArticle,
)

from trading_bot.momentum_pullback_catalyst_classifier import (
    CatalystCategory,
    assess_symbol_catalysts,
    classify_article,
)


def article(
    headline,
    *,
    symbol="TEST",
    summary="",
    created_at=(
        "2026-08-13T12:00:00Z"
    ),
):
    return MomentumCatalystArticle(
        symbol=symbol,
        created_at=created_at,
        headline=headline,
        source="benzinga",
        summary=summary,
        url="https://example.com",
    )


def test_earnings_beat_is_positive():
    result = classify_article(
        article(
            "TEST Q2 EPS $0.32 Beats "
            "$0.16 Estimate, Sales "
            "$356M Beat Estimates"
        )
    )

    assert result is not None

    assert (
        result.category
        == CatalystCategory.EARNINGS_BEAT
    )


def test_acquisition_is_positive():
    result = classify_article(
        article(
            "TEST To Be Acquired In "
            "$4 Billion Deal"
        )
    )

    assert result is not None

    assert (
        result.category
        == CatalystCategory.ACQUISITION
    )


def test_contract_is_positive():
    result = classify_article(
        article(
            "TEST Awarded Contract "
            "With U.S. Agency"
        )
    )

    assert result is not None

    assert (
        result.category
        == CatalystCategory.CONTRACT
    )


def test_fda_approval_is_positive():
    result = classify_article(
        article(
            "FDA Approves TEST "
            "Treatment"
        )
    )

    assert result is not None

    assert (
        result.category
        == CatalystCategory.REGULATORY
    )


def test_positive_clinical_result():
    result = classify_article(
        article(
            "TEST Meets Primary Endpoint "
            "In Phase 3 Trial"
        )
    )

    assert result is not None

    assert (
        result.category
        == CatalystCategory.CLINICAL
    )


def test_partnership_is_positive():
    result = classify_article(
        article(
            "TEST Announces Strategic "
            "Partnership With Major "
            "Technology Company"
        )
    )

    assert result is not None

    assert (
        result.category
        == CatalystCategory.PARTNERSHIP
    )


def test_raised_guidance_is_positive():
    result = classify_article(
        article(
            "TEST Raises Guidance "
            "Following Strong Quarter"
        )
    )

    assert result is not None

    assert (
        result.category
        == CatalystCategory.GUIDANCE
    )


@pytest.mark.parametrize(
    "headline",
    [
        (
            "12 Industrials Stocks "
            "Moving In Thursday's "
            "Intraday Session"
        ),
        (
            "TEST Shares Halted On "
            "Circuit Breaker To The "
            "Upside"
        ),
        (
            "TEST Shares Resume Trade"
        ),
        (
            "Why Is TEST Stock "
            "Gaining Thursday?"
        ),
        (
            "Dow Gains Over 100 Points; "
            "Producer Prices Unchanged"
        ),
        (
            "TEST And Other Big Stocks "
            "Moving Higher Thursday"
        ),
    ],
)
def test_generic_market_stories_do_not_qualify(
    headline,
):
    assert (
        classify_article(
            article(headline)
        )
        is None
    )


@pytest.mark.parametrize(
    "headline",
    [
        (
            "TEST Announces "
            "Public Offering"
        ),
        (
            "TEST Prices Registered "
            "Direct Offering"
        ),
        (
            "TEST Files Chapter 11 "
            "Bankruptcy"
        ),
        (
            "TEST Misses Estimates "
            "And Cuts Guidance"
        ),
        (
            "TEST Receives Delisting "
            "Notice"
        ),
    ],
)
def test_negative_events_do_not_qualify(
    headline,
):
    assert (
        classify_article(
            article(headline)
        )
        is None
    )


def test_summary_can_supply_catalyst():
    result = classify_article(
        article(
            "TEST Announces "
            "Corporate Update",
            summary=(
                "The company was "
                "awarded a contract "
                "with a federal agency."
            ),
        )
    )

    assert result is not None

    assert (
        result.category
        == CatalystCategory.CONTRACT
    )


def test_unknown_company_news_is_not_positive():
    assert (
        classify_article(
            article(
                "TEST Announces "
                "Corporate Update"
            )
        )
        is None
    )


def test_assessment_requires_real_positive():
    articles = [
        article(
            "TEST Shares Halted On "
            "Circuit Breaker"
        ),
        article(
            "12 Technology Stocks "
            "Moving Thursday"
        ),
    ]

    result = assess_symbol_catalysts(
        symbol="TEST",
        articles=articles,
    )

    assert result.positive is False
    assert result.catalysts == ()


def test_assessment_marks_symbol_positive():
    articles = [
        article(
            "TEST Shares Halted On "
            "Circuit Breaker"
        ),
        article(
            "TEST Awarded Contract "
            "Worth $50 Million",
            created_at=(
                "2026-08-13T13:00:00Z"
            ),
        ),
    ]

    result = assess_symbol_catalysts(
        symbol="test",
        articles=articles,
    )

    assert result.symbol == "TEST"
    assert result.positive is True
    assert len(
        result.catalysts
    ) == 1

    assert (
        result.catalysts[0].category
        == CatalystCategory.CONTRACT
    )


def test_other_symbol_articles_ignored():
    result = assess_symbol_catalysts(
        symbol="AAA",
        articles=[
            article(
                "BBB Awarded Contract",
                symbol="BBB",
            )
        ],
    )

    assert result.positive is False


def test_duplicate_catalysts_removed():
    duplicate = article(
        "TEST Awarded Contract"
    )

    result = assess_symbol_catalysts(
        symbol="TEST",
        articles=[
            duplicate,
            duplicate,
        ],
    )

    assert len(
        result.catalysts
    ) == 1


def test_blank_symbol_rejected():
    with pytest.raises(
        ValueError
    ):
        assess_symbol_catalysts(
            symbol=" ",
            articles=[],
        )
