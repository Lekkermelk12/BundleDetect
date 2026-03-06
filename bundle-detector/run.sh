#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

VENV_DIR="${VENV_DIR:-.venv}"
ENV_FILE="${ENV_FILE:-.env}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing $ENV_FILE. Create it with required variables before running." >&2
  exit 1
fi

if [[ ! -d "$VENV_DIR" ]]; then
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

python -m pip install --upgrade pip
pip install -r requirements.txt
python -m playwright install

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

MONITOR_LOG="${MONITOR_LOG:-monitor.log}"
BOT_LOG="${BOT_LOG:-bot.log}"

python main.py monitor >"$MONITOR_LOG" 2>&1 &
MONITOR_PID=$!

python main.py bot >"$BOT_LOG" 2>&1 &
BOT_PID=$!

cleanup() {
  kill "$MONITOR_PID" "$BOT_PID" 2>/dev/null || true
}

trap cleanup EXIT INT TERM

echo "Monitor started (pid=$MONITOR_PID, log=$MONITOR_LOG)"
echo "Bot started (pid=$BOT_PID, log=$BOT_LOG)"
echo "Press Ctrl+C to stop both processes."

wait -n "$MONITOR_PID" "$BOT_PID"
STATUS=$?

echo "A process exited (status=$STATUS). Stopping remaining process..."
cleanup
wait "$MONITOR_PID" "$BOT_PID" 2>/dev/null || true

exit "$STATUS"
