from datetime import UTC, datetime

from trading_bot.historical_portfolio_replay import (
    HistoricalPortfolioCandidate,
    replay_historical_portfolio,
)


def ts(hour, minute):
    return datetime(
        2026,
        3,
        2,
        hour,
        minute,
        tzinfo=UTC,
    )


def candidate(
    *,
    symbol,
    strategy="MANIPULATION",
    created,
    fill=None,
    exit_time=None,
    entry=10.0,
    pnl=1.0,
    status="COMPLETED",
    cancel=None,
    score=0.0,
    weight=1.0,
):
    return HistoricalPortfolioCandidate(
        date="2026-03-02",
        symbol=symbol,
        strategy=strategy,
        created_at=created,
        status=status,
        entry_price=entry,
        fill_time=fill,
        cancel_time=cancel,
        exit_time=exit_time,
        exit_price=(
            entry + pnl
            if exit_time is not None
            else None
        ),
        per_share_pnl=pnl,
        allocation_score=score,
        allocation_weight=weight,
    )


def rejection_map(report):
    return dict(
        report.rejection_counts
    )


def test_two_pending_entries_reserve_position_slots():
    items = [
        candidate(
            symbol="AAPL",
            created=ts(14, 45),
            fill=ts(14, 46),
            exit_time=ts(16, 0),
        ),
        candidate(
            symbol="MSFT",
            created=ts(14, 45),
            status="ENTRY_NOT_FILLED",
            fill=None,
            exit_time=None,
            cancel=ts(20, 0),
            pnl=0.0,
        ),
        candidate(
            symbol="NVDA",
            created=ts(14, 50),
            fill=ts(14, 51),
            exit_time=ts(16, 5),
        ),
    ]

    report = replay_historical_portfolio(
        candidates=items,
        market_bars={},
        per_position_cap=175.0,
    )

    assert report.accepted_entries == 2
    assert report.rejected_entries == 1
    assert (
        rejection_map(report)[
            "MAX_OPEN_POSITIONS_EXCEEDED"
        ]
        == 1
    )

    assert (
        report.max_position_symbols_observed
        <= 2
    )

    assert (
        report.max_open_orders_observed
        <= 2
    )


def test_exit_releases_position_slot():
    items = [
        candidate(
            symbol="AAPL",
            created=ts(14, 45),
            fill=ts(14, 46),
            exit_time=ts(15, 0),
        ),
        candidate(
            symbol="MSFT",
            created=ts(14, 45),
            fill=ts(14, 47),
            exit_time=ts(16, 0),
        ),
        candidate(
            symbol="NVDA",
            created=ts(15, 1),
            fill=ts(15, 2),
            exit_time=ts(16, 5),
        ),
    ]

    report = replay_historical_portfolio(
        candidates=items,
        market_bars={},
        per_position_cap=175.0,
    )

    assert report.accepted_entries == 3
    assert report.rejected_entries == 0
    assert report.completed_positions == 3


def test_realized_daily_loss_blocks_later_entry():
    items = [
        candidate(
            symbol="AAPL",
            created=ts(14, 45),
            fill=ts(14, 46),
            exit_time=ts(15, 0),
            entry=10.0,
            pnl=-2.0,
        ),
        candidate(
            symbol="MSFT",
            created=ts(15, 1),
            fill=ts(15, 2),
            exit_time=ts(16, 0),
        ),
    ]

    report = replay_historical_portfolio(
        candidates=items,
        market_bars={},
        per_position_cap=175.0,
        max_daily_loss=25.0,
    )

    assert report.accepted_entries == 1
    assert report.rejected_entries == 1

    assert (
        rejection_map(report)[
            "DAILY_LOSS_LIMIT_REACHED"
        ]
        == 1
    )

    assert report.total_realized_pnl == -34.0


def test_per_position_cap_controls_integer_quantity():
    items = [
        candidate(
            symbol="AAPL",
            created=ts(14, 45),
            fill=ts(14, 46),
            exit_time=ts(15, 0),
            entry=100.0,
            pnl=10.0,
        ),
    ]

    report = replay_historical_portfolio(
        candidates=items,
        market_bars={},
        per_position_cap=175.0,
    )

    assert report.accepted_entries == 1
    assert report.total_realized_pnl == 10.0


def test_strategy_priority_changes_same_time_single_slot():
    items = [
        candidate(
            symbol="AAPL",
            strategy="MANIPULATION",
            created=ts(14, 45),
            fill=ts(14, 46),
            exit_time=ts(15, 0),
            pnl=1.0,
        ),
        candidate(
            symbol="MSFT",
            strategy="QUICK_FLIP",
            created=ts(14, 45),
            fill=ts(14, 46),
            exit_time=ts(15, 0),
            pnl=2.0,
        ),
    ]

    manipulation_first = (
        replay_historical_portfolio(
            candidates=items,
            market_bars={},
            per_position_cap=175.0,
            max_open_positions=1,
            max_open_orders=1,
            strategy_priority=(
                "MANIPULATION",
                "QUICK_FLIP",
            ),
        )
    )

    quick_flip_first = (
        replay_historical_portfolio(
            candidates=items,
            market_bars={},
            per_position_cap=175.0,
            max_open_positions=1,
            max_open_orders=1,
            strategy_priority=(
                "QUICK_FLIP",
                "MANIPULATION",
            ),
        )
    )

    assert (
        dict(
            manipulation_first
            .strategy_realized_pnl
        )["MANIPULATION"]
        == 17.0
    )

    assert (
        dict(
            quick_flip_first
            .strategy_realized_pnl
        )["QUICK_FLIP"]
        == 34.0
    )


def test_same_time_new_entries_do_not_use_same_time_exit():
    items = [
        candidate(
            symbol="AAPL",
            created=ts(14, 45),
            fill=ts(14, 45),
            exit_time=ts(14, 45),
        ),
        candidate(
            symbol="MSFT",
            created=ts(14, 45),
            fill=ts(14, 45),
            exit_time=ts(14, 45),
        ),
    ]

    report = replay_historical_portfolio(
        candidates=items,
        market_bars={},
        per_position_cap=175.0,
        max_open_positions=1,
        max_open_orders=1,
    )

    assert report.accepted_entries == 1
    assert report.rejected_entries == 1


def test_higher_allocation_score_gets_capacity_first():
    items = [
        candidate(
            symbol="AAA",
            created=ts(14, 45),
            fill=ts(14, 46),
            exit_time=ts(15, 0),
            pnl=1.0,
            score=1.0,
        ),
        candidate(
            symbol="ZZZ",
            created=ts(14, 45),
            fill=ts(14, 46),
            exit_time=ts(15, 0),
            pnl=2.0,
            score=5.0,
        ),
    ]

    report = replay_historical_portfolio(
        candidates=items,
        market_bars={},
        per_position_cap=175.0,
        max_open_positions=1,
        max_open_orders=1,
    )

    assert report.accepted_entries == 1
    assert report.rejected_entries == 1

    pnl = dict(
        report.strategy_realized_pnl
    )

    assert pnl["MANIPULATION"] == 34.0


def test_allocator_weight_limits_position_budget():
    items = [
        candidate(
            symbol="AAA",
            created=ts(14, 45),
            fill=ts(14, 46),
            exit_time=ts(15, 0),
            entry=100.0,
            pnl=10.0,
            score=5.0,
            weight=0.5,
        ),
    ]

    report = replay_historical_portfolio(
        candidates=items,
        market_bars={},
        per_position_cap=500.0,
        operational_cap=475.0,
        hard_cap=500.0,
    )

    assert report.accepted_entries == 1

    assert report.total_realized_pnl == 20.0
