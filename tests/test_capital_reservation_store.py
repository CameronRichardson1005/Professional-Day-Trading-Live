import json

from trading_bot.capital_reservation_store import (
    DailyCapitalReservationStore,
)


def test_reservations_accumulate_across_strategies(
    tmp_path,
):
    store = DailyCapitalReservationStore(
        tmp_path / "capital.json"
    )

    store.reserve(
        date_str="2026-08-14",
        reservation_id="MANIPULATION:OPEN",
        strategy="MANIPULATION_OPENING_15M",
        symbol="OPEN",
        exposure=120.0,
    )

    store.reserve(
        date_str="2026-08-14",
        reservation_id=(
            "QUICK_FLIP:MARA:2026-08-14T10:05:00-04:00"
        ),
        strategy="QUICK_FLIP",
        symbol="MARA",
        exposure=80.0,
    )

    assert (
        store.total_reserved_exposure(
            "2026-08-14"
        )
        == 200.0
    )


def test_same_reservation_is_idempotent(
    tmp_path,
):
    store = DailyCapitalReservationStore(
        tmp_path / "capital.json"
    )

    store.reserve(
        date_str="2026-08-14",
        reservation_id="MANIPULATION:OPEN",
        strategy="MANIPULATION",
        symbol="OPEN",
        exposure=100.0,
    )

    store.reserve(
        date_str="2026-08-14",
        reservation_id="MANIPULATION:OPEN",
        strategy="MANIPULATION",
        symbol="OPEN",
        exposure=125.0,
    )

    assert (
        store.total_reserved_exposure(
            "2026-08-14"
        )
        == 125.0
    )


def test_new_trading_date_starts_fresh_pool(
    tmp_path,
):
    store = DailyCapitalReservationStore(
        tmp_path / "capital.json"
    )

    store.reserve(
        date_str="2026-08-14",
        reservation_id="MANIPULATION:OPEN",
        strategy="MANIPULATION",
        symbol="OPEN",
        exposure=300.0,
    )

    assert (
        store.total_reserved_exposure(
            "2026-08-15"
        )
        == 0.0
    )

    store.reserve(
        date_str="2026-08-15",
        reservation_id="QUICK_FLIP:MARA:SIGNAL",
        strategy="QUICK_FLIP",
        symbol="MARA",
        exposure=50.0,
    )

    assert (
        store.total_reserved_exposure(
            "2026-08-15"
        )
        == 50.0
    )

    payload = json.loads(
        (tmp_path / "capital.json").read_text()
    )

    assert payload["date"] == "2026-08-15"
    assert len(payload["reservations"]) == 1


def test_store_file_is_private(
    tmp_path,
):
    path = tmp_path / "capital.json"

    store = DailyCapitalReservationStore(path)

    store.reserve(
        date_str="2026-08-14",
        reservation_id="MANIPULATION:OPEN",
        strategy="MANIPULATION",
        symbol="OPEN",
        exposure=100.0,
    )

    assert (
        path.stat().st_mode & 0o777
    ) == 0o600
