"""What the project builder should do next, from the project repo's state.

The workflow (.github/workflows/projects.yml) calls `projects step`, which
reads the project's GitHub repo through `gh` and returns one stage:

    create   repo missing: create it (private), then plan
    plan     no PLAN.md on main: Fable writes the plan as a PR
    rerun    an open agent PR's CI failed on a first attempt: re-run the
             failed jobs once (no agent session; outages and flakes such as
             a registry 500 clear without a code change)
    address  an open agent PR has feedback newer than the agent's last
             commit/reply, or its CI failed again after the re-run (at most
             CI_FIX_ATTEMPTS sessions per PR, counting ones that crashed):
             Opus addresses it on that branch
    merge    autopilot only: the open PR passed review + CI and has sat
             AUTOPILOT_QUIET (5h) without feedback: merge it
    wait     an open agent PR awaits Patrick: do nothing (no compute spent)
    build    next unchecked milestone in PLAN.md: Opus builds and
             reviews it, one PR
    evolve   every milestone merged: Fable runs the project, reads its
             measured results and decides whether anything justifies more
             work; if so it appends at most 3 milestones to PLAN.md as a
             reviewed PR, if not it changes nothing (AD-44; EVOLVE_ROUNDS
             per project, never twice at the same plan size)
    finish   every milestone merged and evolving done: write the resume
             entry from measured results, proposed to the private repo as a PR
    idle     nothing to do

Only one agent PR is open per project at a time, so each project's pace
follows Patrick's reviews unless he opts into autopilot. Several approved
projects are built side by side (AD-41): `pick` takes whichever has work, so
one project waiting on a PR never stalls the others.
"""

from __future__ import annotations

import json
import re
import subprocess
import textwrap
from collections.abc import Callable
from dataclasses import dataclass, field, replace
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
CI_FIX_MARK = "<!-- ci-fix -->"  # on the reply after an automatic CI fix
CI_FIX_ATTEMPTS = 2
# One Claude Max usage window: Patrick can still stop a merge by commenting.
AUTOPILOT_QUIET = timedelta(hours=5)
# How many times a project may extend its own plan after finishing it
# (AD-44). Bounded so a project ends; Patrick's `steer` can always add more.
EVOLVE_ROUNDS = 2
_FREE_STAGES = ("merge", "rerun")  # no agent session, so they go first
_IDLE_STAGES = ("wait", "idle")
_FAILED = {"FAILURE", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED", "ERROR", "STARTUP_FAILURE"}
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
    checks_failed: list[str] = field(default_factory=list)  # finished and red
    ci_fix_attempts: int = 0
    rerunnable: list[int] = field(default_factory=list)  # red Actions runs on attempt 1


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


def _actions_runs(repo: str, commits: list[dict], gh: Gh) -> list[dict]:
    """Workflow runs for the PR's head commit, shaped like statusCheckRollup
    plus the run's id and attempt number."""
    sha = commits[-1].get("oid") if commits else None
    if not sha:
        return []
    data = _json(gh, ["api", f"repos/{repo}/actions/runs?head_sha={sha}"]) or {}
    # An unfinished run has no conclusion yet, so it never counts as green.
    return [
        {
            "name": r.get("name") or "",
            "conclusion": r.get("conclusion") or "",
            "id": r.get("id"),
            "attempt": int(r.get("run_attempt") or 1),
        }
        for r in data.get("workflow_runs") or []
    ]


def _rerunnable(runs: list[dict]) -> list[int]:
    """Failed runs that have not been re-run yet."""
    return [
        int(r["id"])
        for r in runs
        if r.get("id") and r["attempt"] == 1 and r["conclusion"].upper() in _FAILED
    ]


def read_pr(repo: str, raw: dict, gh: Gh) -> PullRequest:
    number = int(raw["number"])
    pr_view = ["pr", "view", str(number), "--repo", repo, "--json"]
    runs: list[dict] | None = None
    try:
        view = _json(gh, [*pr_view, "commits,statusCheckRollup,body"])
        checks = view.get("statusCheckRollup") or []
    except GhError:
        # A fine-grained token can't always read check runs (GitHub doesn't
        # offer "Checks" on every token); the Actions runs for the head commit
        # say the same thing with only "Actions: read".
        view = _json(gh, [*pr_view, "commits,body"])
        checks = runs = _actions_runs(repo, view.get("commits") or [], gh)
    commits = view.get("commits") or []
    last_commit = _when(commits[-1].get("committedDate")) if commits else None
    green = bool(checks) and all(
        (c.get("conclusion") or c.get("state") or "").upper() in ("SUCCESS", "NEUTRAL", "SKIPPED")
        for c in checks
    )
    failed = [
        str(c.get("name") or c.get("context") or "check")
        for c in checks
        if (c.get("conclusion") or c.get("state") or "").upper() in _FAILED
    ]
    if failed and runs is None:
        try:  # which runs to re-run; without them the builder goes straight to a fix
            runs = _actions_runs(repo, commits, gh)
        except GhError:
            runs = []
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
        checks_failed=failed,
        ci_fix_attempts=sum(CI_FIX_MARK in body for _, body, _ in notes),
        rerunnable=_rerunnable(runs or []) if failed else [],
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
        if pr.checks_failed:
            # A red check never merges. Re-run it once first: an outage (the
            # 2026-10-14 Docker Hub 500 on Replay M6) needs no code change.
            if pr.rerunnable:
                return Stage(
                    "rerun", pr=pr, reason=f"CI failed ({', '.join(pr.checks_failed)}); re-running"
                )
            # Then fix it, bounded so a fix that can't land doesn't loop.
            # Sessions are counted when they start (projects.yaml), so one
            # that crashes before replying still uses up an attempt.
            attempts = max(pr.ci_fix_attempts, project.ci_fix_started.count(pr.number))
            if attempts < CI_FIX_ATTEMPTS:
                note = [
                    f"CI is failing on this PR: {', '.join(pr.checks_failed)}. The failed jobs' "
                    "log tail is in .agent/ci-failure.log. Find the root cause, fix it, and "
                    "make the whole quality gate pass."
                ]
                n = attempts + 1
                return Stage(
                    "address",
                    pr=replace(pr, feedback=note),
                    reason=f"CI failing; fix attempt {n} of {CI_FIX_ATTEMPTS}",
                )
            return Stage("wait", pr=pr, reason="CI still failing after automatic fixes; needs you")
        quiet_since = pr.last_activity or pr.created
        if (
            project.autopilot
            and pr.checks_green
            and any(m in pr.body for m in _PASS_MARKS)
            and now - quiet_since >= AUTOPILOT_QUIET
        ):
            return Stage("merge", pr=pr, reason="autopilot: reviewed, green, quiet 5h")
        return Stage("wait", pr=pr, reason="waiting for your review")
    if not state.plan:
        return Stage("plan", reason="no PLAN.md on main")
    todo = [m for m in state.milestones if not m.done]
    if todo:
        return Stage("build", milestone=todo[0].title, reason=f"{len(todo)} milestone(s) left")
    if not state.milestones:
        return Stage("plan", reason="PLAN.md has no milestone checklist")
    # The plan is done. Before finishing, an evolve round asks whether the
    # measured results justify more work (AD-44): bounded rounds, and a round
    # that adds nothing is not repeated at the same plan size.
    size = len(state.milestones)
    rounds = project.evolve_rounds or EVOLVE_ROUNDS
    if len(project.evolved_at) < rounds and size not in project.evolved_at:
        n = len(project.evolved_at) + 1
        return Stage("evolve", reason=f"all milestones merged; evolve round {n} of {rounds}")
    return Stage("finish", reason="all milestones merged")  # retried until it succeeds


Option = tuple[Project, RepoState, Stage]


def pick(
    options: list[Option], slots: int | None = None, prefer: str | None = None
) -> Option | None:
    """The project to work on this run: a merge or CI re-run first (no agent
    session), then the first project, in priority order, with work. When none
    has work, the first one, so its wait reason is what gets reported.

    `slots` is the usage governor's project count (AD-42): only the first
    `slots` projects *that have work* may start agent sessions; the rest wait
    their turn. A project with nothing to do never holds a slot (2026-10-17:
    a waiting Replay held the only slot and blocked Anvil and Tributary).
    `prefer` (a slug) picks that project when it is allowed to run."""
    for option in options:
        if option[2].kind in _FREE_STAGES:
            return option
    working = [o for o in options if o[2].kind not in _IDLE_STAGES]
    allowed = working if slots is None else working[: max(slots, 0)]
    if prefer:
        for option in allowed:
            if option[0].slug == prefer:
                return option
    if allowed:
        return allowed[0]
    if working:
        project, state, stage = working[0]
        return project, state, Stage("wait", pr=stage.pr, reason="usage governor: " + (
            f"{project.slug} waits; only {max(slots or 0, 0)} project(s) may run now"
        ))  # fmt: skip
    return options[0] if options else None


def hold_evolve(options: list[Option], why: str) -> list[Option]:
    """Without spare usage, evolve rounds wait so other projects' required
    work goes first (AD-48). When no other project has work, a round is the
    only use of the slot and runs under the normal governor (2026-10-20:
    Patrick paused the rest to finish Replay, and spare usage never came)."""
    if not any(st.kind not in (*_IDLE_STAGES, "evolve") for _, _, st in options):
        return options
    return [
        (p, s, Stage("wait", reason=f"evolve waits for spare Claude usage ({why})"))
        if st.kind == "evolve"
        else (p, s, st)
        for p, s, st in options
    ]


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


_HREF_RE = re.compile(r"\\href\{([^}]+)\}")


def upsert_project(tex: str, block: str) -> str:
    """Replace the project's entry (found by its repo link) with `block`, or
    add it as a reserve entry. A reserve stays commented out; an entry Patrick
    made live stays live. Superseded (%%) lines are never touched."""
    link = _HREF_RE.search(block)
    if link is None:
        return insert_reserve_project(tex, block)
    lines = tex.splitlines()
    for start, line in enumerate(lines):
        live = not line.lstrip().startswith("%")
        body = line.lstrip().removeprefix("% ").removeprefix("%") if not live else line
        if not body.lstrip().startswith("\\resumeProjectHeading"):
            continue
        if link.group(1) not in "\n".join(lines[start : start + 3]):
            continue
        end = next((i for i in range(start, len(lines)) if "\\resumeItemListEnd" in lines[i]), None)
        if end is None:
            break
        new = block.strip() if live else comment_block(block)
        indent = line[: len(line) - len(line.lstrip())] if live else ""
        replacement = [indent + row if row else row for row in new.splitlines()]
        out = "\n".join([*lines[:start], *replacement, *lines[end + 1 :]])
        return out + ("\n" if tex.endswith("\n") else "")
    return insert_reserve_project(tex, block)


def find_project_entry(tex: str, repo: str) -> str:
    """The project's current entry (live or reserve, uncommented) found by its
    repo link, or "" if the resume has none. Superseded (%%) lines are skipped."""
    lines = tex.splitlines()
    for start, line in enumerate(lines):
        if line.lstrip().startswith("%%"):
            continue
        body = line.lstrip().removeprefix("% ").removeprefix("%")
        if not body.lstrip().startswith("\\resumeProjectHeading"):
            continue
        if repo not in "\n".join(lines[start : start + 3]):
            continue
        end = next((i for i in range(start, len(lines)) if "\\resumeItemListEnd" in lines[i]), None)
        if end is None:
            return ""
        rows = [
            r.lstrip().removeprefix("% ").removeprefix("%") if r.lstrip().startswith("%") else r
            for r in lines[start : end + 1]
        ]
        return textwrap.dedent("\n".join(rows)).strip() + "\n"
    return ""


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
