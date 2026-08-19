#!/bin/zsh

set -e

PROJECT="/Users/cameronrichardson/PycharmProjects/Professional-Day-Trading-Live"
PYTHON="/Users/cameronrichardson/PycharmProjects/PythonProjects/bin/python"

cd "$PROJECT" || exit 1

mkdir -p "$PROJECT/runtime/automation"

export PYTHONUNBUFFERED=1

if [ -n "$1" ]; then
    DATE="$1"
else
    DATE="$(TZ=America/New_York date +%F)"
fi

echo
echo "POST-SESSION RECOVERY"
echo "Trading date: $DATE"
echo

if pgrep -f "main.py production" >/dev/null 2>&1; then
    echo "Production is still running."
    echo "Recovery will not run at the same time."
    exit 1
fi

"$PYTHON" main.py backfill "$DATE"

"$PYTHON" - <<'PY'
from trading_bot.bot import TradingBot

bot = TradingBot()
bot.initialise_trading_sheets()
bot.trading_sheets.format_all_sheets()

print()
print("Trading workbook formatting complete.")
PY

echo
echo "SESSION RECOVERY COMPLETE"
echo "Trading date: $DATE"
echo "No broker orders were submitted."
