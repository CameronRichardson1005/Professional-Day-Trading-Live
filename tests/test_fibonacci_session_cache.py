from trading_bot.bot import TradingBot


class FakeAlpaca:
    def __init__(self):
        self.opening_calls = []
        self.atr_calls = []

    def get_opening_15min_bars(
            self,
            *,
            symbols_csv,
            date_str,
            feed,
    ):
        self.opening_calls.append(
            (symbols_csv, date_str, feed)
        )

        return {
            symbol: {"symbol": symbol}
            for symbol in symbols_csv.split(",")
        }

    def get_previous_day_ranges_all(
            self,
            *,
            symbols_csv,
            date_str,
            feed,
    ):
        self.atr_calls.append(
            (symbols_csv, date_str, feed)
        )

        return {
            symbol: 1.0
            for symbol in symbols_csv.split(",")
        }


def make_bot():
    bot = object.__new__(TradingBot)
    bot.symbols_csv = "OPEN,SOUN"
    bot.alpaca = FakeAlpaca()
    return bot


def test_fibonacci_static_data_cached_within_session():
    bot = make_bot()

    first = bot._get_fibonacci_session_static_data(
        date_str="2026-08-07",
        data_feed="iex",
    )

    second = bot._get_fibonacci_session_static_data(
        date_str="2026-08-07",
        data_feed="iex",
    )

    assert first == second

    assert bot.alpaca.opening_calls == [
        (
            "OPEN,SOUN",
            "2026-08-07",
            "iex",
        ),
    ]

    assert bot.alpaca.atr_calls == [
        (
            "OPEN,SOUN",
            "2026-08-07",
            "iex",
        ),
    ]


def test_fibonacci_cache_separates_market_data_feeds():
    bot = make_bot()

    bot._get_fibonacci_session_static_data(
        date_str="2026-08-07",
        data_feed="iex",
    )

    bot._get_fibonacci_session_static_data(
        date_str="2026-08-07",
        data_feed="sip",
    )

    assert len(bot.alpaca.opening_calls) == 2
    assert len(bot.alpaca.atr_calls) == 2


def test_fibonacci_cache_separates_trading_dates():
    bot = make_bot()

    bot._get_fibonacci_session_static_data(
        date_str="2026-08-06",
        data_feed="iex",
    )

    bot._get_fibonacci_session_static_data(
        date_str="2026-08-07",
        data_feed="iex",
    )

    assert len(bot.alpaca.opening_calls) == 2
    assert len(bot.alpaca.atr_calls) == 2


def test_fibonacci_cache_separates_symbol_sets():
    bot = make_bot()

    bot._get_fibonacci_session_static_data(
        date_str="2026-08-07",
        data_feed="iex",
    )

    bot.symbols_csv = "OPEN,SOUN,RIVN"

    bot._get_fibonacci_session_static_data(
        date_str="2026-08-07",
        data_feed="iex",
    )

    assert len(bot.alpaca.opening_calls) == 2
    assert len(bot.alpaca.atr_calls) == 2
