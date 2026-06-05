#!/usr/bin/env bash
# setup_cron.sh — install a daily crontab entry for internship_bot.
# Run once. Re-running is safe (idempotent).

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${REPO_DIR}/.venv"
SCRIPT="${REPO_DIR}/scripts/run_daily.sh"

# Detect python path
if [ -f "${VENV_DIR}/bin/python" ]; then
    PYTHON="${VENV_DIR}/bin/python"
else
    PYTHON="$(which python3)"
fi

echo "Repository : $REPO_DIR"
echo "Python     : $PYTHON"
echo ""
read -rp "What time should the bot run? (24h format, e.g. 08:00): " TIME_INPUT

HOUR="${TIME_INPUT%%:*}"
MINUTE="${TIME_INPUT##*:}"

# Validate
if ! [[ "$HOUR" =~ ^[0-9]+$ ]] || ! [[ "$MINUTE" =~ ^[0-9]+$ ]]; then
    echo "Invalid time. Please use HH:MM format."
    exit 1
fi

CRON_LINE="${MINUTE} ${HOUR} * * * bash ${SCRIPT} >> ${REPO_DIR}/logs/cron.log 2>&1"

# Add only if not already present
( crontab -l 2>/dev/null | grep -v "internship_bot"; echo "$CRON_LINE" ) | crontab -

echo ""
echo "Crontab entry installed:"
echo "  $CRON_LINE"
echo ""
echo "Verify with: crontab -l"
