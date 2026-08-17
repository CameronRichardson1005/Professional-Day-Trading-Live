import os
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"

load_dotenv(dotenv_path=ENV_FILE, override=False)


# Webull is the sole market-data provider.
#
# These compatibility constants remain temporarily because
# existing internal method signatures use data_feed/provider
# arguments. They no longer select Alpaca, IEX, or SIP.
MARKET_DATA_FEED = "webull"
MARKET_DATA_PROVIDER = "webull"


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


# ------------------------------------------------------------
# Webull broker execution foundation
# ------------------------------------------------------------
#
# Only DISABLED and SANDBOX are permitted at this stage.
# LIVE_APPROVAL and LIVE_AUTO are intentionally recognized
# but hard-locked until sandbox validation is complete.
WEBULL_EXECUTION_MODE = os.getenv(
    "WEBULL_EXECUTION_MODE",
    "DISABLED",
).strip().upper()

_WEBULL_EXECUTION_MODES = {
    "DISABLED",
    "SANDBOX",
    "LIVE_APPROVAL",
    "LIVE_AUTO",
}

if WEBULL_EXECUTION_MODE not in _WEBULL_EXECUTION_MODES:
    raise RuntimeError(
        "WEBULL_EXECUTION_MODE must be one of: "
        + ", ".join(sorted(_WEBULL_EXECUTION_MODES))
    )

if WEBULL_EXECUTION_MODE in {
    "LIVE_APPROVAL",
    "LIVE_AUTO",
}:
    raise RuntimeError(
        "Live Webull execution modes are locked. "
        "Only DISABLED or SANDBOX may be used."
    )

# Sandbox credentials are deliberately separate from the
# existing production Webull preview/account credentials.
WEBULL_SANDBOX_APP_KEY = os.getenv(
    "WEBULL_SANDBOX_APP_KEY",
    "",
).strip()

WEBULL_SANDBOX_APP_SECRET = os.getenv(
    "WEBULL_SANDBOX_APP_SECRET",
    "",
).strip()

WEBULL_EXECUTION_LEDGER_FILE = Path(
    os.getenv(
        "WEBULL_EXECUTION_LEDGER_FILE",
        str(
            PROJECT_ROOT
            / "runtime"
            / "webull_execution_ledger.json"
        ),
    )
)


# A second explicit arming control for broker-mutating sandbox
# operations. WEBULL_EXECUTION_MODE=SANDBOX alone is not enough.
WEBULL_SANDBOX_ORDER_SUBMISSION_ENABLED = (
    os.getenv(
        "WEBULL_SANDBOX_ORDER_SUBMISSION_ENABLED",
        "false",
    ).strip().lower()
    in {"1", "true", "yes", "on"}
)


# Independent arm for modifying an already-existing sandbox
# order. This does NOT permit new order placement.
#
# Cancellation remains rescue-capable even when this is false.
WEBULL_SANDBOX_ORDER_MANAGEMENT_ENABLED = (
    os.getenv(
        "WEBULL_SANDBOX_ORDER_MANAGEMENT_ENABLED",
        "false",
    ).strip().lower()
    in {"1", "true", "yes", "on"}
)

# Explicit sandbox account selection prevents silently choosing
# the first account returned by Webull.
WEBULL_SANDBOX_ACCOUNT_ID = os.getenv(
    "WEBULL_SANDBOX_ACCOUNT_ID",
    "",
).strip()
