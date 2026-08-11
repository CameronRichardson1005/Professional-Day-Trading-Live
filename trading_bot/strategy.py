from .config import ATR_MULTIPLIER, STOP_BUFFER
from .models import Stock


class ManipulationStrategy:
    """
    Preserved opening 15-minute manipulation strategy.

    This implementation remains in the repository for historical
    replay, backtesting, comparison, and audit purposes. It may be
    retired from active INVEST routing without being deleted.

    INVEST requires:
    1. Manipulation candle
    2. Red opening candle
    """

    def evaluate(
        self,
        stock: Stock,
        opening_bar: dict,
        atr: float,
    ) -> Stock:
        stock.opening_bar = opening_bar
        stock.atr = atr

        open_price = float(opening_bar["o"])
        high = float(opening_bar["h"])
        low = float(opening_bar["l"])
        close_price = float(opening_bar["c"])

        stock.candle_range = high - low
        stock.atr_threshold = atr * ATR_MULTIPLIER

        exceeds_threshold = (
            stock.candle_range > stock.atr_threshold
        )

        within_margin = (
            stock.atr_threshold - stock.candle_range
        ) <= 0.005

        stock.is_manipulation = (
            exceeds_threshold or within_margin
        )

        stock.is_red = open_price > close_price

        stock.limit_buy = low

        stock.limit_sell = low + (
            (high - low) * 0.382
        )

        stock.stop_loss = stock.limit_buy - (
            (stock.limit_sell - stock.limit_buy) / 2
        )

        stop_loss_is_too_close = (
            stock.limit_buy - STOP_BUFFER
        ) < stock.stop_loss

        if stop_loss_is_too_close:
            stock.stop_loss -= STOP_BUFFER

        stock.trading_stop_loss = (
            stock.stop_loss - STOP_BUFFER
        )

        stock.signal = (
            "INVEST"
            if stock.is_manipulation and stock.is_red
            else "NO INVEST"
        )

        distance_from_high = high - close_price
        distance_from_low = close_price - low

        if distance_from_low <= distance_from_high:
            stock.proximity = (
                f"{round(distance_from_low * 100, 1)}¢ "
                "from Low"
            )
        else:
            stock.proximity = (
                f"{round(distance_from_high * 100, 1)}¢ "
                "from High"
            )

        return stock