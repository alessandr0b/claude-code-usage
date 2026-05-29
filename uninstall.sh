#!/usr/bin/env bash
#
# uninstall.sh — remove the scheduled claude-code-usage job.
# Leaves any already-generated reports in place.
#
set -euo pipefail

LABEL="com.claude-code-usage.monthly"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="$SCRIPT_DIR/claude_usage_report.py"

case "$(uname -s)" in
  Darwin)
    PLIST_DST="$HOME/Library/LaunchAgents/$LABEL.plist"
    if [[ -f "$PLIST_DST" ]]; then
        launchctl unload "$PLIST_DST" 2>/dev/null || true
        rm -f "$PLIST_DST"
        echo "✓ Removed launchd job '$LABEL'"
    else
        echo "Nothing to remove (no plist at $PLIST_DST)."
    fi
    ;;

  Linux)
    if crontab -l 2>/dev/null | grep -qF "$SCRIPT"; then
        TMP="$(mktemp)"
        crontab -l 2>/dev/null | grep -vF "$SCRIPT" > "$TMP" || true
        crontab "$TMP"
        rm -f "$TMP"
        echo "✓ Removed cron job"
    else
        echo "Nothing to remove (no matching crontab entry)."
    fi
    ;;

  *)
    echo "error: unsupported OS '$(uname -s)'." >&2
    exit 1
    ;;
esac
