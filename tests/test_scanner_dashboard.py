from trading_bot.scanner import StockScanner
from trading_bot.scanner import StockStats
from trading_bot.sheets_client import SheetsClient
from trading_bot.models import Stock


def make_stats(
        symbol,
        avg_volume,
        avg_price,
        avg_range,
        avg_range_pct,
        valid_bars=30,
):
    return StockStats(
        symbol=symbol,
        valid_bars=valid_bars,
        avg_volume=avg_volume,
        avg_price=avg_price,
        avg_range=avg_range,
        avg_range_pct=avg_range_pct,
    )


def test_eligibility_failures_match_scanner_rules():
    scanner = StockScanner(
        current_symbols=["CORE"],
    )

    stats = make_stats(
        symbol="FAIL",
        valid_bars=10,
        avg_volume=100_000,
        avg_price=50.0,
        avg_range=0.10,
        avg_range_pct=2.0,
    )

    assert scanner.eligibility_failures(stats) == [
        "INSUFFICIENT BARS",
        "VOLUME BELOW MINIMUM",
        "RANGE BELOW MINIMUM",
        "RANGE % BELOW MINIMUM",
    ]
    assert scanner.is_eligible(stats) is False


def test_scanner_dashboard_reconciles_ranked_rows():
    scanner = StockScanner(
        current_symbols=["CORE"],
    )

    statistics = [
        make_stats(
            symbol="LYFT",
            avg_volume=800_000,
            avg_price=15.0,
            avg_range=0.60,
            avg_range_pct=5.0,
        ),
        make_stats(
            symbol="SNAP",
            avg_volume=2_000_000,
            avg_price=5.0,
            avg_range=0.50,
            avg_range_pct=5.0,
        ),
        make_stats(
            symbol="UBER",
            avg_volume=1_000_000,
            avg_price=72.0,
            avg_range=2.00,
            avg_range_pct=3.5,
        ),
    ]

    captured = {}
    worksheet = object()

    sheets = object.__new__(SheetsClient)

    def fake_get_or_create_worksheet(
            title,
            rows,
            cols,
    ):
        captured["creation"] = (
            title,
            rows,
            cols,
        )
        return worksheet

    def fake_replace_date_rows(**kwargs):
        captured["replacement"] = kwargs

    sheets.get_or_create_worksheet = (
        fake_get_or_create_worksheet
    )
    sheets._replace_date_rows = (
        fake_replace_date_rows
    )

    sheets.write_scanner_dashboard(
        date_str="2026-07-27",
        statistics=statistics,
        selected_symbols=["CORE", "SNAP"],
        scanner=scanner,
    )

    assert captured["creation"] == (
        "Scanner Dashboard",
        100,
        11,
    )

    replacement = captured["replacement"]

    assert replacement["worksheet"] is worksheet
    assert replacement["date_str"] == "2026-07-27"
    assert replacement["last_column"] == "K"
    assert replacement["sheet_name"] == (
        "Scanner Dashboard"
    )

    rows = replacement["replacement_rows"]

    assert [row[1] for row in rows] == [
        "SNAP",
        "LYFT",
        "UBER",
    ]

    assert rows[0][8:] == [
        "YES",
        "YES",
        "SELECTED",
    ]

    assert rows[1][8:] == [
        "YES",
        "NO",
        "ELIGIBLE - LIMIT REACHED",
    ]

    assert rows[2][8:] == [
        "NO",
        "NO",
        "RANGE % BELOW MINIMUM",
    ]


def test_orders_sheet_uses_original_trading_stop_loss():
    invest = Stock(symbol="OPEN")
    invest.signal = "INVEST"
    invest.limit_buy = 4.25
    invest.limit_sell = 4.50
    invest.stop_loss = 4.10
    invest.trading_stop_loss = 4.05

    skipped = Stock(symbol="SOUN")
    skipped.signal = "NO INVEST"

    captured = {}
    worksheet = object()
    sheets = object.__new__(SheetsClient)
    sheets.get_or_create_worksheet = (
        lambda title, rows, cols: worksheet
    )
    sheets._replace_date_rows = (
        lambda **kwargs: captured.update(kwargs)
    )

    sheets.write_orders(
        date_str="2026-07-27",
        stocks={
            "OPEN": invest,
            "SOUN": skipped,
        },
    )

    assert captured["columns"] == [
        "Date",
        "Symbol",
        "Limit Buy",
        "Limit Sell",
        "Trading Stop Loss",
        "Webull Preview",
        "Quantity",
        "Estimated Position Value",
        "Maximum Position Value",
        "Sizing Constraint",
        "Estimated Cost",
        "Estimated Fee",
        "Submitted",
    ]
    assert captured["replacement_rows"] == [
        [
            "2026-07-27",
            "OPEN",
            4.25,
            4.5,
            4.05,
            "NOT PREVIEWED",
            "",
            "",
            "",
            "",
            "",
            "",
            "NO",
        ]
    ]
