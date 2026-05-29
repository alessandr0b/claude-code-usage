#!/usr/bin/env bash
#
# install.sh — schedule claude-code-usage to regenerate monthly.
#   macOS  -> launchd  (~/Library/LaunchAgents)
#   Linux  -> cron     (user crontab)
#
# Usage:  ./install.sh [OUTPUT_DIR]
#   OUTPUT_DIR defaults to ~/claude-code-usage-reports
#
set -euo pipefail

LABEL="com.claude-code-usage.monthly"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="$SCRIPT_DIR/claude_usage_report.py"
OUTDIR="${1:-$HOME/claude-code-usage-reports}"

PYTHON="$(command -v python3 || true)"
if [[ -z "$PYTHON" ]]; then
    echo "error: python3 not found on PATH." >&2
    exit 1
fi
if [[ ! -f "$SCRIPT" ]]; then
    echo "error: cannot find $SCRIPT" >&2
    exit 1
fi

mkdir -p "$OUTDIR"

# Build a PATH that includes wherever npx lives, so `ccusage` works under launchd/cron.
NPX_DIR=""
if command -v npx >/dev/null 2>&1; then
    NPX_DIR="$(dirname "$(command -v npx)")"
fi
JOB_PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin"
[[ -n "$NPX_DIR" ]] && JOB_PATH="$NPX_DIR:$JOB_PATH"

case "$(uname -s)" in
  Darwin)
    PLIST_SRC="$SCRIPT_DIR/templates/com.claude-code-usage.monthly.plist"
    PLIST_DST="$HOME/Library/LaunchAgents/$LABEL.plist"
    mkdir -p "$HOME/Library/LaunchAgents"

    sed -e "s|__PYTHON__|$PYTHON|g" \
        -e "s|__SCRIPT__|$SCRIPT|g" \
        -e "s|__OUTDIR__|$OUTDIR|g" \
        -e "s|__PATH__|$JOB_PATH|g" \
        "$PLIST_SRC" > "$PLIST_DST"

    # Reload idempotently (ignore "not loaded" on first run).
    launchctl unload "$PLIST_DST" 2>/dev/null || true
    launchctl load  "$PLIST_DST"

    echo "✓ Installed launchd job '$LABEL'"
    echo "  plist:   $PLIST_DST"
    echo "  reports: $OUTDIR"
    echo "  runs:    1st of each month at 09:00"
    echo
    echo "Test it now with:  launchctl start $LABEL"
    ;;

  Linux)
    CRON_LINE="0 9 1 * * \"$PYTHON\" \"$SCRIPT\" --out-dir \"$OUTDIR\" >> \"$OUTDIR/.cron.log\" 2>&1"
    # Replace any existing entry for this script, keep everything else.
    TMP="$(mktemp)"
    crontab -l 2>/dev/null | grep -vF "$SCRIPT" > "$TMP" || true
    echo "$CRON_LINE" >> "$TMP"
    crontab "$TMP"
    rm -f "$TMP"

    echo "✓ Installed cron job"
    echo "  entry:   $CRON_LINE"
    echo "  reports: $OUTDIR"
    echo "  runs:    1st of each month at 09:00"
    ;;

  *)
    echo "error: unsupported OS '$(uname -s)'. Run the script manually or add your own scheduler." >&2
    exit 1
    ;;
esac
