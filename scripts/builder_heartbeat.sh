#!/usr/bin/env bash
# Progress pings to #projects while a builder session runs (AD-36), so Patrick
# can tell "working" from "stuck" without logs (they print stats only).
#
#   builder_heartbeat.sh <label> <interval-seconds>   (run in the background,
#   from the project checkout; reads HEARTBEAT_WEBHOOK, TITLE)
#
# Every interval: minutes elapsed, commits on the branch, last commit subject,
# files touched in the last interval. Flags no activity for two intervals.
# Never fails the build; agent sessions run without HEARTBEAT_WEBHOOK.
set -u
label="$1"; every="${2:-1200}"
[ -n "${HEARTBEAT_WEBHOOK:-}" ] || exit 0
start=$(date +%s); idle=0
while sleep "$every"; do
  mins=$(( ($(date +%s) - start) / 60 ))
  commits=$(git rev-list --count origin/main..HEAD 2>/dev/null || echo 0)
  last=$(git log -1 --format=%s origin/main..HEAD 2>/dev/null | cut -c1-90)
  touched=$(find . -path ./.git -prune -o -type f -newermt "-${every} seconds" -print 2>/dev/null | wc -l | tr -d ' ')
  if [ "$touched" = "0" ]; then idle=$((idle + 1)); else idle=0; fi
  status="working"
  [ "$idle" -ge 2 ] && status="⚠️ no file changes for $(( idle * every / 60 )) min (may be stuck; the stage times out on its own)"
  text="⏱️ **${TITLE:-project}** ${label}: ${mins} min, ${commits} commit(s)${last:+, latest: \"${last}\"}, ${touched} file(s) changed recently. ${status}."
  jq -n --arg c "$text" '{content: $c}' \
    | curl -s -o /dev/null -X POST -H "Content-Type: application/json" -d @- "$HEARTBEAT_WEBHOOK" || true
done
