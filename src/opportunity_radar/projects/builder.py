"""What the project builder should do next, from the project repo's state.

The workflow (.github/workflows/projects.yml) calls `projects step`, which
reads the project's GitHub repo through `gh` and returns one stage:

    create   repo missing: create it (private), then plan
    plan     no PLAN.md on main: Fable writes the plan as a PR
    address  an open agent PR has feedback newer than the agent's last
             commit/reply: Opus addresses it on that branch
    merge    autopilot only: the open PR passed review + CI and has sat
             12h without feedback: merge it
    wait     an open agent PR awaits Patrick: do nothing (no compute spent)
    build    next unchecked milestone in PLAN.md: Opus builds it, Fable
             reviews it, one PR
    finish   every milestone merged: write the resume entry from measured
             results, proposed to the private repo as a PR
    idle     nothing to do

Only one agent PR is open per project at a time, so the pace follows
Patrick's reviews unless he opts into autopilot.
"""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from opportunity_radar.projects.portfolio import Project

# Everything visible in a project repo reads as Patrick's own work (AD-34):
# neutral branch names and hidden markers, legacy ones still recognised.
WORK_BRANCH = "dev/"
BRANCH_PREFIXES = (WORK_BRANCH, "agent/")
AGENT_MARK = "<!-- ack -->"  # on the builder's replies to review comments
_REPLY_MARKS = (AGENT_MARK, "<!-- project-builder -->")
REVIEW_PASS = "<!-- review: pass -->"
_PASS_MARKS = (REVIEW_PASS, "<!-- fable-review: pass -->")
AUTOPILOT_QUIET = timedelta(hours=12)
_CHECKBOX_RE = re.compile(r"^\s*[-*]\s*\[( |x|X)\]\s*(.+?)\s*$")

Gh = Callable[[list[str]], str]  # gh args -> stdout; raises GhError on failure


class GhError(RuntimeError):
    pass


def gh_cli(token: str | None = None) -> Gh:
    import os

    env = dict(os.environ)
    if token:
        env["GH_TOKEN"] = token

    def run(args: list[str]) -> str:
        proc = subprocess.run(["gh", *args], capture_output=True, text=True, check=False, env=env)
        if proc.returncode != 0:
            raise GhError(proc.stderr.strip()[:200] or f"gh exited {proc.returncode}")
        return proc.stdout

    return run


@dataclass
class Milestone:
    title: str
    done: bool


@dataclass
class PullRequest:
    number: int
    url: str
    branch: str
    created: datetime
    body: str = ""
    feedback: list[str] = field(default_factory=list)  # Patrick's unaddressed comments
    checks_green: bool = False
    last_activity: datetime | None = None


@dataclass
class RepoState:
    exists: bool
    plan: str | None = None
    pr: PullRequest | None = None

    @property
    def milestones(self) -> list[Milestone]:
        return parse_milestones(self.plan or "")


@dataclass
class Stage:
    kind: str
    milestone: str | None = None
    pr: PullRequest | None = None
    reason: str = ""


def parse_milestones(plan: str) -> list[Milestone]:
    """Checkboxes under the first '## ...Milestones' heading of PLAN.md."""
    out: list[Milestone] = []
    inside = False
    for line in plan.splitlines():
        if line.startswith("## "):
            if inside:
                break
            inside = "milestone" in line.lower()
            continue
        if inside:
            match = _CHECKBOX_RE.match(line)
            if match:
                out.append(Milestone(title=match.group(2), done=match.group(1) != " "))
    return out


def _when(text: str | None) -> datetime | None:
    if not text:
        return None
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def _json(gh: Gh, args: list[str]):
    return json.loads(gh(args) or "null")


def read_pr(repo: str, raw: dict, gh: Gh) -> PullRequest:
    number = int(raw["number"])
    view = _json(
        gh, ["pr", "view", str(number), "--repo", repo, "--json", "commits,statusCheckRollup,body"]
    )
    commits = view.get("commits") or []
    last_commit = _when(commits[-1].get("committedDate")) if commits else None
    checks = view.get("statusCheckRollup") or []
    green = bool(checks) and all(
        (c.get("conclusion") or c.get("state") or "").upper() in ("SUCCESS", "NEUTRAL", "SKIPPED")
        for c in checks
    )
    notes: list[tuple[datetime, str, bool]] = []  # (when, body, by_agent)
    for path, when_key in (
        (f"repos/{repo}/issues/{number}/comments", "created_at"),
        (f"repos/{repo}/pulls/{number}/comments", "created_at"),
        (f"repos/{repo}/pulls/{number}/reviews", "submitted_at"),
    ):
        for item in _json(gh, ["api", path, "--paginate"]) or []:
            body = (item.get("body") or "").strip()
            when = _when(item.get(when_key))
            if body and when:
                notes.append((when, body, any(m in body for m in _REPLY_MARKS)))
    agent_times = [w for w, _, by_agent in notes if by_agent]
    cutoff = max([t for t in [last_commit, *agent_times] if t], default=None)
    feedback = [
        body
        for when, body, by_agent in sorted(notes)
        if not by_agent and (cutoff is None or when > cutoff)
    ]
    activity = max([t for t in [cutoff, *(w for w, _, _ in notes)] if t], default=None)
    return PullRequest(
        number=number,
        url=str(raw.get("url") or ""),
        branch=str(raw.get("headRefName") or ""),
        created=_when(raw.get("createdAt")) or datetime.now(UTC),
        body=str(view.get("body") or ""),
        feedback=feedback,
        checks_green=green,
        last_activity=activity,
    )


def read_state(repo: str, gh: Gh) -> RepoState:
    try:
        gh(["repo", "view", repo, "--json", "name"])
    except GhError:
        return RepoState(exists=False)
    try:
        plan: str | None = gh(
            ["api", f"repos/{repo}/contents/PLAN.md", "-H", "Accept: application/vnd.github.raw"]
        )
    except GhError:
        plan = None
    prs = _json(
        gh,
        ["pr", "list", "--repo", repo, "--state", "open",
         "--json", "number,url,headRefName,createdAt"],
    )  # fmt: skip
    agent_prs = [p for p in prs or [] if str(p.get("headRefName", "")).startswith(BRANCH_PREFIXES)]
    pr = read_pr(repo, agent_prs[0], gh) if agent_prs else None
    return RepoState(exists=True, plan=plan, pr=pr)


def decide(project: Project, state: RepoState, now: datetime | None = None) -> Stage:
    now = now or datetime.now(UTC)
    if project.status not in ("approved", "building", "finishing"):
        return Stage("idle", reason=f"status is {project.status}")
    if not state.exists:
        return Stage("create", reason="repository does not exist yet")
    if state.pr is not None:
        pr = state.pr
        if pr.feedback:
            return Stage("address", pr=pr, reason=f"{len(pr.feedback)} new comment(s)")
        quiet_since = pr.last_activity or pr.created
        if (
            project.autopilot
            and pr.checks_green
            and any(m in pr.body for m in _PASS_MARKS)
            and now - quiet_since >= AUTOPILOT_QUIET
        ):
            return Stage("merge", pr=pr, reason="autopilot: reviewed, green, quiet 12h")
        return Stage("wait", pr=pr, reason="waiting for your review")
    if not state.plan:
        return Stage("plan", reason="no PLAN.md on main")
    todo = [m for m in state.milestones if not m.done]
    if todo:
        return Stage("build", milestone=todo[0].title, reason=f"{len(todo)} milestone(s) left")
    if not state.milestones:
        return Stage("plan", reason="PLAN.md has no milestone checklist")
    return Stage("finish", reason="all milestones merged")  # retried until it succeeds


# ---------------------------------------------------------------- resume entry


# Numbers glued to letters (p95, M2, H100, GPT4) are labels, not claims.
_NUMBER_RE = re.compile(r"(?<![A-Za-z\d])\d+(?:[.,]\d+)*")


def comment_block(block: str) -> str:
    return "\n".join(f"% {line}" if line.strip() else "%" for line in block.strip().splitlines())


def insert_reserve_project(tex: str, block: str) -> str:
    """Add a project as a commented-out (reserve) entry at the end of the
    Projects section, so the tailor may use it but the master is unchanged."""
    section = re.search(r"^\\section\{Projects\}", tex, re.MULTILINE)
    if section is None:
        raise ValueError("resume.tex has no live \\section{Projects}")
    end = tex.find("\\resumeSubHeadingListEnd", section.end())
    if end == -1:
        raise ValueError("Projects section has no \\resumeSubHeadingListEnd")
    line_start = tex.rfind("\n", 0, end) + 1
    return tex[:line_start] + comment_block(block) + "\n\n" + tex[line_start:]


def validate_entry(block: str) -> list[str]:
    problems = []
    if "\\resumeProjectHeading" not in block:
        problems.append("no \\resumeProjectHeading")
    if block.count("\\resumeItem{") < 2:
        problems.append("fewer than two \\resumeItem bullets")
    if "\\section" in block or "\\begin{document}" in block:
        problems.append("must be a single project entry, not a document")
    return problems


def unbacked_numbers(block: str, results: str) -> list[str]:
    """Numbers in the entry's bullets that RESULTS.md does not contain."""
    from opportunity_radar.resume.latex import find_macros, to_plain

    measured = set(_NUMBER_RE.findall(results))
    out: list[str] = []
    for call in find_macros(block, "resumeItem", 1):
        for number in _NUMBER_RE.findall(to_plain(call.args[0])):
            if number not in measured and number not in out:
                out.append(number)
    return out
