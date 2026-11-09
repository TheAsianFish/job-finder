#!/usr/bin/env bash
# Start the next cloud scan in the chain and make sure it really starts (AD-51).
#
# The scan chain (AD-24) is only as strong as its weakest dispatch: a single
# HTTP 500/502 from the dispatch API, or a dispatched run that dies at startup
# before any job runs, used to stop scanning until GitHub's unreliable cron
# happened to fire (gaps of 3-7 hours in Oct/Nov 2026). So this script
#   1. paces runs MIN_GAP seconds apart (start to start),
#   2. retries the dispatch on transient API errors,
#   3. watches for the dispatched run and dispatches again when it ends
#      without ever starting a job.
#
# Env: GH_REPO, RUN_ID (this run, never mistaken for the successor), and
# optionally WORKFLOW (scan.yml), REF (main), MIN_GAP (600), RUN_STARTED
# (epoch seconds), CHAIN_RETRY_DELAYS ("10 30 60 120 240"),
# CHAIN_POLL_INTERVAL (15), CHAIN_POLL_LIMIT (24), CHAIN_MAX_STARTS (3).
set -uo pipefail

: "${GH_REPO:?GH_REPO is required}"
: "${RUN_ID:?RUN_ID is required}"
WORKFLOW=${WORKFLOW:-scan.yml}
REF=${REF:-main}
MIN_GAP=${MIN_GAP:-600}
RUN_STARTED=${RUN_STARTED:-$(date +%s)}
read -r -a DELAYS <<< "${CHAIN_RETRY_DELAYS:-10 30 60 120 240}"
POLL_INTERVAL=${CHAIN_POLL_INTERVAL:-15}
POLL_LIMIT=${CHAIN_POLL_LIMIT:-24}
MAX_STARTS=${CHAIN_MAX_STARTS:-3}

iso_utc() {  # epoch seconds -> 2026-11-09T18:07:19Z (GNU or BSD date)
  date -u -d "@$1" +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date -u -r "$1" +%Y-%m-%dT%H:%M:%SZ
}

dispatch() {
  local attempt=0
  while true; do
    if gh workflow run "$WORKFLOW" --ref "$REF"; then
      return 0
    fi
    if [ "$attempt" -ge "${#DELAYS[@]}" ]; then
      return 1
    fi
    echo "Dispatch failed; retrying in ${DELAYS[$attempt]}s."
    sleep "${DELAYS[$attempt]}"
    attempt=$((attempt + 1))
  done
}

# "<id> <status> <conclusion>" of the newest dispatched run created since $1
# that is not this run; empty when none is visible yet.
successor() {
  gh api "repos/$GH_REPO/actions/workflows/$WORKFLOW/runs?event=workflow_dispatch&per_page=10" \
    --jq "[.workflow_runs[] | select(.id != $RUN_ID and .created_at >= \"$1\")]
          | sort_by(.created_at) | last
          | if . == null then \"\" else \"\(.id) \(.status) \(.conclusion)\" end" 2>/dev/null
}

job_count() {
  gh api "repos/$GH_REPO/actions/runs/$1/jobs" --jq '.total_count' 2>/dev/null || echo "?"
}

elapsed=$(( $(date +%s) - RUN_STARTED ))
wait=$(( MIN_GAP - elapsed ))
if [ "$wait" -gt 0 ]; then
  echo "Run took ${elapsed}s; next scan in ${wait}s."
  sleep "$wait"
fi

for start in $(seq 1 "$MAX_STARTS"); do
  # A few seconds of slack for clock skew between this runner and the API.
  since=$(iso_utc $(( $(date +%s) - 10 )))
  if ! dispatch; then
    echo "::error::Could not dispatch the next scan after ${#DELAYS[@]} retries."
    exit 1
  fi
  echo "Dispatched the next scan (attempt $start); waiting for it to start."
  for _ in $(seq 1 "$POLL_LIMIT"); do
    sleep "$POLL_INTERVAL"
    read -r id status conclusion <<< "$(successor "$since")"
    [ -n "${id:-}" ] || continue
    case "$status" in
      in_progress)
        echo "Next scan $id is running."
        exit 0
        ;;
      completed)
        if [ "$conclusion" = "cancelled" ]; then
          # Replaced by a newer pending run (cron or another dispatch),
          # which carries the chain on.
          echo "Next scan $id was superseded by a newer run."
          exit 0
        fi
        jobs=$(job_count "$id")
        if [ "$jobs" = "0" ]; then
          echo "::warning::Next scan $id ended ($conclusion) before any job started; dispatching again."
          continue 2
        fi
        echo "Next scan $id already finished ($conclusion)."
        exit 0
        ;;
    esac
  done
  if [ -n "${id:-}" ]; then
    echo "Next scan $id is still $status; GitHub will start it."
    exit 0
  fi
  echo "::warning::No dispatched run appeared; dispatching again."
done

echo "::error::The next scan never started after $MAX_STARTS dispatches."
exit 1
