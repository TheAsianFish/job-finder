#!/usr/bin/env bash
# Read the Claude Max usage meter (AD-42): one one-word Haiku call in
# stream-json, whose rate_limit_event carries the 5-hour and 7-day
# utilization. Usage: usage_probe.sh OUT. Never fails the caller: without a
# reading the governor runs a single project.
out="${1:?usage: usage_probe.sh OUT}"
if [ -z "${CLAUDE_CODE_OAUTH_TOKEN:-}" ]; then
  echo "usage probe: no CLAUDE_CODE_OAUTH_TOKEN; governor runs one project"
  : > "$out"; exit 0
fi
# Max plan only (AD-39): never let an API key bill this.
timeout 2m env -u ANTHROPIC_API_KEY -u ANTHROPIC_AUTH_TOKEN -u ANTHROPIC_BASE_URL \
  -u CLAUDE_CODE_USE_BEDROCK -u CLAUDE_CODE_USE_VERTEX -u CLAUDE_CODE_USE_FOUNDRY \
  claude -p "Reply with the single word: ok" --model haiku --max-turns 1 \
  --output-format stream-json --verbose > "$out" 2>/dev/null || true
grep -q '"rate_limit_event"' "$out" && echo "usage probe: meter read" \
  || echo "usage probe: no meter in the output; governor runs one project"
exit 0
