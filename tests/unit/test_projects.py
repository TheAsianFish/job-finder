"""Portfolio pipeline and project-builder decisions (AD-32)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from typer.testing import CliRunner

from opportunity_radar.projects.builder import (
    AGENT_MARK,
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
        Project(slug="c", title="Gamma", status="building", repo="TheAsianFish/c"),
    ]
    save_projects(projects, path)
    assert "status: approved" in path.read_text() and path.read_text().startswith("# Portfolio")
    loaded = load_projects(path)
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
        branch="agent/m2",
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
        _pr(checks_green=True, body="<!-- fable-review: changes -->"),
        _pr(checks_green=True, body=REVIEW_PASS, last_activity=NOW - timedelta(hours=2)),
    ):
        assert decide(project, RepoState(True, PLAN, pr), NOW).kind == "wait"
    project.autopilot = False
    assert decide(project, RepoState(True, PLAN, ready), NOW).kind == "wait"


class FakeGh:
    """Answers the gh calls read_state makes, keyed by their first args."""

    def __init__(self, *, exists=True, plan=PLAN, prs=None, comments=None, commits=None):
        self.exists, self.plan = exists, plan
        self.prs = prs or []
        self.comments = comments or []
        self.commits = commits or []
        self.calls: list[list[str]] = []

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
            return json.dumps(
                {
                    "commits": self.commits,
                    "statusCheckRollup": [{"conclusion": "SUCCESS"}],
                    "body": REVIEW_PASS,
                }
            )
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
            {"number": 4, "url": "u4", "headRefName": "agent/m2", "createdAt": commit_at},
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
    saved = load_projects(private_dir() / "projects.yaml")
    assert saved[0].status == "building" and saved[0].repo == "TheAsianFish/evalkit"

    dry = CliRunner().invoke(app, ["projects", "step", "--dry-run", "--out", str(out)])
    assert dry.exit_code == 0
