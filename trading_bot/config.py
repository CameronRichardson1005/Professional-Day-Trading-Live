import os
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"

load_dotenv(dotenv_path=ENV_FILE, override=False)


API_KEY = os.getenv(
    "ALPACA_API_KEY",
    "",
).strip()

API_SECRET = os.getenv(
    "ALPACA_API_SECRET",
    "",
).strip()

# Alpaca is an optional fallback/research provider.
#
# Missing Alpaca credentials must not prevent the Webull-primary
# production bot from starting. AlpacaClient validates credentials
# only when an Alpaca network request is actually attempted.
BASE_URL = "https://data.alpaca.markets/v2/stocks/bars"

ALPACA_DATA_FEED = os.getenv(
    "ALPACA_DATA_FEED",
    "sip",
).strip().lower()

if ALPACA_DATA_FEED not in {"iex", "sip"}:
    raise RuntimeError(
        "ALPACA_DATA_FEED must be 'iex' or 'sip'."
    )

MARKET_DATA_FEED = ALPACA_DATA_FEED

# Primary market-data provider for production decisions.
#
# Webull is the default because production strategy market data
# and the trading workflow are Webull-based.
#
# Alpaca remains available as a controlled fallback and for
# research/source comparisons.
MARKET_DATA_PROVIDER = os.getenv(
    "MARKET_DATA_PROVIDER",
    "webull",
).strip().lower()

if MARKET_DATA_PROVIDER not in {
    "webull",
    "alpaca",
}:
    raise RuntimeError(
        "MARKET_DATA_PROVIDER must be "
        "'webull' or 'alpaca'."
    )


# Standalone live Manipulation strategy.
MANIPULATION_STRATEGY_NAME = "MANIPULATION_OPENING_15M"

# Real broker submission remains intentionally unsupported.
REAL_ORDER_SUBMISSION_ENABLED = False

# Quick Flip monitors completed 5-minute reversal candles
# after the 09:30-09:45 opening range has closed.
QUICK_FLIP_MONITOR_START = "09:45"
QUICK_FLIP_MONITOR_CUTOFF = "11:00"
QUICK_FLIP_MONITOR_INTERVAL_SECONDS = 60

TICKERS = [
    "BBAI",
    "OPEN",
    "SOUN",
    "SOFI",
    "RIVN",
    "PLTR",
]

# Broad scanner universe. The scanner ranks these candidates
# each session, but only the top three eligible candidates join
# the six core symbols for live tracking.
CANDIDATE_TICKERS = [
    "SNAP",
    "UBER",
    "PINS",
    "RGTI",
    "SOXL",
    "LYFT",
    "NVDA",
    "AMD",
    "INTC",
    "MU",
    "F",
    "NIO",
    "LCID",
    "MARA",
    "RIOT",
    "HOOD",
    "AFRM",
    "DKNG",
    "IONQ",
]

ATR_MULTIPLIER = 0.25
STOP_BUFFER = 0.05

DASHBOARD_URL = os.getenv(
    "DASHBOARD_URL",
    (
        "https://cameron-trading-desk."
        "cameron-richardson.workers.dev"
        "/api/sessions/latest"
    ),
).strip()

if "chatgpt.site" in DASHBOARD_URL.lower():
    raise RuntimeError(
        "DASHBOARD_URL must use the Cloudflare trading desk. "
        "ChatGPT-hosted dashboard URLs are not supported."
    )

DASHBOARD_INGEST_KEY = os.getenv(
    "DASHBOARD_INGEST_KEY",
    "",
).strip()

DASHBOARD_SITE_TOKEN = os.getenv(
    "DASHBOARD_SITE_TOKEN",
    "",
).strip()

DASHBOARD_REQUEST_TIMEOUT = (5, 15)

SPREADSHEET_ID = os.getenv(
    "GOOGLE_SPREADSHEET_ID",
    "1fe4SD1jGvZ9bVudcFc--o8fwlHoiAxZSYeMUypNVFOQ",
).strip()

if not SPREADSHEET_ID:
    raise RuntimeError(
        "GOOGLE_SPREADSHEET_ID cannot be empty."
    )

# Separate clean workbook for the current Manipulation +
# Quick Flip workflow. The legacy GOOGLE_SPREADSHEET_ID
# remains unchanged and continues to preserve the existing
# workbook/history.
NEW_TRADING_SPREADSHEET_ID = os.getenv(
    "NEW_TRADING_SPREADSHEET_ID",
    "",
).strip()

SHEETS_REQUEST_TIMEOUT = (10, 20)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

CREDS_FILE = os.getenv(
    "GOOGLE_CREDS_FILE",
    str(
        PROJECT_ROOT
        / "Scripts"
        / "data"
        / "day-trading-scr-32d7db89c6b8.json"

    ),
)

# Webull preview-only integration.
WEBULL_APP_KEY = os.getenv(
    "WEBULL_APP_KEY",
    "",
).strip()

WEBULL_APP_SECRET = os.getenv(
    "WEBULL_APP_SECRET",
    "",
).strip()

WEBULL_PREVIEW_ENABLED = (
    os.getenv(
        "WEBULL_PREVIEW_ENABLED",
        "false",
    ).strip().lower()
    in {"1", "true", "yes", "on"}
)

WEBULL_PREVIEW_RISK_DOLLARS = float(
    os.getenv(
        "WEBULL_PREVIEW_RISK_DOLLARS",
        "25",
    )
)

# Capital-allocation preview sizing.
#
# Position value, available cash, buying power, risk budget,
# and account-exposure limits remain the primary constraints.
# This high share ceiling prevents the previous comparison-only
# one-share rule from suppressing allocation recommendations.
#
# This is preview sizing only and does not enable broker orders.
WEBULL_PREVIEW_MAX_SHARES = int(
    os.getenv(
        "WEBULL_PREVIEW_MAX_SHARES",
        "100000",
    )
)

# Fraction of the conservative cash-safe capital base that may
# be considered for today's preview recommendations.
#
# The hard real-order safety limits below are independent and are
# NOT increased by this preview-allocation setting.
WEBULL_CAPITAL_DEPLOYMENT_FRACTION = float(
    os.getenv(
        "WEBULL_CAPITAL_DEPLOYMENT_FRACTION",
        "0.90",
    )
)

WEBULL_PREVIEW_MAX_POSITION_VALUE = float(
    os.getenv(
        "WEBULL_PREVIEW_MAX_POSITION_VALUE",
        "500",
    )
)

if WEBULL_PREVIEW_RISK_DOLLARS <= 0:
    raise RuntimeError(
        "WEBULL_PREVIEW_RISK_DOLLARS must be positive."
    )

if WEBULL_PREVIEW_MAX_SHARES <= 0:
    raise RuntimeError(
        "WEBULL_PREVIEW_MAX_SHARES must be positive."
    )

if not (
    0
    < WEBULL_CAPITAL_DEPLOYMENT_FRACTION
    <= 1
):
    raise RuntimeError(
        "WEBULL_CAPITAL_DEPLOYMENT_FRACTION must be "
        "greater than 0 and at most 1."
    )

if WEBULL_PREVIEW_MAX_POSITION_VALUE <= 0:
    raise RuntimeError(
        "WEBULL_PREVIEW_MAX_POSITION_VALUE must be positive."
    )


# Hard Webull account safety limits.
#
# These limits apply independently of strategy sizing. They must
# remain enforced before any future real-order submission.
WEBULL_MAX_TOTAL_EXPOSURE_DOLLARS = float(
    os.getenv(
        "WEBULL_MAX_TOTAL_EXPOSURE_DOLLARS",
        "500",
    )
)

WEBULL_OPERATIONAL_EXPOSURE_CAP_DOLLARS = float(
    os.getenv(
        "WEBULL_OPERATIONAL_EXPOSURE_CAP_DOLLARS",
        "475",
    )
)

WEBULL_REQUIRE_CASH_ACCOUNT = True
WEBULL_ALLOW_MARGIN = False
WEBULL_ALLOW_SHORT_SELLING = False
WEBULL_REQUIRE_MANUAL_APPROVAL = True

# Real Webull order submission remains disabled. This is a
# hard-coded fail-safe rather than an environment-controlled flag.
WEBULL_ORDER_SUBMISSION_ENABLED = False

if WEBULL_MAX_TOTAL_EXPOSURE_DOLLARS <= 0:
    raise RuntimeError(
        "WEBULL_MAX_TOTAL_EXPOSURE_DOLLARS must be positive."
    )

if WEBULL_OPERATIONAL_EXPOSURE_CAP_DOLLARS <= 0:
    raise RuntimeError(
        "WEBULL_OPERATIONAL_EXPOSURE_CAP_DOLLARS must be positive."
    )

if (
    WEBULL_OPERATIONAL_EXPOSURE_CAP_DOLLARS
    > WEBULL_MAX_TOTAL_EXPOSURE_DOLLARS
):
    raise RuntimeError(
        "Webull operational exposure cap cannot exceed "
        "the hard total-exposure cap."
    )

# Webull manual approval workflow.
WEBULL_APPROVAL_TTL_SECONDS = int(
    os.getenv(
        "WEBULL_APPROVAL_TTL_SECONDS",
        "300",
    )
)

if WEBULL_APPROVAL_TTL_SECONDS <= 0:
    raise RuntimeError(
        "WEBULL_APPROVAL_TTL_SECONDS must be positive."
    )

# Hard fail-safe. The approval workflow may be tested while
# this remains active, but no approved order can be claimed
# for submission.
WEBULL_TRADING_KILL_SWITCH = True

WEBULL_APPROVAL_STORE_FILE = Path(
    os.getenv(
        "WEBULL_APPROVAL_STORE_FILE",
        str(
            PROJECT_ROOT
            / "runtime"
            / "webull_approvals.json"
        ),
    )
)
