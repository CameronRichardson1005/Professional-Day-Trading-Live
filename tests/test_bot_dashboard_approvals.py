from trading_bot.bot import TradingBot


class PublicQueue:
    def list_public_records(self):
        return [
            {
                "symbol": "OPEN",
                "quantity": 10,
                "limitPrice": 4.25,
                "proposedExposure": 42.5,
                "status": "PENDING",
                "createdAt": "2026-08-06T18:00:00Z",
                "expiresAt": "2026-08-06T18:05:00Z",
            }
        ]


class FailingQueue:
    def list_public_records(self):
        raise RuntimeError("store unavailable")


def test_dashboard_uses_redacted_approval_records():
    bot = TradingBot.__new__(TradingBot)
    bot.webull_approval_queue = PublicQueue()

    records = bot._dashboard_webull_approvals()

    assert records == [
        {
            "symbol": "OPEN",
            "quantity": 10,
            "limitPrice": 4.25,
            "proposedExposure": 42.5,
            "status": "PENDING",
            "createdAt": "2026-08-06T18:00:00Z",
            "expiresAt": "2026-08-06T18:05:00Z",
        }
    ]


def test_missing_queue_fails_closed():
    bot = TradingBot.__new__(TradingBot)
    bot.webull_approval_queue = None

    assert bot._dashboard_webull_approvals() == []


def test_unreadable_queue_fails_closed():
    bot = TradingBot.__new__(TradingBot)
    bot.webull_approval_queue = FailingQueue()

    assert bot._dashboard_webull_approvals() == []
