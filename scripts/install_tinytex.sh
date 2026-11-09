#!/usr/bin/env bash
# Install TinyTeX (pdfLaTeX, no sudo) plus the packages Jake's resume template
# needs. Idempotent: re-running only adds missing packages. Used by CI
# (.github/workflows/*.yml) and works on macOS/Linux dev machines.
#
# Self-healing (AD-51): CI restores TinyTeX from a cache that can be weeks
# old. Once CTAN ships a newer tlmgr, every `tlmgr install` against the old
# copy dies with "tlmgr itself needs to be updated", and after a TeX Live
# release rollover the old tree cannot talk to the repository at all. So a
# failed install first updates tlmgr in place, and if that is not enough it
# throws the stale tree away and installs a fresh one.
set -euo pipefail

PACKAGES=(titlesec marvosym enumitem fancyhdr babel-english preprint)

case "$(uname -s)" in
  Darwin) ROOT="$HOME/Library/TinyTeX"; BIN="$ROOT/bin/universal-darwin" ;;
  *)      ROOT="$HOME/.TinyTeX";        BIN="$ROOT/bin/$(uname -m)-linux" ;;
esac

fresh_install() {
  rm -rf "$ROOT"
  curl -sL "https://yihui.org/tinytex/install-bin-unix.sh" | sh >/dev/null
}

install_packages() {
  "$BIN/tlmgr" install "${PACKAGES[@]}" >/dev/null 2>&1
}

if [ ! -x "$BIN/pdflatex" ]; then
  fresh_install
fi

if ! install_packages; then
  echo "tlmgr install failed; updating tlmgr itself and retrying."
  if ! { "$BIN/tlmgr" update --self >/dev/null 2>&1 && install_packages; }; then
    echo "TinyTeX is too old to update in place; reinstalling it."
    fresh_install
    # Last attempt prints tlmgr's own error if it still fails.
    "$BIN/tlmgr" install "${PACKAGES[@]}"
  fi
fi

if [ -n "${GITHUB_PATH:-}" ]; then
  echo "$BIN" >> "$GITHUB_PATH"
fi
"$BIN/pdflatex" --version | head -1
