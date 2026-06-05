#!/usr/bin/env bash
# run_daily.sh — wrapper for the daily internship bot run.
# Called by cron or manually. Activates venv, runs main, logs output.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${REPO_DIR}/.venv"
LOG_DIR="${REPO_DIR}/logs"
LOG_FILE="${LOG_DIR}/cron_$(date +%Y-%m-%d).log"

mkdir -p "$LOG_DIR"

echo "=== internship_bot daily run $(date) ===" >> "$LOG_FILE"

# Activate virtual environment if it exists
if [ -f "${VENV_DIR}/bin/activate" ]; then
    source "${VENV_DIR}/bin/activate"
fi

cd "$REPO_DIR"
python -m src.main "$@" >> "$LOG_FILE" 2>&1

echo "=== done $(date) ===" >> "$LOG_FILE"
