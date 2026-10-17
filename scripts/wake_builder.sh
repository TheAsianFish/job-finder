#!/usr/bin/env bash
# Start the project builder as soon as it has work (AD-35). Run from the scan
# chain every ~10 minutes. Needs GH_TOKEN (dispatch, this repo), AGENT_GH_TOKEN
# (read the project repo) and the private repo at resume/private.
#
# Guards: nothing while a builder run is queued or running; nothing for 3 hours
# after a failed run, so a broken stage can't loop; nothing for 30 minutes
# after a run that only decided (usage governor holding the work); a failed
# decision starts a builder run whose failure is reported to #projects.
# Prints the stage only, never private context; posts nothing to Discord.
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

# The dry run below can't see the usage meter, so it may report work the
# governor will hold. After a run that did nothing but decide (only the
# control job ran), wait 30 minutes before trying again, unless it merged a
# PR (the next milestone should start right away).
read -r last_id last_done < <(gh run list --workflow projects.yml --limit 1 \
  --json databaseId,updatedAt --jq '.[0] | "\(.databaseId) \(.updatedAt)"' 2>/dev/null || echo "")
if [ -n "${last_id:-}" ]; then
  worked=$(gh run view "$last_id" --json jobs \
    --jq '[.jobs[] | select(.name != "control" and .conclusion != "skipped")] | length' 2>/dev/null || echo 1)
  quiet=$(( $(date +%s) - $(date -d "$last_done" +%s) ))
  if [ "$worked" = "0" ] && [ "$quiet" -lt 1800 ]; then
    control=$(gh run view "$last_id" --json jobs --jq '.jobs[] | select(.name == "control") | .databaseId')
    if ! gh api "repos/${GH_REPO}/actions/jobs/${control}/logs" 2>/dev/null | grep -q "stage=merged"; then
      echo "last builder run had nothing to start ${quiet}s ago; checking again later"; exit 0
    fi
  fi
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
  create|plan|build|address|evolve|merge|finish|rerun) ;;
  *) echo "builder: nothing to do (${stage})"; exit 0 ;;
esac

gh workflow run projects.yml -f action=auto -f project="$(jq -r .slug "$ctx")"
# The builder run announces its stage to #projects itself, once the usage
# governor has let it start (scripts/announce_stage.sh): announcing here
# posted every 10 minutes while the governor held the work (2026-10-17).
echo "builder started (${stage})"
