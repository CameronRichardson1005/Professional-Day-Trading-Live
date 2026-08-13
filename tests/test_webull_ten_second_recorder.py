import csv
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from trading_bot.webull_ten_second_bars import (
    TenSecondBar,
)
from trading_bot.webull_ten_second_recorder import (
    TEN_SECOND_BAR_COLUMNS,
    TenSecondBarRecorder,
)
from trading_bot.webull_tick_recorder_service import (
    WebullTickRecorderService,
)


EASTERN = ZoneInfo(
    "America/New_York"
)


def make_bar(
    *,
    symbol="NVDA",
):
    return TenSecondBar(
        symbol=symbol,
        timestamp=datetime(
            2026,
            8,
            13,
            10,
            15,
            20,
            tzinfo=EASTERN,
        ),
        open=100.00,
        high=100.30,
        low=99.90,
        close=100.20,
        volume=1200,
        trades=15,
        trading_session="RTH",
    )


def epoch_ms(
    second,
):
    return int(
        datetime(
            2026,
            8,
            13,
            10,
            0,
            second,
            tzinfo=EASTERN,
        ).timestamp()
        * 1000
    )


def test_recorder_writes_header_and_bar(
    tmp_path,
):
    recorder = TenSecondBarRecorder(
        tmp_path
    )

    path = recorder.append_bar(
        make_bar()
    )

    assert path.exists()

    with path.open(
        newline="",
        encoding="utf-8",
    ) as handle:
        rows = list(
            csv.DictReader(handle)
        )

    assert len(rows) == 1

    assert list(
        rows[0].keys()
    ) == TEN_SECOND_BAR_COLUMNS

    assert rows[0]["symbol"] == "NVDA"
    assert rows[0]["open"] == "100.0"
    assert rows[0]["close"] == "100.2"
    assert rows[0]["trades"] == "15"


def test_recorder_appends_without_duplicate_header(
    tmp_path,
):
    recorder = TenSecondBarRecorder(
        tmp_path
    )

    recorder.append_bar(
        make_bar(
            symbol="AAA"
        )
    )

    recorder.append_bar(
        make_bar(
            symbol="BBB"
        )
    )

    path = recorder.path_for_date(
        "2026-08-13"
    )

    lines = path.read_text(
        encoding="utf-8"
    ).splitlines()

    assert len(lines) == 3

    assert (
        lines[0].startswith(
            "symbol,timestamp,"
        )
    )


def test_service_rejects_empty_symbol_list(
    tmp_path,
):
    try:
        WebullTickRecorderService(
            symbols=[],
            app_key="key",
            app_secret="secret",
            output_root=tmp_path,
        )
    except ValueError as error:
        assert (
            "At least one symbol"
            in str(error)
        )
    else:
        raise AssertionError(
            "Expected ValueError."
        )


def test_service_processes_ticks_and_writes_completed_bar(
    tmp_path,
):
    service = WebullTickRecorderService(
        symbols=["NVDA"],
        app_key="key",
        app_secret="secret",
        output_root=tmp_path,
    )

    service.process_tick({
        "symbol": "NVDA",
        "timestamp": epoch_ms(1),
        "price": 100.00,
        "volume": 100,
        "trading_session": "RTH",
    })

    service.process_tick({
        "symbol": "NVDA",
        "timestamp": epoch_ms(5),
        "price": 100.20,
        "volume": 200,
        "trading_session": "RTH",
    })

    completed = service.process_tick({
        "symbol": "NVDA",
        "timestamp": epoch_ms(11),
        "price": 100.30,
        "volume": 300,
        "trading_session": "RTH",
    })

    assert completed is not None
    assert completed.open == 100.00
    assert completed.high == 100.20
    assert completed.close == 100.20
    assert completed.volume == 300
    assert completed.trades == 2

    assert service.tick_messages == 3
    assert service.completed_bars == 1

    files = list(
        Path(tmp_path).glob(
            "*.csv"
        )
    )

    assert len(files) == 1


def test_service_ignores_unsubscribed_symbol(
    tmp_path,
):
    service = WebullTickRecorderService(
        symbols=["NVDA"],
        app_key="key",
        app_secret="secret",
        output_root=tmp_path,
    )

    result = service.process_tick({
        "symbol": "AMD",
        "timestamp": epoch_ms(1),
        "price": 100,
        "volume": 10,
    })

    assert result is None
    assert service.tick_messages == 0


def test_service_counts_invalid_tick(
    tmp_path,
):
    service = WebullTickRecorderService(
        symbols=["NVDA"],
        app_key="key",
        app_secret="secret",
        output_root=tmp_path,
    )

    result = service.process_tick({
        "symbol": "NVDA",
        "timestamp": epoch_ms(1),
        "price": 0,
        "volume": 10,
    })

    assert result is None
    assert service.invalid_ticks == 1


def test_flush_all_writes_open_bar(
    tmp_path,
):
    service = WebullTickRecorderService(
        symbols=["NVDA"],
        app_key="key",
        app_secret="secret",
        output_root=tmp_path,
    )

    service.process_tick({
        "symbol": "NVDA",
        "timestamp": epoch_ms(1),
        "price": 100,
        "volume": 50,
        "trading_session": "RTH",
    })

    flushed = service.flush_all()

    assert len(flushed) == 1
    assert service.completed_bars == 1

    files = list(
        Path(tmp_path).glob(
            "*.csv"
        )
    )

    assert len(files) == 1
