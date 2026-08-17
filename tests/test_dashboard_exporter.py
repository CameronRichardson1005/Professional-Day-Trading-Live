from trading_bot.dashboard_exporter import (
    DashboardExporter,
)
from trading_bot.models import Stock


def complete_stock(
        symbol="TEST",
        signal="INVEST",
):
    stock = Stock(symbol=symbol)
    stock.opening_bar = {
        "o": 10.0,
        "h": 11.0,
        "l": 9.0,
        "c": 9.5,
    }
    stock.atr = 1.0
    stock.candle_range = 2.0
    stock.atr_threshold = 0.5
    stock.is_manipulation = True
    stock.is_red = True
    stock.signal = signal
    stock.limit_buy = 9.0
    stock.limit_sell = 9.382
    stock.stop_loss = 8.809
    stock.trading_stop_loss = 8.759
    return stock


def test_complete_invest_includes_levels():
    payload = DashboardExporter.build_payload(
        date_str="2026-07-23",
        source="REPLAY",
        stocks={
            "TEST": complete_stock(),
        },
        processed_bars={
            "TEST": 15,
        },
    )

    assert payload["status"] == "COMPLETE"
    assert payload["dataFeed"] == "WEBULL"
    assert payload["symbols"][0]["signal"] == "INVEST"
    assert payload["symbols"][0]["levels"] == {
        "buy": 9.0,
        "target": 9.382,
        "stop": 8.809,
        "tradingStop": 8.759,
    }


def test_incomplete_symbol_suppresses_signal_and_levels():
    payload = DashboardExporter.build_payload(
        date_str="2026-07-23",
        source="LIVE",
        stocks={
            "TEST": complete_stock(),
        },
        processed_bars={
            "TEST": 14,
        },
    )

    symbol = payload["symbols"][0]
    assert payload["status"] == "INCOMPLETE"
    assert symbol["signal"] == "WARNING"
    assert "levels" not in symbol


def test_missing_strategy_result_is_incomplete():
    stock = Stock(symbol="TEST")

    payload = DashboardExporter.build_payload(
        date_str="2026-07-23",
        source="LIVE",
        stocks={
            "TEST": stock,
        },
        processed_bars={
            "TEST": 15,
        },
    )

    symbol = payload["symbols"][0]
    assert payload["status"] == "INCOMPLETE"
    assert symbol["detail"] == "strategy unavailable"
    assert symbol["signal"] == "WARNING"


def test_no_invest_never_includes_levels():
    payload = DashboardExporter.build_payload(
        date_str="2026-07-23",
        source="REPLAY",
        stocks={
            "TEST": complete_stock(
                signal="NO INVEST"
            ),
        },
        processed_bars={
            "TEST": 15,
        },
    )

    symbol = payload["symbols"][0]
    assert payload["status"] == "COMPLETE"
    assert symbol["signal"] == "NO INVEST"
    assert "levels" not in symbol


def test_publish_skips_when_key_is_missing():
    exporter = DashboardExporter(
        ingest_key="",
        post_fn=lambda *args, **kwargs: (
            None
        ),
    )

    assert exporter.publish(
        date_str="2026-07-23",
        source="REPLAY",
        stocks={
            "TEST": complete_stock(),
        },
        processed_bars={
            "TEST": 15,
        },
    ) is None


def test_publish_uses_read_only_endpoint_contract():
    calls = []

    class Response:
        @staticmethod
        def raise_for_status():
            return None

        @staticmethod
        def json():
            return {
                "accepted": True,
                "id": "replay-2026-07-23",
                "status": "COMPLETE",
            }

    def post(url, **kwargs):
        calls.append((url, kwargs))
        return Response()

    exporter = DashboardExporter(
        url="https://example.test/api/sessions/latest",
        ingest_key="secret",
        site_token="site-token",
        post_fn=post,
    )

    result = exporter.publish(
        date_str="2026-07-23",
        source="REPLAY",
        stocks={
            "TEST": complete_stock(),
        },
        processed_bars={
            "TEST": 15,
        },
    )

    assert result["accepted"] is True
    assert calls[0][0].endswith(
        "/api/sessions/latest"
    )
    assert calls[0][1]["headers"] == {
        "x-dashboard-key": "secret",
        "OAI-Sites-Authorization": (
            "Bearer site-token"
        ),
    }
    assert calls[0][1]["timeout"] == (5, 15)
    assert calls[0][1]["json"]["dataFeed"] == "WEBULL"


def test_complete_invest_includes_outcome():
    stock = complete_stock()
    stock.outcome = {
        "status": "WIN",
        "entryTime": "09:45",
        "exitTime": "10:12",
        "entryPrice": 9.0,
        "exitPrice": 9.382,
        "pnlPerShare": 0.382,
        "returnPct": 4.244444,
        "detail": "Profit target reached first.",
    }

    payload = DashboardExporter.build_payload(
        date_str="2026-07-23",
        source="REPLAY",
        stocks={
            "TEST": stock,
        },
        processed_bars={
            "TEST": 15,
        },
    )

    assert payload["symbols"][0]["outcome"] == (
        stock.outcome
    )


def test_payload_includes_optional_symbol_reliability():
    reliability = [
        {
            "symbol": "BBAI",
            "completeness": 0.787,
            "usableDays": 10,
            "totalBars": 118,
            "expectedBars": 150,
            "status": "EXCLUDED_LOW_RELIABILITY",
        },
        {
            "symbol": "OPEN",
            "completeness": 0.947,
            "usableDays": 10,
            "totalBars": 142,
            "expectedBars": 150,
            "status": "SELECTED",
        },
    ]

    payload = DashboardExporter.build_payload(
        date_str="2026-07-28",
        source="LIVE",
        stocks={
            "OPEN": complete_stock(
                symbol="OPEN",
                signal="NO INVEST",
            ),
        },
        processed_bars={
            "OPEN": 15,
        },
        data_feed="iex",
        symbol_reliability=reliability,
    )

    assert payload["symbolReliability"] == reliability


def test_payload_omits_reliability_when_unavailable():
    payload = DashboardExporter.build_payload(
        date_str="2026-07-28",
        source="REPLAY",
        stocks={
            "TEST": complete_stock(),
        },
        processed_bars={
            "TEST": 15,
        },
    )

    assert "symbolReliability" not in payload


def test_payload_includes_optional_symbol_reliability():
    reliability = [
        {
            "symbol": "BBAI",
            "completeness": 0.787,
            "usableDays": 10,
            "totalBars": 118,
            "expectedBars": 150,
            "status": "EXCLUDED_LOW_RELIABILITY",
        },
        {
            "symbol": "OPEN",
            "completeness": 0.947,
            "usableDays": 10,
            "totalBars": 142,
            "expectedBars": 150,
            "status": "SELECTED",
        },
    ]

    payload = DashboardExporter.build_payload(
        date_str="2026-07-28",
        source="LIVE",
        stocks={
            "OPEN": complete_stock(
                symbol="OPEN",
                signal="NO INVEST",
            ),
        },
        processed_bars={
            "OPEN": 15,
        },
        data_feed="iex",
        symbol_reliability=reliability,
    )

    assert payload["symbolReliability"] == reliability


def test_payload_omits_reliability_when_unavailable():
    payload = DashboardExporter.build_payload(
        date_str="2026-07-28",
        source="REPLAY",
        stocks={
            "TEST": complete_stock(),
        },
        processed_bars={
            "TEST": 15,
        },
    )

    assert "symbolReliability" not in payload


def test_payload_includes_manual_production_health():
    stock = Stock(symbol="TEST")
    stock.green_minutes = 15

    payload = DashboardExporter.build_payload(
        date_str="2026-07-28",
        source="LIVE",
        stocks={"TEST": stock},
        processed_bars={"TEST": 15},
        data_feed="iex",
        run_mode="MANUAL",
    )

    assert payload["productionHealth"] == {
        "runMode": "MANUAL",
        "workflowStatus": "COMPLETED",
        "marketDay": True,
        "dataStatus": "WARNING",
    }


def test_payload_includes_scheduled_run_mode():
    stock = Stock(symbol="TEST")
    stock.green_minutes = 15

    payload = DashboardExporter.build_payload(
        date_str="2026-07-28",
        source="LIVE",
        stocks={"TEST": stock},
        processed_bars={"TEST": 15},
        data_feed="iex",
        run_mode="SCHEDULED",
    )

    assert (
        payload["productionHealth"]["runMode"]
        == "SCHEDULED"
    )


def test_invest_symbol_exports_webull_preview():
    stock = Stock(symbol="SOFI")
    stock.signal = "INVEST"
    stock.opening_bar = {
        "o": 16.90,
        "h": 17.00,
        "l": 16.70,
        "c": 16.75,
    }
    stock.atr = 0.90
    stock.candle_range = 0.30
    stock.atr_threshold = 0.225
    stock.is_manipulation = True
    stock.is_red = True
    stock.limit_buy = 16.70
    stock.limit_sell = 16.81
    stock.stop_loss = 16.64
    stock.trading_stop_loss = 16.59
    stock.webull_preview = {
        "status": "PREVIEW READY",
        "submitted": False,
        "symbol": "SOFI",
        "quantity": 227,
        "limitBuy": 16.70,
        "target": 16.81,
        "tradingStopLoss": 16.59,
        "riskPerShare": 0.11,
        "plannedRisk": 24.97,
        "estimatedPositionValue": 3790.90,
        "maxPositionValue": 5000.0,
        "sizingConstraint": "RISK_BUDGET",
        "estimatedCost": 3790.90,
        "estimatedTransactionFee": 0.0,
        "currency": "USD",
    }

    payload = DashboardExporter.build_payload(
        date_str="2026-07-29",
        source="LIVE",
        stocks={"SOFI": stock},
        processed_bars={"SOFI": 15},
        data_feed="iex",
    )

    preview = payload["symbols"][0]["webullPreview"]

    assert preview["status"] == "PREVIEW READY"
    assert preview["submitted"] is False
    assert preview["quantity"] == 227
    assert (
        preview["estimatedPositionValue"]
        == 3790.90
    )
    assert preview["maxPositionValue"] == 5000.0
    assert (
        preview["sizingConstraint"]
        == "RISK_BUDGET"
    )
    assert preview["estimatedCost"] == 3790.90
    assert preview["estimatedTransactionFee"] == 0.0


def test_no_invest_symbol_does_not_export_webull_preview():
    stock = Stock(symbol="RIVN")
    stock.signal = "NO INVEST"
    stock.webull_preview = {
        "status": "PREVIEW READY",
        "submitted": False,
    }

    payload = DashboardExporter.build_payload(
        date_str="2026-07-29",
        source="LIVE",
        stocks={"RIVN": stock},
        processed_bars={"RIVN": 15},
        data_feed="iex",
    )

    assert "webullPreview" not in payload["symbols"][0]


def test_more_than_fifteen_bars_remains_complete():
    payload = DashboardExporter.build_payload(
        date_str="2026-08-03",
        source="LIVE_MANIPULATION",
        stocks={
            "OPEN": complete_stock(),
        },
        processed_bars={
            "OPEN": 45,
        },
        data_feed="iex",
    )

    symbol = payload["symbols"][0]

    assert payload["status"] == "COMPLETE"
    assert symbol["signal"] == "INVEST"


def test_webull_preview_never_reports_submitted():
    stock = complete_stock()
    stock.webull_preview = {
        "status": "PREVIEW READY",
        "submitted": True,
        "symbol": "OPEN",
        "quantity": 100,
        "limitBuy": 4.25,
        "target": 4.60,
        "tradingStopLoss": 4.10,
    }

    payload = DashboardExporter.build_payload(
        date_str="2026-08-03",
        source="LIVE_MANIPULATION",
        stocks={"OPEN": stock},
        processed_bars={"OPEN": 38},
        data_feed="iex",
    )

    preview = payload["symbols"][0]["webullPreview"]

    assert preview["submitted"] is False



def test_dashboard_caps_opening_bars_processed_at_fifteen():
    stock = Stock(symbol="OPEN")
    stock.signal = "NO INVEST"
    stock.opening_bar = {
        "o": 3.91,
        "h": 3.95,
        "l": 3.80,
        "c": 3.815,
    }
    stock.atr = 0.20

    payload = DashboardExporter.build_payload(
        date_str="2026-08-05",
        source="LIVE_MANIPULATION",
        stocks={"OPEN": stock},
        processed_bars={"OPEN": 18},
        data_feed="iex",
    )

    symbol_payload = payload["symbols"][0]

    assert symbol_payload["barsProcessed"] == 15
    assert symbol_payload["barsExpected"] == 15


def test_payload_includes_redacted_webull_approval_status():
    approvals = [
        {
            "symbol": "OPEN",
            "quantity": 10,
            "limitPrice": 4.25,
            "proposedExposure": 42.50,
            "status": "PENDING",
            "createdAt": "2026-08-06T18:00:00Z",
            "expiresAt": "2026-08-06T18:05:00Z",
        }
    ]

    payload = DashboardExporter.build_payload(
        date_str="2026-08-06",
        source="LIVE_MANIPULATION",
        stocks={
            "OPEN": complete_stock(),
        },
        processed_bars={
            "OPEN": 38,
        },
        data_feed="iex",
        webull_approvals=approvals,
    )

    assert payload["webullApprovals"] == approvals
    assert payload["webullSafety"] == {
        "manualApprovalRequired": True,
        "killSwitchActive": True,
        "submissionEnabled": False,
    }


def test_payload_does_not_add_approval_fields_by_default():
    payload = DashboardExporter.build_payload(
        date_str="2026-08-06",
        source="LIVE_MANIPULATION",
        stocks={
            "OPEN": complete_stock(),
        },
        processed_bars={
            "OPEN": 38,
        },
        data_feed="iex",
    )

    assert "webullApprovals" not in payload
    assert "webullSafety" not in payload


def test_payload_includes_optional_paper_performance():
    performance = {
        "date": "2026-08-07",
        "ordersApproved": 5,
        "tradesEntered": 4,
        "closedTrades": 4,
        "noEntry": 1,
        "winRatePct": 75.0,
        "realizedPnl": 8.42,
        "simulationOnly": True,
        "brokerSubmitted": False,
    }

    payload = DashboardExporter.build_payload(
        date_str="2026-08-07",
        source="LIVE_MANIPULATION",
        stocks={
            "TEST": complete_stock(),
        },
        processed_bars={
            "TEST": 15,
        },
        data_feed="iex",
        paper_performance=performance,
    )

    assert (
        payload["paperPerformance"]
        == performance
    )


def test_payload_omits_paper_performance_when_unavailable():
    payload = DashboardExporter.build_payload(
        date_str="2026-08-07",
        source="LIVE_MANIPULATION",
        stocks={
            "TEST": complete_stock(),
        },
        processed_bars={
            "TEST": 15,
        },
        data_feed="iex",
    )

    assert "paperPerformance" not in payload


def test_publish_passes_paper_performance_to_endpoint():
    calls = []

    class Response:
        @staticmethod
        def raise_for_status():
            return None

        @staticmethod
        def json():
            return {
                "accepted": True,
                "id": "live_manipulation-2026-08-07",
                "status": "COMPLETE",
            }

    def post(url, **kwargs):
        calls.append((url, kwargs))
        return Response()

    exporter = DashboardExporter(
        url="https://example.test/api/sessions/latest",
        ingest_key="secret",
        site_token="site-token",
        post_fn=post,
    )

    performance = {
        "date": "2026-08-07",
        "realizedPnl": 8.42,
        "simulationOnly": True,
        "brokerSubmitted": False,
    }

    exporter.publish(
        date_str="2026-08-07",
        source="LIVE_MANIPULATION",
        stocks={
            "TEST": complete_stock(),
        },
        processed_bars={
            "TEST": 15,
        },
        data_feed="iex",
        paper_performance=performance,
    )

    assert (
        calls[0][1]["json"]["paperPerformance"]
        == performance
    )


def test_payload_includes_optional_paper_portfolio():
    portfolio = {
        "startingCash": 10000.0,
        "cash": 9965.0,
        "buyingPower": 9965.0,
        "marketValue": 42.0,
        "realizedPnl": 5.0,
        "unrealizedPnl": 2.0,
        "totalPnl": 7.0,
        "equity": 10007.0,
        "simulationOnly": True,
        "brokerSubmitted": False,
    }

    payload = DashboardExporter.build_payload(
        date_str="2026-08-07",
        source="LIVE_MANIPULATION",
        stocks={
            "TEST": complete_stock(),
        },
        processed_bars={
            "TEST": 15,
        },
        data_feed="iex",
        paper_portfolio=portfolio,
    )

    assert payload["paperPortfolio"] == portfolio


def test_payload_omits_paper_portfolio_when_unavailable():
    payload = DashboardExporter.build_payload(
        date_str="2026-08-07",
        source="LIVE_MANIPULATION",
        stocks={
            "TEST": complete_stock(),
        },
        processed_bars={
            "TEST": 15,
        },
        data_feed="iex",
    )

    assert "paperPortfolio" not in payload


def test_publish_passes_paper_portfolio_to_endpoint():
    calls = []

    class Response:
        @staticmethod
        def raise_for_status():
            return None

        @staticmethod
        def json():
            return {
                "accepted": True,
                "id": "live_manipulation-2026-08-07",
                "status": "COMPLETE",
            }

    def post(url, **kwargs):
        calls.append((url, kwargs))
        return Response()

    exporter = DashboardExporter(
        url="https://example.test/api/sessions/latest",
        ingest_key="secret",
        site_token="site-token",
        post_fn=post,
    )

    portfolio = {
        "startingCash": 10000.0,
        "cash": 10005.0,
        "equity": 10007.0,
        "simulationOnly": True,
        "brokerSubmitted": False,
    }

    exporter.publish(
        date_str="2026-08-07",
        source="LIVE_MANIPULATION",
        stocks={
            "TEST": complete_stock(),
        },
        processed_bars={
            "TEST": 15,
        },
        data_feed="iex",
        paper_portfolio=portfolio,
    )

    assert (
        calls[0][1]["json"]["paperPortfolio"]
        == portfolio
    )
