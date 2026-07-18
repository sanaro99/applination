#!/usr/bin/env bash
# setup_cron.sh — install a daily crontab entry for internship_bot.
# Run once. Re-running is safe (idempotent).
#
# Cost note: DeepSeek (the default LLM provider) bills ~50% less during its
# off-peak window, 16:30-00:30 GMT. The prompt below suggests the local
# equivalent of 20:00 GMT (mid-window) so the daily run lands inside off-peak;
# press Enter to accept it, or type your own time.

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

# Suggest the local equivalent of 20:00 GMT (mid off-peak): resolve 20:00 UTC to
# an epoch (GNU then BSD form), then render that instant in local time. If the
# platform's date can't do it, leave the suggestion empty.
SUG_EPOCH="$(date -d '20:00 UTC' +%s 2>/dev/null \
    || date -j -u -f '%H:%M' '20:00' +%s 2>/dev/null || true)"
SUGGESTED=""
if [ -n "$SUG_EPOCH" ]; then
    SUGGESTED="$(date -d "@${SUG_EPOCH}" +%H:%M 2>/dev/null \
        || date -r "${SUG_EPOCH}" +%H:%M 2>/dev/null || true)"
fi

if [ -n "$SUGGESTED" ]; then
    echo "Tip: DeepSeek off-peak is 16:30-00:30 GMT (~50% off). Suggested local time: ${SUGGESTED}."
    read -rp "What time should the bot run? (24h HH:MM, Enter for ${SUGGESTED}): " TIME_INPUT
    TIME_INPUT="${TIME_INPUT:-$SUGGESTED}"
else
    echo "Tip: DeepSeek off-peak is 16:30-00:30 GMT (~50% off) - pick a local time inside it."
    read -rp "What time should the bot run? (24h format, e.g. 08:00): " TIME_INPUT
fi

HOUR="${TIME_INPUT%%:*}"
MINUTE="${TIME_INPUT##*:}"

# Validate
if ! [[ "$HOUR" =~ ^[0-9]+$ ]] || ! [[ "$MINUTE" =~ ^[0-9]+$ ]]; then
    echo "Invalid time. Please use HH:MM format."
    exit 1
fi

# Informational: is the chosen local time inside DeepSeek's off-peak window?
# Parse HH:MM as local -> epoch, then render that absolute instant in UTC.
# (A bare `date -u -d "08:00"` parses the input AS UTC, so go via epoch.)
EPOCH="$(date -d "${HOUR}:${MINUTE}" +%s 2>/dev/null \
    || date -j -f '%H:%M' "${HOUR}:${MINUTE}" +%s 2>/dev/null || true)"
UTC_HHMM=""
if [ -n "$EPOCH" ]; then
    UTC_HHMM="$(date -u -d "@${EPOCH}" +%H%M 2>/dev/null \
        || date -u -r "${EPOCH}" +%H%M 2>/dev/null || true)"
fi
if [ -n "$UTC_HHMM" ]; then
    UTC_MINS=$(( 10#${UTC_HHMM:0:2} * 60 + 10#${UTC_HHMM:2:2} ))
    if [ "$UTC_MINS" -ge 990 ] || [ "$UTC_MINS" -le 30 ]; then
        echo "Off-peak   : inside DeepSeek's 16:30-00:30 GMT window (~50% off)."
    else
        echo "Note       : this time (${UTC_HHMM:0:2}:${UTC_HHMM:2:2} GMT) is outside DeepSeek off-peak - LLM calls bill at full price."
    fi
fi

CRON_LINE="${MINUTE} ${HOUR} * * * bash ${SCRIPT} >> ${REPO_DIR}/logs/cron.log 2>&1"

# Add only if not already present
( crontab -l 2>/dev/null | grep -v "internship_bot"; echo "$CRON_LINE" ) | crontab -

echo ""
echo "Crontab entry installed:"
echo "  $CRON_LINE"
echo ""
echo "Verify with: crontab -l"
