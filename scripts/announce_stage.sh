#!/usr/bin/env bash
# Tell #projects what this builder run is starting (AD-35, moved here from
# wake_builder.sh on 2026-10-17): called by the control job after the usage
# governor decided, so a run the governor holds posts nothing.
# Usage: announce_stage.sh CONTEXT_JSON. Never fails the run.
ctx="${1:?usage: announce_stage.sh CONTEXT_JSON}"
stage=$(jq -r .stage "$ctx")
title=$(jq -r '.project.title // empty' "$ctx")
case "$stage" in
  plan)    what="planning the project" ;;
  build)   what="starting milestone $(( $(jq -r .milestones_done "$ctx") + 1 )) of $(jq -r .milestones_total "$ctx"): $(jq -r .milestone "$ctx")" ;;
  address) reason=$(jq -r .reason "$ctx")
           if [[ "$reason" == "CI failing"* ]]; then what="CI is failing on the open PR; fixing it (${reason#CI failing; })"
           else what="addressing your PR comments"; fi ;;
  merged)  what="autopilot merged the reviewed PR" ;;
  evolve)  what="plan done; checking whether the results justify more milestones" ;;
  finish)  what="all milestones merged; preparing the release and resume entry" ;;
  *)       exit 0 ;;  # wait, idle, rerun (posted separately): nothing to announce
esac
[ -n "$title" ] || exit 0
printf '**%s**: %s.\n' "$title" "$what" > "${RUNNER_TEMP:-/tmp}/announce.md"
uv run opportunity-radar notify markdown "${RUNNER_TEMP:-/tmp}/announce.md" \
  --title "▶️ Project builder" --channel projects || true
