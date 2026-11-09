"""scripts/chain_scan.sh: the scan chain survives API errors and dead runs (AD-51).

A fake `gh` on PATH stands in for the GitHub CLI: it fails the first N
dispatches, then answers the successor lookup with whatever state the test
scripted for the current dispatch count.
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "chain_scan.sh"

FAKE_GH = """#!/usr/bin/env bash
state="$FAKE_STATE"
if [ "$1" = "workflow" ] && [ "$2" = "run" ]; then
  fails=$(cat "$state/fails")
  if [ "$fails" -gt 0 ]; then
    echo $((fails - 1)) > "$state/fails"
    echo "could not create workflow dispatch event: HTTP 502" >&2
    exit 1
  fi
  echo x >> "$state/dispatches"
  exit 0
fi
if [ "$1" = "api" ]; then
  n=$(wc -l < "$state/dispatches" | tr -d ' ')
  case "$2" in
    */jobs) cat "$state/jobs_$n" 2>/dev/null || echo 1 ;;
    *) cat "$state/run_$n" 2>/dev/null || echo "" ;;
  esac
  exit 0
fi
exit 2
"""


def _run(tmp_path: Path, *, fails: int, runs: dict[int, str], jobs: dict[int, str] | None = None):
    bin_dir = tmp_path / "bin"
    state = tmp_path / "state"
    bin_dir.mkdir(parents=True)
    state.mkdir()
    gh = bin_dir / "gh"
    gh.write_text(FAKE_GH)
    gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
    (state / "fails").write_text(str(fails))
    (state / "dispatches").write_text("")
    for n, line in runs.items():
        (state / f"run_{n}").write_text(line + "\n")
    for n, count in (jobs or {}).items():
        (state / f"jobs_{n}").write_text(count + "\n")
    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "FAKE_STATE": str(state),
        "GH_REPO": "owner/repo",
        "RUN_ID": "100",
        "MIN_GAP": "0",
        "CHAIN_RETRY_DELAYS": "0 0 0",
        "CHAIN_POLL_INTERVAL": "0",
        "CHAIN_POLL_LIMIT": "3",
        "CHAIN_MAX_STARTS": "3",
    }
    result = subprocess.run(
        ["bash", str(SCRIPT)], env=env, capture_output=True, text=True, timeout=60
    )
    dispatched = len((state / "dispatches").read_text().splitlines())
    return result, dispatched


def test_transient_dispatch_errors_are_retried(tmp_path: Path) -> None:
    result, dispatched = _run(tmp_path, fails=2, runs={1: "200 in_progress "})
    assert result.returncode == 0, result.stdout + result.stderr
    assert dispatched == 1
    assert "retrying" in result.stdout
    assert "200 is running" in result.stdout


def test_run_that_dies_before_any_job_is_dispatched_again(tmp_path: Path) -> None:
    result, dispatched = _run(
        tmp_path,
        fails=0,
        runs={1: "200 completed failure", 2: "201 in_progress "},
        jobs={1: "0"},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert dispatched == 2
    assert "before any job started" in result.stdout


def test_finished_or_superseded_successor_ends_quietly(tmp_path: Path) -> None:
    result, dispatched = _run(tmp_path, fails=0, runs={1: "200 completed failure"}, jobs={1: "1"})
    assert result.returncode == 0 and dispatched == 1
    result, dispatched = _run(tmp_path / "b", fails=0, runs={1: "200 completed cancelled"})
    assert result.returncode == 0 and dispatched == 1


def test_queued_successor_is_left_to_github(tmp_path: Path) -> None:
    result, dispatched = _run(tmp_path, fails=0, runs={1: "200 queued "})
    assert result.returncode == 0 and dispatched == 1
    assert "still queued" in result.stdout


def test_persistent_dispatch_failure_fails_loudly(tmp_path: Path) -> None:
    result, dispatched = _run(tmp_path, fails=99, runs={})
    assert result.returncode == 1
    assert dispatched == 0
    assert "Could not dispatch" in result.stdout
