from datetime import UTC, datetime

from trading_bot.bot import TradingBot
from trading_bot.models import Stock
from trading_bot.webull_paper_lifecycle import (
    WebullPaperLifecycleTracker,
)
from trading_bot.webull_paper_order_store import (
    WebullPaperOrderRecord,
    WebullPaperOrderStore,
)


def make_bot(tmp_path):
    bot = object.__new__(TradingBot)

    bot.stocks = {
        "OPEN": Stock(symbol="OPEN"),
    }
    bot.symbols_csv = "OPEN"

    bot._fibonacci_intraday_bar_cache = {}

    store = WebullPaperOrderStore(
        tmp_path / "paper-orders.json"
    )

    bot.webull_paper_lifecycle_tracker = (
        WebullPaperLifecycleTracker(
            store=store
        )
    )

    return bot, store


def add_order(store):
    submitted_at = datetime(
        2026,
        8,
        7,
        14,
        0,
        tzinfo=UTC,
    )

    store.add(
        WebullPaperOrderRecord(
            paper_order_id="paper-1",
            approval_reference="approval-1",
            idempotency_key="idem-1",
            symbol="OPEN",
            side="BUY",
            quantity=10,
            limit_price=4.25,
            proposed_exposure=42.50,
            status="PAPER SUBMITTED",
            created_at=submitted_at,
            submitted_at=submitted_at,
            safety_reason="APPROVED",
            target_price=4.60,
            stop_price=4.10,
        )
    )


def test_bot_lifecycle_uses_cached_bars_only(
    tmp_path,
):
    bot, store = make_bot(tmp_path)
    add_order(store)

    end = datetime(
        2026,
        8,
        7,
        14,
        2,
        tzinfo=UTC,
    )

    key = (
        "2026-08-07",
        "iex",
        "OPEN",
    )

    bot._fibonacci_intraday_bar_cache[key] = {
        "bars": {
            "OPEN": [{
                "t": "2026-08-07T14:01:00Z",
                "o": 4.20,
                "h": 4.30,
                "l": 4.20,
                "c": 4.28,
                "v": 1000,
            }]
        },
        "fetched_through": end,
    }

    bot._process_webull_paper_lifecycle(
        date_str="2026-08-07",
        evaluation_end=end,
        data_feed="iex",
    )

    record = store.load()["paper-1"]

    assert record.lifecycle_status == "OPEN"
    assert record.fill_price == 4.25


def test_bot_cutoff_finalizes_cached_open_trade(
    tmp_path,
):
    bot, store = make_bot(tmp_path)
    add_order(store)

    cutoff = datetime(
        2026,
        8,
        7,
        14,
        5,
        tzinfo=UTC,
    )

    key = (
        "2026-08-07",
        "iex",
        "OPEN",
    )

    bot._fibonacci_intraday_bar_cache[key] = {
        "bars": {
            "OPEN": [
                {
                    "t": "2026-08-07T14:01:00Z",
                    "o": 4.20,
                    "h": 4.30,
                    "l": 4.20,
                    "c": 4.28,
                    "v": 1000,
                },
                {
                    "t": "2026-08-07T14:04:00Z",
                    "o": 4.28,
                    "h": 4.40,
                    "l": 4.22,
                    "c": 4.35,
                    "v": 1000,
                },
            ]
        },
        "fetched_through": cutoff,
    }

    bot._finalize_webull_paper_lifecycle(
        date_str="2026-08-07",
        cutoff=cutoff,
        data_feed="iex",
    )

    record = store.load()["paper-1"]

    assert record.lifecycle_status == "CLOSED"
    assert record.exit_reason == "TIME EXIT"
    assert record.exit_price == 4.35
