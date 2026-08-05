#!/usr/bin/env bash
# Install the Opportunity Radar daemon as a macOS launchd agent.
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UV_PATH="$(command -v uv || true)"
if [[ -z "$UV_PATH" ]]; then
  echo "error: uv not found on PATH. Install with: brew install uv" >&2
  exit 1
fi

LABEL="com.patrick.opportunity-radar"
LOG_DIR="$HOME/Library/Logs/OpportunityRadar"
PLIST_DEST="$HOME/Library/LaunchAgents/$LABEL.plist"
TEMPLATE="$PROJECT_DIR/launchd/$LABEL.plist.template"

mkdir -p "$LOG_DIR" "$HOME/Library/LaunchAgents"

sed -e "s|__UV_PATH__|$UV_PATH|g" \
    -e "s|__PROJECT_DIR__|$PROJECT_DIR|g" \
    -e "s|__LOG_DIR__|$LOG_DIR|g" \
    "$TEMPLATE" > "$PLIST_DEST"

# Reload cleanly if already installed.
launchctl bootout "gui/$(id -u)" "$PLIST_DEST" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST_DEST"

echo "Installed and started: $LABEL"
echo "  logs:      $LOG_DIR/daemon.log"
echo "  stop:      launchctl bootout gui/$(id -u) $PLIST_DEST"
echo "  uninstall: scripts/uninstall_launchd.sh"
