"""Portfolio pipeline and project-builder decisions (AD-32)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from typer.testing import CliRunner

from opportunity_radar.projects.builder import (
    AGENT_MARK,
    CI_FIX_ATTEMPTS,
    CI_FIX_MARK,
    REVIEW_PASS,
    GhError,
    PullRequest,
    RepoState,
    decide,
    insert_reserve_project,
    parse_milestones,
    read_state,
    unbacked_numbers,
    validate_entry,
)
from opportunity_radar.projects.portfolio import (
    Project,
    add_proposals,
    load_projects,
    next_project,
    save_projects,
    set_status,
)
from opportunity_radar.resume.bank import build_bank
from tests.conftest import load_fixture

NOW = datetime(2026, 10, 9, 12, tzinfo=UTC)
PLAN = """# Plan

## Goal
Something real.

## Milestones
- [x] M1: Scaffold, CI, thin vertical slice — done when tests pass
- [ ] M2: Retrieval with evals — done when recall@10 is measured
- [ ] M3: Release readiness

## Risks
- [ ] not a milestone
"""
ENTRY = r"""\resumeProjectHeading
  {\textbf{Evalkit --- LLM Agent Evaluation Harness} $|$ \emph{Python, FastAPI} $|$ \href{https://github.com/TheAsianFish/evalkit}{\textcolor{blue}{GitHub}}}{}
  \resumeItemListStart
    \resumeItem{Built an evaluation harness that replays 250 agent traces, raising task success from 61\% to \textbf{78\%}.}
    \resumeItem{Cut p95 latency to 840ms with response caching and batched tool calls.}
  \resumeItemListEnd
"""


# ---------------------------------------------------------------- projects.yaml


def test_projects_round_trip_and_pipeline_order(tmp_path):
    path = tmp_path / "projects.yaml"
    projects = [
        Project(slug="a", title="Alpha", status="proposed"),
        Project(slug="b", title="Beta", status="approved"),
        Project(
            slug="c", title="Gamma", status="building", repo="TheAsianFish/c", ci_fix_started=[7]
        ),
    ]
    save_projects(projects, path)
    assert "status: approved" in path.read_text() and path.read_text().startswith("# Portfolio")
    assert path.read_text().count("ci_fix_started") == 1  # omitted when empty
    loaded = load_projects(path)
    assert [p.ci_fix_started for p in loaded] == [[], [], [7]]
    assert [p.slug for p in loaded] == ["a", "b", "c"]
    assert next_project(loaded).slug == "c"  # in-flight work first
    set_status(loaded, "c", "paused")
    assert next_project(loaded).slug == "b"
    with pytest.raises(ValueError):
        set_status(loaded, "a", "shipping")
    with pytest.raises(KeyError):
        set_status(loaded, "zzz", "approved")
    assert loaded[0].repo_name == "TheAsianFish/a"


def test_scout_proposals_never_duplicate():
    projects = [Project(slug="evalkit", title="Evalkit")]
    added = add_proposals(
        projects,
        [
            Project(slug="evalkit", title="Evalkit again", status="approved"),
            Project(slug="x", title="Evalkit"),  # same title
            Project(slug="ragbench", title="RAG Bench", status="approved"),
        ],
    )
    assert [p.slug for p in added] == ["ragbench"]
    assert added[0].status == "proposed" and added[0].proposed  # scout can't self-approve


# ---------------------------------------------------------------- decisions


def test_parse_milestones_reads_only_the_milestone_section():
    milestones = parse_milestones(PLAN)
    assert [m.done for m in milestones] == [True, False, False]
    assert milestones[1].title.startswith("M2: Retrieval")


def _pr(**kwargs) -> PullRequest:
    base = dict(
        number=4,
        url="https://github.com/TheAsianFish/evalkit/pull/4",
        branch="dev/m2",
        created=NOW - timedelta(hours=20),
        last_activity=NOW - timedelta(hours=20),
    )
    base.update(kwargs)
    return PullRequest(**base)


@pytest.mark.parametrize(
    ("status", "state", "expected"),
    [
        ("proposed", RepoState(exists=True, plan=PLAN), "idle"),
        ("approved", RepoState(exists=False), "create"),
        ("building", RepoState(exists=True, plan=None), "plan"),
        ("building", RepoState(exists=True, plan="# no checklist"), "plan"),
        ("building", RepoState(exists=True, plan=PLAN), "build"),
        ("building", RepoState(exists=True, plan=PLAN, pr=_pr()), "wait"),
        (
            "building",
            RepoState(exists=True, plan=PLAN, pr=_pr(feedback=["use pgvector"])),
            "address",
        ),
        ("building", RepoState(exists=True, plan=PLAN.replace("[ ]", "[x]")), "finish"),
        ("finishing", RepoState(exists=True, plan=PLAN.replace("[ ]", "[x]")), "finish"),
    ],
)
def test_decide_stages(status, state, expected):
    stage = decide(Project(slug="evalkit", title="Evalkit", status=status), state, NOW)
    assert stage.kind == expected
    if expected == "build":
        assert stage.milestone.startswith("M2")


def test_autopilot_merges_only_reviewed_green_quiet_prs():
    project = Project(slug="e", title="E", status="building", autopilot=True)
    ready = _pr(checks_green=True, body=f"Summary\n{REVIEW_PASS}")
    assert decide(project, RepoState(True, PLAN, ready), NOW).kind == "merge"
    for pr in (
        _pr(checks_green=False, body=REVIEW_PASS),
        _pr(checks_green=True, body="<!-- review: changes -->"),
        _pr(checks_green=True, body=REVIEW_PASS, last_activity=NOW - timedelta(hours=2)),
    ):
        assert decide(project, RepoState(True, PLAN, pr), NOW).kind == "wait"
    project.autopilot = False
    assert decide(project, RepoState(True, PLAN, ready), NOW).kind == "wait"


def test_failed_ci_gets_bounded_automatic_fixes():
    project = Project(slug="e", title="E", status="building", autopilot=True)
    red = _pr(checks_green=False, body=REVIEW_PASS, checks_failed=["Smoke test"])
    stage = decide(project, RepoState(True, PLAN, red), NOW)
    assert stage.kind == "address" and stage.reason.startswith("CI failing; fix attempt 1 of 2")
    assert "Smoke test" in stage.pr.feedback[0]
    red.ci_fix_attempts = CI_FIX_ATTEMPTS
    stage = decide(project, RepoState(True, PLAN, red), NOW)
    assert stage.kind == "wait" and "needs you" in stage.reason
    pending = _pr(checks_green=False, body=REVIEW_PASS)  # still running: just wait
    assert decide(project, RepoState(True, PLAN, pending), NOW).kind == "wait"


def test_failed_ci_is_rerun_once_before_a_fix_session():
    project = Project(slug="e", title="E", status="building", autopilot=True)
    red = _pr(checks_failed=["CI"], rerunnable=[38531971040])
    stage = decide(project, RepoState(True, PLAN, red), NOW)
    assert stage.kind == "rerun" and stage.reason == "CI failed (CI); re-running"
    red.rerunnable = []  # the re-run failed too: now a fix session
    assert decide(project, RepoState(True, PLAN, red), NOW).kind == "address"


def test_ci_fix_sessions_that_crashed_still_count():
    # PR #7: every session died before replying, so the PR comments showed
    # zero attempts and the builder retried forever.
    red = _pr(checks_failed=["CI"])
    project = Project(slug="e", title="E", status="building", ci_fix_started=[3, 4])
    stage = decide(project, RepoState(True, PLAN, red), NOW)
    assert stage.kind == "address" and stage.reason == "CI failing; fix attempt 2 of 2"
    project.ci_fix_started.append(4)
    stage = decide(project, RepoState(True, PLAN, red), NOW)
    assert stage.kind == "wait" and "needs you" in stage.reason


def test_legacy_review_marker_still_counts():
    project = Project(slug="e", title="E", status="building", autopilot=True)
    legacy = _pr(checks_green=True, body="Summary\n<!-- fable-review: pass -->")
    assert decide(project, RepoState(True, PLAN, legacy), NOW).kind == "merge"


class FakeGh:
    """Answers the gh calls read_state makes, keyed by their first args."""

    def __init__(
        self, *, exists=True, plan=PLAN, prs=None, comments=None, commits=None, runs=None,
        rollup=None,
    ):  # fmt: skip
        self.exists, self.plan = exists, plan
        self.runs = runs  # set: the token can't read check runs, only Actions runs
        self.rollup = rollup or [{"conclusion": "SUCCESS"}]
        self.prs = prs or []
        self.comments = comments or []
        self.commits = commits or []
        self.calls: list[list[str]] = []
        self.runs_for_ids: list[dict] = []

    def __call__(self, args: list[str]) -> str:
        self.calls.append(args)
        if args[:2] == ["repo", "view"]:
            if not self.exists:
                raise GhError("not found")
            return "{}"
        if args[0] == "api" and args[1].endswith("contents/PLAN.md"):
            if self.plan is None:
                raise GhError("404")
            return self.plan
        if args[:2] == ["pr", "list"]:
            return json.dumps(self.prs)
        if args[:2] == ["pr", "view"]:
            if self.runs is not None:
                if "statusCheckRollup" in args[-1]:
                    raise GhError("GraphQL: Resource not accessible by personal access token")
                return json.dumps({"commits": self.commits, "body": REVIEW_PASS})
            return json.dumps(
                {
                    "commits": self.commits,
                    "statusCheckRollup": self.rollup,
                    "body": REVIEW_PASS,
                }
            )
        if args[0] == "api" and "actions/runs" in args[1]:
            return json.dumps({"workflow_runs": self.runs or self.runs_for_ids})
        if args[0] == "api" and "issues" in args[1]:
            return json.dumps(self.comments)
        if args[0] == "api":
            return "[]"
        raise AssertionError(args)


def test_read_state_finds_only_unaddressed_human_feedback():
    commit_at = "2026-10-09T08:00:00Z"
    gh = FakeGh(
        prs=[
            {"number": 9, "url": "u9", "headRefName": "dependabot/x", "createdAt": commit_at},
            {"number": 4, "url": "u4", "headRefName": "dev/m2", "createdAt": commit_at},
        ],
        commits=[{"committedDate": commit_at}],
        comments=[
            {"body": "old note, already handled", "created_at": "2026-10-09T07:00:00Z"},
            {"body": f"Done.\n{AGENT_MARK}", "created_at": "2026-10-09T09:00:00Z"},
            {"body": "Please add a pgvector backend", "created_at": "2026-10-09T10:00:00Z"},
        ],
    )
    state = read_state("TheAsianFish/evalkit", gh)
    assert state.exists and state.plan == PLAN
    assert state.pr is not None and state.pr.number == 4
    assert state.pr.feedback == ["Please add a pgvector backend"]
    assert state.pr.checks_green and REVIEW_PASS in state.pr.body

    replied = FakeGh(
        prs=gh.prs,
        commits=[{"committedDate": commit_at}],
        comments=[
            {"body": "Please add a pgvector backend", "created_at": "2026-10-09T10:00:00Z"},
            {"body": f"Added.\n{AGENT_MARK}", "created_at": "2026-10-09T11:00:00Z"},
        ],
    )
    assert read_state("TheAsianFish/evalkit", replied).pr.feedback == []
    assert read_state("x/y", FakeGh(exists=False)).exists is False
    assert read_state("x/y", FakeGh(plan=None)).plan is None


def test_ci_is_read_from_actions_runs_when_check_runs_are_off_limits():
    prs = [{"number": 4, "url": "u4", "headRefName": "dev/m2", "createdAt": "2026-10-09T08:00:00Z"}]
    commits = [{"committedDate": "2026-10-09T08:00:00Z", "oid": "abc123"}]
    passed = FakeGh(prs=prs, commits=commits, runs=[{"conclusion": "success"}])
    assert read_state("x/y", passed).pr.checks_green
    assert any(a[1] == "repos/x/y/actions/runs?head_sha=abc123" for a in passed.calls)
    running = FakeGh(
        prs=prs, commits=commits, runs=[{"conclusion": "success"}, {"conclusion": None}]
    )
    assert not read_state("x/y", running).pr.checks_green
    assert not read_state("x/y", FakeGh(prs=prs, commits=commits, runs=[])).pr.checks_green
    red = FakeGh(
        prs=prs,
        commits=commits,
        runs=[{"name": "CI", "conclusion": "failure"}],
        comments=[
            {
                "body": f"Fixed CI.\n{AGENT_MARK}\n{CI_FIX_MARK}",
                "created_at": "2026-10-09T09:00:00Z",
            }
        ],
    )
    pr = read_state("x/y", red).pr
    assert pr.checks_failed == ["CI"] and pr.ci_fix_attempts == 1 and pr.feedback == []
    assert pr.rerunnable == []  # GitHub's run ids are missing from these runs


def test_only_first_attempt_failures_are_rerunnable():
    prs = [{"number": 7, "url": "u7", "headRefName": "dev/m6", "createdAt": "2026-10-14T07:00:00Z"}]
    commits = [{"committedDate": "2026-10-14T07:00:00Z", "oid": "abc123"}]
    runs = [
        {"name": "CI", "conclusion": "failure", "id": 11, "run_attempt": 1},
        {"name": "Docs", "conclusion": "failure", "id": 12, "run_attempt": 2},
        {"name": "Lint", "conclusion": "success", "id": 13, "run_attempt": 1},
    ]
    # Check runs readable: the run ids still come from the Actions runs.
    gh = FakeGh(prs=prs, commits=commits, rollup=[{"name": "compose", "conclusion": "FAILURE"}])
    gh.runs_for_ids = runs
    assert read_state("x/y", gh).pr.rerunnable == [11]
    assert read_state("x/y", FakeGh(prs=prs, commits=commits, runs=runs)).pr.rerunnable == [11]
    green = FakeGh(prs=prs, commits=commits)
    assert read_state("x/y", green).pr.rerunnable == []
    assert not any("actions/runs" in a[1] for a in green.calls if a[0] == "api")


# ---------------------------------------------------------------- resume entry


def test_resume_entry_is_inserted_as_a_reserve_project():
    source = load_fixture("resume_sample.tex")
    assert validate_entry(ENTRY) == []
    updated = insert_reserve_project(source, ENTRY)
    bank = build_bank(updated)
    reserve = [p.name for p in bank.projects if not p.active]
    assert "Evalkit — LLM Agent Evaluation Harness" in reserve
    live_before = [p.name for p in build_bank(source).projects if p.active]
    assert [p.name for p in bank.projects if p.active] == live_before  # master unchanged
    with pytest.raises(ValueError):
        insert_reserve_project("\\section{Experience}", ENTRY)


def test_entry_validation_and_unbacked_numbers():
    assert "fewer than two" in validate_entry("\\resumeProjectHeading{x}{} \\resumeItem{a}")[0]
    assert validate_entry("\\section{X}\\resumeProjectHeading \\resumeItem{a} \\resumeItem{b}")
    results = "Replayed 250 traces. Success 61% -> 78%."
    assert unbacked_numbers(ENTRY, results) == ["840"]


# ---------------------------------------------------------------- CLI step


def test_cli_step_creates_repo_marks_building_and_writes_context(tmp_path, monkeypatch):
    from opportunity_radar import cli_projects
    from opportunity_radar.cli import app
    from opportunity_radar.resume.paths import private_dir

    save_projects([Project(slug="evalkit", title="Evalkit", status="approved", pitch="Evals")])
    gh = FakeGh(exists=False)
    created: list[list[str]] = []

    def fake(args):
        if args[:2] == ["repo", "create"]:
            created.append(args)
            return ""
        return gh(args)

    monkeypatch.setattr("opportunity_radar.projects.builder.gh_cli", lambda token=None: fake)
    monkeypatch.setattr(cli_projects, "_candidate_summary", lambda: {"skills": {"L": ["Python"]}})
    out = tmp_path / "context.json"
    result = CliRunner().invoke(app, ["projects", "step", "--out", str(out), "--no-push"])
    assert result.exit_code == 0, result.output
    context = json.loads(out.read_text())
    assert context["stage"] == "plan" and context["repo"] == "TheAsianFish/evalkit"
    assert created and created[0][2] == "TheAsianFish/evalkit" and "--private" in created[0]
    assert context["candidate"]["skills"] == {"L": ["Python"]}
    assert context["hub"].startswith("# Shared context")  # agents get the shared memory
    saved = load_projects(private_dir() / "projects.yaml")
    assert saved[0].status == "building" and saved[0].repo == "TheAsianFish/evalkit"

    dry = CliRunner().invoke(app, ["projects", "step", "--dry-run", "--out", str(out)])
    assert dry.exit_code == 0


def test_cli_step_reruns_red_ci_and_records_fix_attempts(tmp_path, monkeypatch):
    from opportunity_radar import cli_projects
    from opportunity_radar.cli import app
    from opportunity_radar.resume.paths import private_dir

    save_projects([Project(slug="replay", title="Replay", status="building", autopilot=True)])
    prs = [{"number": 7, "url": "u7", "headRefName": "dev/m6", "createdAt": "2026-10-14T07:00:00Z"}]
    commits = [{"committedDate": "2026-10-14T07:00:00Z", "oid": "abc123"}]
    runs = [{"name": "CI", "conclusion": "failure", "id": 38531971040, "run_attempt": 1}]
    gh = FakeGh(prs=prs, commits=commits, runs=runs)
    reruns: list[list[str]] = []
    allowed = True

    def fake(args):
        if args[:2] == ["run", "rerun"]:
            if not allowed:
                raise GhError("HTTP 403: Resource not accessible by personal access token")
            reruns.append(args)
            return ""
        return gh(args)

    monkeypatch.setattr("opportunity_radar.projects.builder.gh_cli", lambda token=None: fake)
    monkeypatch.setattr(cli_projects, "_candidate_summary", lambda: {})
    out = tmp_path / "context.json"
    step = ["projects", "step", "--out", str(out), "--no-push"]

    result = CliRunner().invoke(app, step)
    assert result.exit_code == 0, result.output
    assert json.loads(out.read_text())["stage"] == "rerun"
    assert reruns == [["run", "rerun", "38531971040", "--failed", "--repo", "TheAsianFish/replay"]]
    assert load_projects(private_dir() / "projects.yaml")[0].ci_fix_started == []

    # A token without "Actions: write" can't re-run: fix it instead, and the
    # session is counted before it starts.
    allowed = False
    result = CliRunner().invoke(app, step)
    assert result.exit_code == 0, result.output
    context = json.loads(out.read_text())
    assert context["stage"] == "address" and context["reason"].startswith(
        "CI failing; fix attempt 1"
    )
    assert load_projects(private_dir() / "projects.yaml")[0].ci_fix_started == [7]

    # A dry run (the scan chain's wake-up check) changes nothing.
    allowed = True
    reruns.clear()
    assert CliRunner().invoke(app, [*step, "--dry-run"]).exit_code == 0
    assert reruns == [] and json.loads(out.read_text())["stage"] == "rerun"
    assert load_projects(private_dir() / "projects.yaml")[0].ci_fix_started == [7]
