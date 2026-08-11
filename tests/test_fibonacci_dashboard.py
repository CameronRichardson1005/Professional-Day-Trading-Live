from pathlib import Path

from trading_bot.fibonacci_dashboard import (
    FibonacciDashboardPublisher,
)


def test_build_payload_has_forward_only_status(
    tmp_path: Path,
):
    ledger = tmp_path / "ledger.csv"
    logs = tmp_path / "logs"
    logs.mkdir()

    ledger.write_text(
        "date,symbol,fibonacci_level,outcome,"
        "net_return_pct,submitted,"
        "observation_type\n"
        "2026-03-05,BBAI,FIB_61_8,WIN,"
        "2.046342,NO,HISTORICAL_VALIDATION\n",
        encoding="utf-8",
    )

    payload = FibonacciDashboardPublisher.build_payload(
        ledger_path=ledger,
        logs_directory=logs,
    )

    assert payload["safetyStatus"] == (
        "PAPER ONLY — NOT SUBMITTED"
    )
    assert payload["forward"]["qualifyingSetups"] == 0
    assert payload["forward"]["closedTrades"] == 0
    assert payload["latestForwardSetup"] is None


def test_publish_posts_to_fibonacci_endpoint(
    tmp_path: Path,
):
    ledger = tmp_path / "ledger.csv"
    logs = tmp_path / "logs"
    logs.mkdir()

    ledger.write_text(
        "date,symbol,fibonacci_level,outcome,"
        "net_return_pct,submitted,"
        "observation_type\n",
        encoding="utf-8",
    )

    captured = {}

    class Response:
        status_code = 200
        text = ""

        @staticmethod
        def raise_for_status():
            return None

        @staticmethod
        def json():
            return {"accepted": True}

    def post_fn(url, **kwargs):
        captured["url"] = url
        captured["kwargs"] = kwargs
        return Response()

    publisher = FibonacciDashboardPublisher(
        url="https://example.test",
        ingest_key="secret",
        site_token="token",
        post_fn=post_fn,
    )

    result = publisher.publish(
        ledger_path=ledger,
        logs_directory=logs,
    )

    assert result == {"accepted": True}
    assert captured["url"] == (
        "https://example.test/"
        "api/fibonacci-paper/latest"
    )
    assert (
        captured["kwargs"]["json"]["safetyStatus"]
        == "PAPER ONLY — NOT SUBMITTED"
    )
