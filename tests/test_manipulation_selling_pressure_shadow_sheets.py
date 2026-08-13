from types import SimpleNamespace

from trading_bot.sheets_client import SheetsClient


class FakeWorksheet:
    pass


def test_shadow_sheet_writer_uses_research_schema():
    client = object.__new__(SheetsClient)

    worksheet = FakeWorksheet()
    captured = {}

    client.get_or_create_worksheet = (
        lambda **kwargs: worksheet
    )

    def replace(**kwargs):
        captured.update(kwargs)

    client._replace_date_rows = replace

    shadow = SimpleNamespace(
        symbol="TEST",
        close_location=0.04,
        relative_volume=3.0,
        normal_entry=10.0,
        adaptive_entry=9.975,
        target=10.191,
        variant_a_stop=9.80,
        variant_b_stop=9.75,
        variant_a_outcome="PENDING",
        variant_b_outcome="PENDING",
    )

    client.write_manipulation_selling_pressure_research(
        date_str="2026-08-13",
        shadows={"TEST": shadow},
    )

    assert captured["worksheet"] is worksheet
    assert captured["date_str"] == "2026-08-13"
    assert captured["last_column"] == "K"

    assert captured["columns"] == [
        "Date",
        "Symbol",
        "Close Location",
        "Relative Volume",
        "Normal Entry",
        "Adaptive Entry",
        "Target",
        "Variant A Stop (1.00x)",
        "Variant B Stop (1.25x)",
        "Variant A Outcome",
        "Variant B Outcome",
    ]

    row = captured["replacement_rows"][0]

    assert row[0] == "2026-08-13"
    assert row[1] == "TEST"
    assert row[4] == 10.0
    assert row[5] == 9.975
    assert row[9] == "PENDING"
    assert row[10] == "PENDING"


def test_shadow_sheet_writer_can_reconcile_zero_triggers():
    client = object.__new__(SheetsClient)

    worksheet = FakeWorksheet()
    captured = {}

    client.get_or_create_worksheet = (
        lambda **kwargs: worksheet
    )

    client._replace_date_rows = (
        lambda **kwargs: captured.update(kwargs)
    )

    client.write_manipulation_selling_pressure_research(
        date_str="2026-08-13",
        shadows={},
    )

    assert captured["replacement_rows"] == []
