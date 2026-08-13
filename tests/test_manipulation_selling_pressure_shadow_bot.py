from trading_bot.bot import TradingBot
from trading_bot.models import Stock


class FakeAlpaca:
    def __init__(self):
        self.calls = []

    def get_historical_opening_15min_bars(
        self,
        *,
        symbols_csv,
        start_date,
        end_date,
        feed,
    ):
        self.calls.append({
            "symbols_csv": symbols_csv,
            "start_date": start_date,
            "end_date": end_date,
            "feed": feed,
        })

        return {
            "TEST": [
                {
                    "t": "2026-08-06T13:30:00Z",
                    "o": 10.0,
                    "h": 10.5,
                    "l": 9.9,
                    "c": 10.1,
                    "v": 1000,
                },
                {
                    "t": "2026-08-07T13:30:00Z",
                    "o": 10.0,
                    "h": 10.5,
                    "l": 9.9,
                    "c": 10.1,
                    "v": 1000,
                },
                {
                    "t": "2026-08-10T13:30:00Z",
                    "o": 10.0,
                    "h": 10.5,
                    "l": 9.9,
                    "c": 10.1,
                    "v": 1000,
                },
                {
                    "t": "2026-08-11T13:30:00Z",
                    "o": 10.0,
                    "h": 10.5,
                    "l": 9.9,
                    "c": 10.1,
                    "v": 1000,
                },
                {
                    "t": "2026-08-12T13:30:00Z",
                    "o": 10.0,
                    "h": 10.5,
                    "l": 9.9,
                    "c": 10.1,
                    "v": 1000,
                },
                # Must NOT be included in the prior-volume average.
                {
                    "t": "2026-08-13T13:30:00Z",
                    "o": 10.5,
                    "h": 10.5,
                    "l": 10.0,
                    "c": 10.02,
                    "v": 999999,
                },
            ]
        }


def test_shadow_builder_does_not_modify_live_manipulation_trade():
    bot = object.__new__(TradingBot)

    stock = Stock(symbol="TEST")

    stock.signal = "INVEST"
    stock.opening_bar = {
        "t": "2026-08-13T13:30:00Z",
        "o": 10.50,
        "h": 10.50,
        "l": 10.00,
        "c": 10.02,
        "v": 3000,
    }

    stock.limit_buy = 10.00
    stock.limit_sell = 10.191
    stock.stop_loss = 9.85
    stock.trading_stop_loss = 9.80

    bot.stocks = {
        "TEST": stock,
    }

    bot.alpaca = FakeAlpaca()
    bot.manipulation_selling_pressure_shadows = {}

    original_live_values = (
        stock.signal,
        stock.limit_buy,
        stock.limit_sell,
        stock.stop_loss,
        stock.trading_stop_loss,
    )

    shadows = (
        bot.build_manipulation_selling_pressure_shadows(
            date_str="2026-08-13",
            data_feed="iex",
        )
    )

    assert "TEST" in shadows

    shadow = shadows["TEST"]

    # Prior five sessions average 1,000 volume.
    # Today's live opening volume is 3,000.
    assert shadow.relative_volume == 3.0

    assert shadow.normal_entry == 10.00
    assert shadow.adaptive_entry == 9.975

    # Most important production-safety assertion:
    assert (
        stock.signal,
        stock.limit_buy,
        stock.limit_sell,
        stock.stop_loss,
        stock.trading_stop_loss,
    ) == original_live_values

    assert len(bot.alpaca.calls) == 1
    assert (
        bot.alpaca.calls[0]["symbols_csv"]
        == "TEST"
    )
    assert (
        bot.alpaca.calls[0]["end_date"]
        == "2026-08-13"
    )
