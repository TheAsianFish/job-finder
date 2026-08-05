#!/usr/bin/env bash
# One-shot macOS setup for Opportunity Radar.
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

if ! command -v uv >/dev/null; then
  if command -v brew >/dev/null; then
    echo "Installing uv via Homebrew..."
    brew install uv
  else
    echo "error: install Homebrew (https://brew.sh) or uv (https://docs.astral.sh/uv) first" >&2
    exit 1
  fi
fi

echo "Installing dependencies..."
uv sync

echo "Initializing config and database..."
uv run opportunity-radar init

echo
echo "Setup complete. Next steps:"
echo "  1. Edit .env and set DISCORD_WEBHOOK_URL"
echo "  2. uv run opportunity-radar doctor"
echo "  3. uv run opportunity-radar notify test"
echo "  4. uv run opportunity-radar baseline"
echo "  5. scripts/install_launchd.sh   # run the daemon at login"
