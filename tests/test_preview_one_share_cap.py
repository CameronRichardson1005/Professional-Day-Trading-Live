from trading_bot.config import (
    WEBULL_ORDER_SUBMISSION_ENABLED,
    WEBULL_PREVIEW_MAX_SHARES,
)


def test_preview_share_cap_allows_capital_allocator_sizing():
    # Preview sizing must allow the capital allocator to recommend
    # more than one share when account capacity permits.
    assert WEBULL_PREVIEW_MAX_SHARES > 1


def test_capital_allocator_does_not_enable_order_submission():
    # Multi-share recommendations remain preview-only.
    assert WEBULL_ORDER_SUBMISSION_ENABLED is False
