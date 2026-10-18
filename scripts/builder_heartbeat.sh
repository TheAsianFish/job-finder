#!/usr/bin/env bash
# Stuck-session warning for #projects while a builder session runs (AD-36).
# Each run already announces its start (announce_stage.sh) and its result (PR,
# review, failure), so a working session stays silent; this posts only when
# no file has changed for two intervals, once per quiet streak.
#
#   builder_heartbeat.sh <label> <interval-seconds>   (run in the background,
#   from the project checkout; reads HEARTBEAT_WEBHOOK, TITLE)
#
# Never fails the build; agent sessions run without HEARTBEAT_WEBHOOK.
set -u
label="$1"; every="${2:-1200}"
[ -n "${HEARTBEAT_WEBHOOK:-}" ] || exit 0
start=$(date +%s); idle=0
while sleep "$every"; do
  touched=$(find . -path ./.git -prune -o -type f -newermt "-${every} seconds" -print 2>/dev/null | wc -l | tr -d ' ')
  if [ "$touched" = "0" ]; then idle=$((idle + 1)); else idle=0; fi
  [ "$idle" -eq 2 ] || continue
  mins=$(( ($(date +%s) - start) / 60 ))
  commits=$(git rev-list --count origin/main..HEAD 2>/dev/null || echo 0)
  text="⚠️ **${TITLE:-project}** ${label}: no file changes for $(( idle * every / 60 )) min (${mins} min in, ${commits} commit(s)); may be stuck, the stage times out on its own."
  jq -n --arg c "$text" '{content: $c}' \
    | curl -s -o /dev/null -X POST -H "Content-Type: application/json" -d @- "$HEARTBEAT_WEBHOOK" || true
done
