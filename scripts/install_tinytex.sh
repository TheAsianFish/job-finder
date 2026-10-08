#!/usr/bin/env bash
# Install TinyTeX (pdfLaTeX, no sudo) plus the packages Jake's resume template
# needs. Idempotent: re-running only adds missing packages. Used by CI
# (.github/workflows/*.yml) and works on macOS/Linux dev machines.
set -euo pipefail

PACKAGES=(titlesec marvosym enumitem fancyhdr babel-english preprint)

case "$(uname -s)" in
  Darwin) BIN="$HOME/Library/TinyTeX/bin/universal-darwin" ;;
  *)      BIN="$HOME/.TinyTeX/bin/$(uname -m)-linux" ;;
esac

if [ ! -x "$BIN/pdflatex" ]; then
  curl -sL "https://yihui.org/tinytex/install-bin-unix.sh" | sh >/dev/null
fi
"$BIN/tlmgr" install "${PACKAGES[@]}" >/dev/null 2>&1 || "$BIN/tlmgr" install "${PACKAGES[@]}"

if [ -n "${GITHUB_PATH:-}" ]; then
  echo "$BIN" >> "$GITHUB_PATH"
fi
"$BIN/pdflatex" --version | head -1
