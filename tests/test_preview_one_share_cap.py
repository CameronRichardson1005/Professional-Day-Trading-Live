from trading_bot.config import WEBULL_PREVIEW_MAX_SHARES


def test_preview_share_cap_is_exactly_one():
    assert WEBULL_PREVIEW_MAX_SHARES == 1
