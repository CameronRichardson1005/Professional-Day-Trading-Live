from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from typing import Iterable

from .momentum_pullback_catalyst import (
    MomentumCatalystArticle,
)


class CatalystCategory(str, Enum):
    EARNINGS_BEAT = "earnings_beat"
    ACQUISITION = "acquisition"
    CONTRACT = "contract"
    REGULATORY = "regulatory"
    CLINICAL = "clinical"
    PARTNERSHIP = "partnership"
    GUIDANCE = "guidance"


@dataclass(frozen=True)
class PositiveCatalyst:
    symbol: str
    category: CatalystCategory
    headline: str
    created_at: str
    source: str
    reason: str


@dataclass(frozen=True)
class CatalystAssessment:
    symbol: str
    positive: bool
    catalysts: tuple[
        PositiveCatalyst,
        ...
    ]


def _normalise(
    value: str,
) -> str:
    return re.sub(
        r"\s+",
        " ",
        str(value).strip().lower(),
    )


# These headlines describe price action or broad
# market activity rather than the underlying cause.
GENERIC_MARKET_PATTERNS = (
    "stocks moving",
    "stock moving",
    "shares halted",
    "circuit breaker",
    "resume trade",
    "resumes trade",
    "why is ",
    "why are ",
    "big stocks moving",
    "dow gains",
    "dow falls",
    "nasdaq gains",
    "nasdaq falls",
    "s&p 500",
)


# Potentially adverse company events should not
# qualify merely because another positive-looking
# keyword also appears in the same text.
NEGATIVE_PATTERNS = (
    "public offering",
    "registered direct offering",
    "at-the-market offering",
    "atm offering",
    "prices offering",
    "announces offering",
    "bankruptcy",
    "chapter 11",
    "receives delisting",
    "delisting notice",
    "going concern",
    "misses estimates",
    "misses estimate",
    "cuts guidance",
    "lowers guidance",
    "withdraws guidance",
)


def _is_generic_market_story(
    text: str,
) -> bool:
    return any(
        pattern in text
        for pattern
        in GENERIC_MARKET_PATTERNS
    )


def _contains_negative_event(
    text: str,
) -> bool:
    return any(
        pattern in text
        for pattern
        in NEGATIVE_PATTERNS
    )


def _category_for_text(
    text: str,
) -> tuple[
    CatalystCategory,
    str,
] | None:

    # Earnings: require both an earnings-type
    # measurement and explicit beat language.
    earnings_terms = (
        "eps",
        "earnings",
        "revenue",
        "sales",
    )

    beat_terms = (
        "beats estimate",
        "beats estimates",
        "beat estimate",
        "beat estimates",
        "tops estimate",
        "tops estimates",
    )

    if (
        any(
            term in text
            for term in earnings_terms
        )
        and any(
            term in text
            for term in beat_terms
        )
    ):
        return (
            CatalystCategory.EARNINGS_BEAT,
            "Company reported results above "
            "stated estimates.",
        )

    acquisition_patterns = (
        "to acquire ",
        "acquisition of ",
        "acquisition by ",
        "merger agreement",
        "definitive merger agreement",
        "going private",
        "to be acquired",
    )

    if any(
        pattern in text
        for pattern
        in acquisition_patterns
    ):
        return (
            CatalystCategory.ACQUISITION,
            "Company-specific acquisition or "
            "merger event identified.",
        )

    contract_patterns = (
        "awarded a contract",
        "awarded contract",
        "wins contract",
        "won contract",
        "receives contract",
        "received contract",
        "secures contract",
        "secured contract",
        "purchase order",
        "awarded task order",
    )

    if any(
        pattern in text
        for pattern
        in contract_patterns
    ):
        return (
            CatalystCategory.CONTRACT,
            "Company-specific contract or order "
            "event identified.",
        )

    regulatory_patterns = (
        "fda approves",
        "fda approved",
        "fda approval",
        "receives fda approval",
        "granted fda approval",
        "receives clearance",
        "fda clearance",
        "510(k) clearance",
    )

    if any(
        pattern in text
        for pattern
        in regulatory_patterns
    ):
        return (
            CatalystCategory.REGULATORY,
            "Positive regulatory approval or "
            "clearance identified.",
        )

    clinical_patterns = (
        "positive phase",
        "positive clinical",
        "meets primary endpoint",
        "met primary endpoint",
        "achieves primary endpoint",
        "achieved primary endpoint",
        "positive trial results",
        "positive topline",
        "positive top-line",
    )

    if any(
        pattern in text
        for pattern
        in clinical_patterns
    ):
        return (
            CatalystCategory.CLINICAL,
            "Positive clinical or trial result "
            "identified.",
        )

    partnership_patterns = (
        "strategic partnership",
        "strategic collaboration",
        "enters partnership",
        "entered partnership",
        "partnership agreement",
        "collaboration agreement",
    )

    if any(
        pattern in text
        for pattern
        in partnership_patterns
    ):
        return (
            CatalystCategory.PARTNERSHIP,
            "Company-specific strategic "
            "partnership identified.",
        )

    guidance_patterns = (
        "raises guidance",
        "raised guidance",
        "increases guidance",
        "increased guidance",
        "raises outlook",
        "raised outlook",
    )

    if any(
        pattern in text
        for pattern
        in guidance_patterns
    ):
        return (
            CatalystCategory.GUIDANCE,
            "Company raised forward guidance "
            "or outlook.",
        )

    return None


def classify_article(
    article: MomentumCatalystArticle,
) -> PositiveCatalyst | None:
    combined = _normalise(
        " ".join(
            (
                article.headline,
                article.summary,
            )
        )
    )

    if not combined:
        return None

    if _is_generic_market_story(
        combined
    ):
        return None

    if _contains_negative_event(
        combined
    ):
        return None

    result = _category_for_text(
        combined
    )

    if result is None:
        return None

    category, reason = result

    return PositiveCatalyst(
        symbol=article.symbol,
        category=category,
        headline=article.headline,
        created_at=article.created_at,
        source=article.source,
        reason=reason,
    )


def assess_symbol_catalysts(
    *,
    symbol: str,
    articles: Iterable[
        MomentumCatalystArticle
    ],
) -> CatalystAssessment:
    clean_symbol = str(
        symbol
    ).strip().upper()

    if not clean_symbol:
        raise ValueError(
            "symbol is required."
        )

    positives = []

    seen = set()

    for article in articles:
        if (
            article.symbol.strip().upper()
            != clean_symbol
        ):
            continue

        catalyst = classify_article(
            article
        )

        if catalyst is None:
            continue

        key = (
            catalyst.category,
            catalyst.headline,
            catalyst.created_at,
        )

        if key in seen:
            continue

        seen.add(key)
        positives.append(
            catalyst
        )

    positives.sort(
        key=lambda item: (
            item.created_at,
            item.headline,
        ),
        reverse=True,
    )

    return CatalystAssessment(
        symbol=clean_symbol,
        positive=bool(
            positives
        ),
        catalysts=tuple(
            positives
        ),
    )
