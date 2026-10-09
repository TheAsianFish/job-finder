#!/usr/bin/env bash
# Run one Claude Code session for the project builder (AD-32).
#
#   project_agent.sh <model> <prompt-file> <minutes> <max-turns> <label>
#
# Runs in the project checkout (cwd) with permissions bypassed: the runner is
# an ephemeral VM and the only secret in the environment is
# CLAUDE_CODE_OAUTH_TOKEN (the GitHub token is never exported to this step,
# and the clone's remote carries no credentials). Fable falls back to Opus if
# it is unavailable. Workflow logs are public, so only run statistics are
# printed, never the model's output.
set -uo pipefail

model="$1"; prompt="$2"; minutes="$3"; turns="$4"; label="$5"
log="${RUNNER_TEMP:-/tmp}/claude-${label}.json"

run() {
  timeout "${minutes}m" env -u HEARTBEAT_WEBHOOK claude -p "$(cat "$prompt")" \
    --model "$1" \
    --permission-mode bypassPermissions \
    --max-turns "$turns" \
    --output-format json > "$log" 2> "${log}.err"
}

# Progress pings to #projects every 20 minutes (AD-36).
bash "$(dirname "$0")/builder_heartbeat.sh" "$label" "${HEARTBEAT_SECONDS:-1200}" &
heartbeat=$!
trap 'kill $heartbeat 2>/dev/null' EXIT

run "$model"
status=$?
if [ $status -ne 0 ] && [ "$model" = "fable" ]; then
  echo "${label}: fable unavailable or failed (exit ${status}); retrying with opus"
  run opus
  status=$?
fi

python3 - "$log" "$label" "$status" <<'EOF'
import json, sys
path, label, status = sys.argv[1], sys.argv[2], sys.argv[3]
try:
    data = json.load(open(path))
except Exception:
    print(f"{label}: exit {status}, no JSON result (timeout or crash)")
    sys.exit(0)
models = ",".join(sorted((data.get("modelUsage") or {}).keys()))
print(
    f"{label}: exit {status}, error={data.get('is_error')}, turns={data.get('num_turns')}, "
    f"minutes={round((data.get('duration_ms') or 0) / 60000, 1)}, models={models}"
)
EOF
exit $status
