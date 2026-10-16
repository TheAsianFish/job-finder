#!/usr/bin/env bash
# Pass private builder data between jobs without printing it (AD-43).
#
# This repo is public and GitHub prints every step's env values in its log,
# so the run context (hub, skills) and the session outputs (resume entry,
# talk tracks, study notes) travel between jobs encrypted with the
# PAYLOAD_KEY secret: only ciphertext appears in outputs, env and logs.
#
#   seal.sh seal DIR   tar + gzip + AES-256 DIR, print one base64 line
#   seal.sh open DIR   read that line on stdin, unpack it into DIR
set -euo pipefail
mode="${1:?usage: seal.sh seal|open DIR}"; dir="${2:?usage: seal.sh seal|open DIR}"
if [ -z "${PAYLOAD_KEY:-}" ]; then
  echo "seal.sh: PAYLOAD_KEY is not set" >&2; exit 1
fi
cipher=(openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -md sha256 -pass env:PAYLOAD_KEY)
case "$mode" in
  seal) tar -czf - -C "$dir" . | "${cipher[@]}" -salt | base64 | tr -d '\n' ;;
  open) mkdir -p "$dir"; tr -d '[:space:]' | base64 -d | "${cipher[@]}" -d | tar -xzf - -C "$dir" ;;
  *) echo "usage: seal.sh seal|open DIR" >&2; exit 2 ;;
esac
