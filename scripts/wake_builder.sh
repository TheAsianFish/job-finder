#!/usr/bin/env bash
# Start the project builder as soon as it has work (AD-35). Run from the scan
# chain every ~10 minutes. Needs GH_TOKEN (dispatch, this repo), AGENT_GH_TOKEN
# (read the project repo) and the private repo at resume/private.
#
# Guards: nothing while a builder run is queued or running; nothing for 3 hours
# after a failed run, so a broken stage can't loop; a failed decision starts
# a builder run whose failure is reported to #projects. Prints the stage only,
# never private context.
set -euo pipefail

busy=$(gh run list --workflow projects.yml --limit 20 --json status \
  --jq '[.[] | select(.status != "completed")] | length')
if [ "$busy" != "0" ]; then echo "builder already running"; exit 0; fi

last=$(gh run list --workflow projects.yml --limit 1 --json conclusion,createdAt \
  --jq '.[0] | "\(.conclusion) \(.createdAt)"' 2>/dev/null || true)
if [[ "$last" == failure* ]]; then
  age=$(( $(date +%s) - $(date -d "${last#* }" +%s) ))
  if [ "$age" -lt 10800 ]; then echo "last builder run failed ${age}s ago; leaving it to the schedule"; exit 0; fi
fi

ctx="${RUNNER_TEMP:-/tmp}/builder-wake.json"
if ! uv run opportunity-radar projects step --dry-run --no-push --out "$ctx" >/dev/null; then
  # Surface the error through a real builder run, which reports it to
  # #projects; the 3-hour guard above keeps that from repeating every scan.
  gh workflow run projects.yml -f action=auto
  echo "builder decision failed; started a builder run to report it"
  exit 0
fi
stage=$(jq -r .stage "$ctx")
case "$stage" in
  create|plan|build|address|merge|finish) ;;
  *) echo "builder: nothing to do (${stage})"; exit 0 ;;
esac

gh workflow run projects.yml -f action=auto -f project="$(jq -r .slug "$ctx")"
echo "builder started (${stage})"
title=$(jq -r .project.title "$ctx")
case "$stage" in
  build)   what="starting milestone $(( $(jq -r .milestones_done "$ctx") + 1 )) of $(jq -r .milestones_total "$ctx"): $(jq -r .milestone "$ctx")" ;;
  address) what="addressing your PR comments" ;;
  merge)   what="autopilot: merging the reviewed PR" ;;
  finish)  what="all milestones merged; preparing the release and resume entry" ;;
  *)       what="starting the ${stage} stage" ;;
esac
printf '**%s**: %s.\n' "$title" "$what" > "${RUNNER_TEMP:-/tmp}/wake.md"
uv run opportunity-radar notify markdown "${RUNNER_TEMP:-/tmp}/wake.md" --title "▶️ Project builder" --channel projects
