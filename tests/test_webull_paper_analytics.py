from dataclasses import replace
from datetime import UTC, datetime

from trading_bot.webull_paper_analytics import (
    build_webull_paper_analytics,
    load_webull_paper_analytics,
)
from trading_bot.webull_paper_order_store import (
    WebullPaperOrderRecord,
    WebullPaperOrderStore,
)


def base_order(
    *,
    order_id,
    symbol,
):
    submitted = datetime(
        2026,
        8,
        7,
        13,
        45,
        tzinfo=UTC,
    )

    return WebullPaperOrderRecord(
        paper_order_id=order_id,
        approval_reference=f"approval-{order_id}",
        idempotency_key=f"idem-{order_id}",
        symbol=symbol,
        side="BUY",
        quantity=10,
        limit_price=10.0,
        proposed_exposure=100.0,
        status="PAPER SUBMITTED",
        created_at=submitted,
        submitted_at=submitted,
        safety_reason="APPROVED",
        target_price=11.0,
        stop_price=9.0,
    )


def closed_order(
    *,
    order_id,
    symbol,
    pnl,
    return_pct,
    reason,
    fill_hour,
    fill_minute,
    mfe,
    mae,
):
    base = base_order(
        order_id=order_id,
        symbol=symbol,
    )

    fill = datetime(
        2026,
        8,
        7,
        fill_hour,
        fill_minute,
        tzinfo=UTC,
    )

    return replace(
        base,
        lifecycle_status="CLOSED",
        filled_at=fill,
        fill_price=10.0,
        highest_price=10.0 * (
            1 + mfe / 100
        ),
        lowest_price=10.0 * (
            1 + mae / 100
        ),
        mfe_pct=mfe,
        mae_pct=mae,
        closed_at=fill,
        exit_price=10.0 * (
            1 + return_pct / 100
        ),
        exit_reason=reason,
        realized_pnl=pnl,
        return_pct=return_pct,
    )


def test_analytics_groups_by_symbol():
    records = [
        closed_order(
            order_id="1",
            symbol="OPEN",
            pnl=5,
            return_pct=5,
            reason="TARGET",
            fill_hour=14,
            fill_minute=1,
            mfe=6,
            mae=-1,
        ),
        closed_order(
            order_id="2",
            symbol="OPEN",
            pnl=-2,
            return_pct=-2,
            reason="STOP",
            fill_hour=14,
            fill_minute=5,
            mfe=1,
            mae=-3,
        ),
        closed_order(
            order_id="3",
            symbol="SOUN",
            pnl=1,
            return_pct=1,
            reason="TIME EXIT",
            fill_hour=14,
            fill_minute=22,
            mfe=2,
            mae=-0.5,
        ),
    ]

    report = build_webull_paper_analytics(
        records=records,
    )

    assert report.total_orders == 3
    assert report.closed_trades == 3
    assert report.realized_pnl == 4
    assert report.win_rate_pct == round(
        2 / 3 * 100,
        6,
    )

    open_group = next(
        group
        for group in report.by_symbol
        if group.key == "OPEN"
    )

    assert open_group.closed_trades == 2
    assert open_group.wins == 1
    assert open_group.losses == 1
    assert open_group.win_rate_pct == 50.0
    assert open_group.realized_pnl == 3
    assert open_group.expectancy_per_trade == 1.5
    assert open_group.target_exits == 1
    assert open_group.stop_exits == 1
    assert open_group.average_mfe_pct == 3.5
    assert open_group.average_mae_pct == -2.0
    assert open_group.sample_label == (
        "VERY SMALL SAMPLE"
    )


def test_analytics_groups_by_new_york_entry_time():
    records = [
        closed_order(
            order_id="1",
            symbol="OPEN",
            pnl=5,
            return_pct=5,
            reason="TARGET",
            fill_hour=13,
            fill_minute=31,
            mfe=6,
            mae=-1,
        ),
        closed_order(
            order_id="2",
            symbol="SOUN",
            pnl=-2,
            return_pct=-2,
            reason="STOP",
            fill_hour=13,
            fill_minute=43,
            mfe=1,
            mae=-3,
        ),
        closed_order(
            order_id="3",
            symbol="BBAI",
            pnl=2,
            return_pct=2,
            reason="TARGET",
            fill_hour=14,
            fill_minute=20,
            mfe=3,
            mae=-1,
        ),
    ]

    report = build_webull_paper_analytics(
        records=records,
    )

    first = next(
        group
        for group in report.by_entry_time
        if group.key == "09:30-09:44 ET"
    )

    second = next(
        group
        for group in report.by_entry_time
        if group.key == "10:15-10:29 ET"
    )

    assert first.closed_trades == 2
    assert first.win_rate_pct == 50.0
    assert first.realized_pnl == 3

    assert second.closed_trades == 1
    assert second.realized_pnl == 2


def test_no_entry_is_counted_but_not_realized():
    base = base_order(
        order_id="1",
        symbol="OPEN",
    )

    no_entry = replace(
        base,
        lifecycle_status="CLOSED",
        closed_at=datetime(
            2026,
            8,
            7,
            15,
            0,
            tzinfo=UTC,
        ),
        exit_reason="NO ENTRY",
    )

    report = build_webull_paper_analytics(
        records=[no_entry],
    )

    assert report.total_orders == 1
    assert report.entered_trades == 0
    assert report.closed_trades == 0
    assert report.no_entry == 1
    assert report.realized_pnl == 0
    assert report.win_rate_pct is None

    assert report.by_symbol[0].no_entry == 1
    assert report.by_symbol[0].sample_label == (
        "NO CLOSED SAMPLE"
    )


def test_open_trade_excluded_from_realized_metrics():
    base = base_order(
        order_id="1",
        symbol="OPEN",
    )

    opened = replace(
        base,
        lifecycle_status="OPEN",
        filled_at=datetime(
            2026,
            8,
            7,
            14,
            5,
            tzinfo=UTC,
        ),
        fill_price=10.0,
        highest_price=10.5,
        lowest_price=9.8,
        mfe_pct=5.0,
        mae_pct=-2.0,
    )

    report = build_webull_paper_analytics(
        records=[opened],
    )

    assert report.entered_trades == 1
    assert report.open_trades == 1
    assert report.closed_trades == 0
    assert report.realized_pnl == 0
    assert report.expectancy_per_trade is None


def test_sample_labels_prevent_overstating_small_results():
    records = [
        closed_order(
            order_id=str(index),
            symbol="OPEN",
            pnl=1,
            return_pct=1,
            reason="TARGET",
            fill_hour=14,
            fill_minute=index,
            mfe=2,
            mae=-1,
        )
        for index in range(1, 6)
    ]

    report = build_webull_paper_analytics(
        records=records,
    )

    group = report.by_symbol[0]

    assert group.win_rate_pct == 100.0
    assert group.closed_trades == 5
    assert group.sample_label == "SMALL SAMPLE"


def test_loader_reads_durable_paper_store(
    tmp_path,
):
    store = WebullPaperOrderStore(
        tmp_path / "paper-orders.json"
    )

    record = closed_order(
        order_id="1",
        symbol="OPEN",
        pnl=5,
        return_pct=5,
        reason="TARGET",
        fill_hour=14,
        fill_minute=1,
        mfe=6,
        mae=-1,
    )

    store.add(record)

    report = load_webull_paper_analytics(
        store=store,
    )

    assert report.total_orders == 1
    assert report.closed_trades == 1
    assert report.realized_pnl == 5
    assert report.simulation_only is True
    assert report.broker_submitted is False


def enriched_closed_order(
    *,
    order_id,
    pnl,
    reward_risk,
    impulse_atr,
    pullback_volume,
    confirmation_time,
):
    trade = closed_order(
        order_id=order_id,
        symbol="OPEN",
        pnl=pnl,
        return_pct=pnl,
        reason=(
            "TARGET"
            if pnl > 0
            else "STOP"
        ),
        fill_hour=14,
        fill_minute=5,
        mfe=max(pnl, 1),
        mae=min(pnl, -1),
    )

    return replace(
        trade,
        strategy_name="FIBONACCI_61_8",
        reward_risk=reward_risk,
        confirmation_time=confirmation_time,
        retracement_price=9.8,
        impulse_atr_multiple=impulse_atr,
        pullback_volume_ratio=pullback_volume,
    )


def test_analytics_groups_by_reward_risk():
    records = [
        enriched_closed_order(
            order_id="1",
            pnl=5,
            reward_risk=1.75,
            impulse_atr=0.6,
            pullback_volume=0.8,
            confirmation_time="10:07",
        ),
        enriched_closed_order(
            order_id="2",
            pnl=-2,
            reward_risk=2.20,
            impulse_atr=0.8,
            pullback_volume=0.6,
            confirmation_time="10:20",
        ),
        enriched_closed_order(
            order_id="3",
            pnl=4,
            reward_risk=2.75,
            impulse_atr=1.2,
            pullback_volume=0.4,
            confirmation_time="10:35",
        ),
    ]

    report = build_webull_paper_analytics(
        records=records,
    )

    low = next(
        group
        for group in report.by_reward_risk
        if group.key == "1.50-1.99"
    )

    middle = next(
        group
        for group in report.by_reward_risk
        if group.key == "2.00-2.49"
    )

    high = next(
        group
        for group in report.by_reward_risk
        if group.key == ">=2.50"
    )

    assert low.realized_pnl == 5
    assert middle.realized_pnl == -2
    assert high.realized_pnl == 4


def test_analytics_groups_by_impulse_strength():
    records = [
        enriched_closed_order(
            order_id="1",
            pnl=3,
            reward_risk=2.0,
            impulse_atr=0.60,
            pullback_volume=0.8,
            confirmation_time="10:07",
        ),
        enriched_closed_order(
            order_id="2",
            pnl=-1,
            reward_risk=2.0,
            impulse_atr=0.85,
            pullback_volume=0.8,
            confirmation_time="10:08",
        ),
        enriched_closed_order(
            order_id="3",
            pnl=5,
            reward_risk=2.0,
            impulse_atr=1.20,
            pullback_volume=0.8,
            confirmation_time="10:09",
        ),
    ]

    report = build_webull_paper_analytics(
        records=records,
    )

    assert {
        group.key
        for group in report.by_impulse_atr
    } == {
        "0.50-0.74 ATR",
        "0.75-0.99 ATR",
        "1.00-1.49 ATR",
    }


def test_analytics_groups_by_pullback_volume():
    records = [
        enriched_closed_order(
            order_id="1",
            pnl=4,
            reward_risk=2.0,
            impulse_atr=1.0,
            pullback_volume=0.40,
            confirmation_time="10:07",
        ),
        enriched_closed_order(
            order_id="2",
            pnl=-2,
            reward_risk=2.0,
            impulse_atr=1.0,
            pullback_volume=0.65,
            confirmation_time="10:08",
        ),
        enriched_closed_order(
            order_id="3",
            pnl=1,
            reward_risk=2.0,
            impulse_atr=1.0,
            pullback_volume=0.85,
            confirmation_time="10:09",
        ),
    ]

    report = build_webull_paper_analytics(
        records=records,
    )

    keys = {
        group.key
        for group in report.by_pullback_volume
    }

    assert keys == {
        "<0.50",
        "0.50-0.74",
        "0.75-0.99",
    }


def test_analytics_groups_by_confirmation_time():
    records = [
        enriched_closed_order(
            order_id="1",
            pnl=4,
            reward_risk=2.0,
            impulse_atr=1.0,
            pullback_volume=0.5,
            confirmation_time="10:07",
        ),
        enriched_closed_order(
            order_id="2",
            pnl=-2,
            reward_risk=2.0,
            impulse_atr=1.0,
            pullback_volume=0.5,
            confirmation_time="10:12",
        ),
        enriched_closed_order(
            order_id="3",
            pnl=3,
            reward_risk=2.0,
            impulse_atr=1.0,
            pullback_volume=0.5,
            confirmation_time="10:22",
        ),
    ]

    report = build_webull_paper_analytics(
        records=records,
    )

    first = next(
        group
        for group in report.by_confirmation_time
        if group.key == "10:00-10:14 ET"
    )

    second = next(
        group
        for group in report.by_confirmation_time
        if group.key == "10:15-10:29 ET"
    )

    assert first.closed_trades == 2
    assert first.realized_pnl == 2
    assert second.closed_trades == 1
    assert second.realized_pnl == 3


def test_legacy_metadata_is_reported_as_unavailable():
    trade = closed_order(
        order_id="1",
        symbol="OPEN",
        pnl=2,
        return_pct=2,
        reason="TARGET",
        fill_hour=14,
        fill_minute=1,
        mfe=3,
        mae=-1,
    )

    report = build_webull_paper_analytics(
        records=[trade],
    )

    assert report.by_reward_risk[0].key == (
        "UNAVAILABLE"
    )
    assert report.by_impulse_atr[0].key == (
        "UNAVAILABLE"
    )
    assert report.by_pullback_volume[0].key == (
        "UNAVAILABLE"
    )
    assert report.by_confirmation_time[0].key == (
        "UNAVAILABLE"
    )

    assert (
        report.by_reward_risk[0].realized_pnl
        == 2
    )
