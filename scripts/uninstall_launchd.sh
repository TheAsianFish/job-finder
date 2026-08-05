#!/usr/bin/env bash
# Remove the Opportunity Radar launchd agent.
set -euo pipefail

LABEL="com.patrick.opportunity-radar"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

launchctl bootout "gui/$(id -u)" "$PLIST" 2>/dev/null || true
rm -f "$PLIST"
echo "Uninstalled $LABEL (logs left in ~/Library/Logs/OpportunityRadar)."
