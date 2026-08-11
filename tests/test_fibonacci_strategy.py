from dataclasses import replace

import trading_bot.fibonacci_strategy as strategy_module

from trading_bot.fibonacci_retracement import RetracementSetup
from trading_bot.fibonacci_strategy import Fibonacci618Strategy
from trading_bot.models import Stock


def setup_record(**overrides):
    base = RetracementSetup(
        date="2026-08-03",
        symbol="TEST",
        data_feed="sip",
        fibonacci_level="FIB_61_8",
        retracement_ratio=0.618,
        setup_found=True,
        rejection_reason="",
        atr=1.0,
        reference_price=12.0,
        atr_pct=8.333,
        impulse_start_time="09:35",
        impulse_end_time="09:55",
        impulse_start_price=10.0,
        impulse_end_price=12.0,
        impulse_size=2.0,
        impulse_atr_multiple=2.0,
        impulse_duration_minutes=20,
        impulse_average_volume=1000.0,
        retracement_price=10.764,
        retracement_touch_time="10:05",
        retracement_touch_low=10.75,
        retracement_depth_actual=0.625,
        pullback_duration_minutes=10,
        pullback_average_volume=700.0,
        pullback_volume_ratio=0.70,
        confirmation_time="10:08",
        confirmation_open=10.80,
        confirmation_high=10.95,
        confirmation_low=10.78,
        confirmation_close=10.92,
        confirmation_body_pct=1.111,
        session_vwap_at_confirmation=10.70,
        confirmation_above_vwap=True,
        entry_price=10.96,
        entry_time="10:09",
        stop_price=10.74,
        target_price=12.00,
        reward_risk=4.727,
        outcome="NO ENTRY",
        exit_time="",
        exit_price=None,
        exit_reason="",
        gross_return_pct=None,
        net_return_pct=None,
        maximum_favourable_excursion_pct=None,
        maximum_adverse_excursion_pct=None,
        detail="Qualifying Fibonacci setup.",
    )

    return replace(base, **overrides)


def test_qualifying_fibonacci_setup_becomes_invest(monkeypatch):
    monkeypatch.setattr(
        strategy_module,
        "analyse_symbol_day",
        lambda **kwargs: [setup_record()],
    )

    stock = Stock(symbol="TEST")

    result = Fibonacci618Strategy().evaluate(
        stock=stock,
        date_str="2026-08-03",
        bars=[{"t": "2026-08-03T13:30:00Z"}],
        atr=1.0,
        data_feed="sip",
    )

    assert result.signal == "INVEST"
    assert result.strategy_name == "FIBONACCI_61_8"
    assert result.limit_buy == 10.96
    assert result.limit_sell == 12.00
    assert result.stop_loss == 10.74
    assert result.trading_stop_loss == 10.74
    assert result.reward_risk == 4.727
    assert result.confirmation_time == "10:08"


def test_nonqualifying_setup_is_no_invest(monkeypatch):
    monkeypatch.setattr(
        strategy_module,
        "analyse_symbol_day",
        lambda **kwargs: [
            setup_record(
                pullback_volume_ratio=1.10,
            )
        ],
    )

    stock = Stock(symbol="TEST")
    stock.limit_buy = 99.0
    stock.webull_preview = {"status": "OLD"}

    result = Fibonacci618Strategy().evaluate(
        stock=stock,
        date_str="2026-08-03",
        bars=[],
        atr=1.0,
        data_feed="sip",
    )

    assert result.signal == "NO INVEST"
    assert result.limit_buy is None
    assert result.limit_sell is None
    assert result.stop_loss is None
    assert result.trading_stop_loss is None
    assert result.webull_preview is None


def test_adapter_uses_only_fib_61_8(monkeypatch):
    wrong_level = setup_record(
        fibonacci_level="FIB_50_0",
        retracement_ratio=0.5,
    )

    monkeypatch.setattr(
        strategy_module,
        "analyse_symbol_day",
        lambda **kwargs: [wrong_level],
    )

    stock = Stock(symbol="TEST")

    result = Fibonacci618Strategy().evaluate(
        stock=stock,
        date_str="2026-08-03",
        bars=[],
        atr=1.0,
        data_feed="sip",
    )

    assert result.signal == "NO INVEST"


def test_fibonacci_adapter_does_not_expose_submission_method():
    strategy = Fibonacci618Strategy()

    assert not hasattr(strategy, "submit_order")
    assert not hasattr(strategy, "place_order")



def test_fibonacci_adapter_derives_red_opening_candle(
        monkeypatch,
):
    monkeypatch.setattr(
        strategy_module,
        "analyse_symbol_day",
        lambda **kwargs: [setup_record()],
    )

    stock = Stock(symbol="TEST")
    stock.opening_bar = {
        "o": 10.00,
        "h": 10.20,
        "l": 9.80,
        "c": 9.90,
    }

    result = Fibonacci618Strategy().evaluate(
        stock=stock,
        date_str="2026-08-03",
        bars=[],
        atr=1.0,
        data_feed="iex",
    )

    assert result.is_red is True


def test_fibonacci_adapter_derives_green_opening_candle(
        monkeypatch,
):
    monkeypatch.setattr(
        strategy_module,
        "analyse_symbol_day",
        lambda **kwargs: [setup_record()],
    )

    stock = Stock(symbol="TEST")
    stock.opening_bar = {
        "o": 10.00,
        "h": 10.20,
        "l": 9.80,
        "c": 10.10,
    }

    result = Fibonacci618Strategy().evaluate(
        stock=stock,
        date_str="2026-08-03",
        bars=[],
        atr=1.0,
        data_feed="iex",
    )

    assert result.is_red is False


def test_fibonacci_adapter_missing_opening_bar_is_not_red(
        monkeypatch,
):
    monkeypatch.setattr(
        strategy_module,
        "analyse_symbol_day",
        lambda **kwargs: [setup_record()],
    )

    stock = Stock(symbol="TEST")
    stock.opening_bar = None

    result = Fibonacci618Strategy().evaluate(
        stock=stock,
        date_str="2026-08-03",
        bars=[],
        atr=1.0,
        data_feed="iex",
    )

    assert result.is_red is False


def test_volume_rejection_has_explicit_reason(
        monkeypatch,
):
    monkeypatch.setattr(
        strategy_module,
        "analyse_symbol_day",
        lambda **kwargs: [
            setup_record(
                pullback_volume_ratio=1.10,
            )
        ],
    )

    stock = Stock(symbol="TEST")

    result = Fibonacci618Strategy().evaluate(
        stock=stock,
        date_str="2026-08-03",
        bars=[],
        atr=1.0,
        data_feed="iex",
    )

    assert result.signal == "NO INVEST"
    assert (
        result.strategy_rejection_reason
        == "PULLBACK_VOLUME_NOT_LOWER_THAN_IMPULSE"
    )


def test_short_impulse_has_explicit_reason(
        monkeypatch,
):
    monkeypatch.setattr(
        strategy_module,
        "analyse_symbol_day",
        lambda **kwargs: [
            setup_record(
                impulse_duration_minutes=10,
            )
        ],
    )

    stock = Stock(symbol="TEST")

    result = Fibonacci618Strategy().evaluate(
        stock=stock,
        date_str="2026-08-03",
        bars=[],
        atr=1.0,
        data_feed="iex",
    )

    assert result.signal == "NO INVEST"
    assert (
        result.strategy_rejection_reason
        == "IMPULSE_DURATION_BELOW_15_MINUTES"
    )
