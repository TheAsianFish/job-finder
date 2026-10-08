"""Open a pull request against the private career repo without touching main.

Used for everything that needs Patrick's explicit approval before it can
influence a resume: bullet proposals (AD-31) and finished portfolio projects
(AD-32). Work happens in a temporary worktree branched from origin/main, so
the local clone's working tree (and any uncommitted scan output) is never
disturbed. Pushing uses the clone's own credentials (deploy key in CI); the
PR is created with `gh` and a token (CAREER_GH_TOKEN / GH_TOKEN) or gh's own
login locally.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path

GIT_AUTHOR = ("TheAsianFish", "jmchung2006@gmail.com")


def git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=False
    )


def repo_slug(repo: Path) -> str | None:
    url = git(repo, "remote", "get-url", "origin").stdout.strip()
    match = re.search(r"github\.com[:/]([^/]+/[^/.]+?)(?:\.git)?$", url)
    return match.group(1) if match else None


def gh_token(explicit: str | None = None) -> str | None:
    return explicit or os.environ.get("CAREER_GH_TOKEN") or os.environ.get("GH_TOKEN")


def open_private_pr(
    repo: Path,
    *,
    branch: str,
    title: str,
    body: str,
    message: str,
    write: Callable[[Path], None],
    token: str | None = None,
) -> str:
    """Branch from origin/main, let `write` edit the worktree, commit as
    TheAsianFish, push, open the PR. Returns its URL; raises RuntimeError
    with a short reason on any failure."""
    gh = shutil.which("gh")
    if gh is None or not (repo / ".git").exists():
        raise RuntimeError("gh CLI or the private git repo is not available")
    slug = repo_slug(repo)
    if slug is None:
        raise RuntimeError("private repo has no GitHub remote")
    fetch = git(repo, "fetch", "-q", "origin", "main")
    if fetch.returncode != 0:
        raise RuntimeError(f"fetch failed: {fetch.stderr.strip()[:150]}")
    with tempfile.TemporaryDirectory(prefix="private-pr-") as tmp:
        work = Path(tmp) / "wt"
        added = git(repo, "worktree", "add", "-q", "-B", branch, str(work), "origin/main")
        if added.returncode != 0:
            raise RuntimeError(f"worktree failed: {added.stderr.strip()[:150]}")
        try:
            write(work)
            git(work, "add", "-A")
            name, email = GIT_AUTHOR
            commit = git(
                work, "-c", f"user.name={name}", "-c", f"user.email={email}",
                "commit", "-q", "-m", message,
            )  # fmt: skip
            if commit.returncode != 0:
                raise RuntimeError(f"commit failed: {commit.stderr.strip()[:150]}")
            push = git(work, "push", "-q", "-f", "origin", f"HEAD:refs/heads/{branch}")
            if push.returncode != 0:
                raise RuntimeError(f"push failed: {push.stderr.strip()[:150]}")
        finally:
            git(repo, "worktree", "remove", "--force", str(work))
            git(repo, "branch", "-D", branch)
    env = dict(os.environ)
    token = gh_token(token)
    if token:
        env["GH_TOKEN"] = token
    created = subprocess.run(
        [gh, "pr", "create", "--repo", slug, "--base", "main", "--head", branch,
         "--title", title[:120], "--body", body],
        capture_output=True, text=True, check=False, env=env,
    )  # fmt: skip
    if created.returncode != 0:
        raise RuntimeError(f"gh pr create failed: {created.stderr.strip()[:150]}")
    return created.stdout.strip().splitlines()[-1]
