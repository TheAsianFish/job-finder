"""Hiring panel (recruiter, hiring manager, interviewer + ATS) and outcome lessons."""

from __future__ import annotations

import json
import threading

import pytest

from opportunity_radar.insights.outcomes import Funnel, lessons, tailored_meta
from opportunity_radar.resume.assess import FitAssessment
from opportunity_radar.resume.bank import build_bank
from opportunity_radar.resume.ledger import find_tailored
from opportunity_radar.resume.panel import run_panel, seated, summary
from opportunity_radar.resume.paths import private_dir
from opportunity_radar.resume.review import render_markdown, review
from opportunity_radar.resume.tailor import master_text
from tests.conftest import load_fixture

DESCRIPTION = (
    "We build backend services in Python and Go on Kubernetes. You will design APIs, "
    "work with PostgreSQL, and improve reliability of distributed systems. " * 6
)
ANSWERS = {
    "technical recruiter": {
        "first_impression": "IBM internship",
        "stands_out": ["IBM"],
        "red_flags": ["Go not visible"],
        "advance": "Maybe",
        "why": "solid but generic",
    },
    "engineering manager": {
        "team_needs": ["APIs"],
        "projects": [{"name": "Repolix", "fit": "strong", "why": "Python services"}],
        "swaps": [],
        "missing_evidence": ["Kubernetes"],
        "interview": "yes",
        "why": "backend depth",
    },
    "interview this candidate": {
        "fragile_bullets": [
            {"bullet": "Cut latency 40%", "likely_question": "How measured?", "risk": "vague"}
        ],
        "strongest_story": "Repolix retrieval",
        "prep": ["p95 methodology"],
    },
    "resume editor who coaches": {
        "story": "Backend engineer who ships search and data tools",
        "coherent": "Partly",
        "star_gaps": [
            {"bullet": "Built dashboard", "missing": "result", "fix": "say what it replaced"}
        ],
        "repetition": ["'Built' opens four bullets"],
    },
}
LEAD = {
    "verdict": "Good fit once Go and PostgreSQL work is visible.",
    "strengths": ["Backend internship"],
    "weak_bullets": [],
    "projects": [],
    "culture_fit": "",
    "competitiveness": "",
    "swaps": [],
    "new_project": {"needed": False},
    "changes": ["Lead with the PostgreSQL work", "Name Kubernetes in the IBM bullet"],
}


@pytest.fixture(scope="module")
def bank():
    return build_bank(load_fixture("resume_sample.tex"))


def _fit() -> FitAssessment:
    return FitAssessment("tune", ["Go hidden"], 0.5, 0.7, ["Python"], ["Go"], [], [], 0.5)


class FakeRunner:
    """Answers each persona by a phrase in its prompt; the lead gets LEAD."""

    def __init__(self, fail: str | None = None):
        self.prompts: list[str] = []
        self.fail = fail
        self.lock = threading.Lock()

    def __call__(self, prompt: str) -> str:
        with self.lock:
            self.prompts.append(prompt)
        if "LEAD of a hiring panel" in prompt:
            return json.dumps(LEAD)
        for phrase, answer in ANSWERS.items():
            if phrase in prompt:
                if self.fail == phrase:
                    raise TimeoutError("claude timed out")
                return json.dumps(answer)
        return json.dumps(LEAD)  # the single-reviewer prompt


def test_panel_runs_every_seat_and_the_ats_check(bank):
    runner = FakeRunner()
    panel = run_panel(
        bank, master_text(bank), title="Backend Intern", company="Acme",
        description=DESCRIPTION, runner=runner,
    )  # fmt: skip
    assert seated(panel) == ["recruiter", "hiring_manager", "interviewer", "editor"]
    assert len(runner.prompts) == 4
    recruiter = next(p for p in runner.prompts if "technical recruiter" in p)
    assert "buried keywords" not in recruiter and "Don't count keywords" in recruiter
    assert 0 <= panel["ats"]["keyword_coverage"] <= 1
    assert summary(panel)["recruiter"] == "maybe" and summary(panel)["hiring_manager"] == "yes"
    assert summary(panel)["editor"] == "partly"
    assert "guaranteed_by_code_on_skills_line" in panel["ats"]


def test_a_failing_seat_is_recorded_and_the_rest_still_answer(bank):
    panel = run_panel(
        bank, master_text(bank), title="Backend Intern", company="Acme",
        description=DESCRIPTION, runner=FakeRunner(fail="technical recruiter"),
    )  # fmt: skip
    assert "TimeoutError" in panel["recruiter"]["error"]
    assert seated(panel) == ["hiring_manager", "interviewer", "editor"]
    assert "recruiter" not in summary(panel)


def test_no_runner_still_gives_the_ats_seat(bank):
    panel = run_panel(
        bank, master_text(bank), title="Backend Intern", company="Acme",
        description=DESCRIPTION, runner=None,
    )  # fmt: skip
    assert set(panel) == {"ats"}


def test_lead_review_reads_the_panel_and_lessons(bank):
    runner = FakeRunner()
    rev = review(
        bank, master_text(bank), title="Backend Intern", company="Acme",
        description=DESCRIPTION, fit=_fit(), runner=runner,
        lessons="3 applications logged, 1 response",
    )  # fmt: skip
    lead_prompt = next(p for p in runner.prompts if "LEAD of a hiring panel" in p)
    assert "3 applications logged" in lead_prompt and "Go not visible" in lead_prompt
    assert "never recommend working a keyword into a" in lead_prompt
    assert "complete STAR story" in lead_prompt
    assert rev.changes == LEAD["changes"] and rev.panel["hiring_manager"]["interview"] == "yes"
    md = render_markdown(rev, _fit(), title="Backend Intern", company="Acme")
    assert "## Top changes (panel lead)" in md and "1. Lead with the PostgreSQL work" in md
    assert "Recruiter (6-second skim):** advance = Maybe" in md
    assert "## Be ready to defend (interviewer)" in md and "How measured?" in md
    assert "**Editor:** coherent = Partly" in md and "## STAR gaps (editor)" in md
    assert "missing result. say what it replaced" in md


def test_single_reviewer_mode_makes_one_call(bank):
    runner = FakeRunner()
    rev = review(
        bank, master_text(bank), title="Backend Intern", company="Acme",
        description=DESCRIPTION, fit=_fit(), runner=runner, use_panel=False,
    )  # fmt: skip
    assert len(runner.prompts) == 1 and rev.panel == {}


# ---------------------------------------------------------------- outcomes


def _funnel(*statuses: str) -> Funnel:
    f = Funnel()
    for s in statuses:
        f.add(s)
    return f


def test_lessons_without_applications():
    assert lessons({}).startswith("No applications logged yet")


def test_lessons_compare_groups_and_flag_small_samples():
    dims = {
        "Overall": {"all": _funnel("applied", "oa", "rejected", "interview")},
        "Project shown": {
            "Repolix": _funnel("oa", "interview", "applied"),
            "Trading Dashboard": _funnel("applied", "rejected"),
        },
        "Role family": {"backend": _funnel("oa")},  # one group only: skipped
    }
    text = lessons(dims)
    assert "4 applications logged, 2 responses (50%)" in text
    assert "treat every pattern below as anecdote" in text
    assert "- Project shown: Repolix: 2/3 (small); Trading Dashboard: 0/2 (small)" in text
    assert "Role family" not in text


def _tailored(name: str, meta: dict) -> None:
    folder = private_dir() / "tailored" / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "meta.json").write_text(json.dumps(meta))


def test_find_tailored_by_job_id_or_url_newest_first():
    _tailored("2026-10-01-acme-backend", {"job_id": 7, "apply_url": "https://acme.com/jobs/1"})
    _tailored("2026-10-05-acme-backend", {"job_id": 7, "apply_url": "https://acme.com/jobs/1"})
    _tailored("2026-10-06-other", {"job_id": 9, "apply_url": "https://other.com/x"})
    assert find_tailored(7, None) == "2026-10-05-acme-backend"
    assert find_tailored(None, "https://acme.com/jobs/1?utm_source=x") == "2026-10-05-acme-backend"
    assert find_tailored(3, "https://nowhere.com") is None


def test_tailored_meta_reads_only_real_folders():
    _tailored("2026-10-05-acme", {"projects": ["Repolix"], "panel": {"recruiter": "yes"}})
    assert tailored_meta("2026-10-05-acme")["projects"] == ["Repolix"]
    assert tailored_meta("backend") == {} and tailored_meta("../secrets") == {}


def test_discord_message_shows_panel_votes_and_top_changes():
    from opportunity_radar.notifications.templates import build_resume_check_message
    from opportunity_radar.resume.review import Review

    class Job:
        title, company_name, apply_url = "Backend Intern", "Acme", "https://acme.com/j/1"

    rev = Review(
        verdict="Close.",
        changes=["Lead with PostgreSQL", "Name Kubernetes", "Cut the dashboard", "Fourth"],
        panel={
            "recruiter": {"advance": "maybe"},
            "hiring_manager": {"interview": "yes"},
            "editor": {"coherent": "partly"},
        },
    )
    text = build_resume_check_message(Job(), _fit(), rev, "1 page")["embeds"][0]["description"]
    assert (
        "👥 Panel: recruiter advance: maybe · manager interview: yes · page coherent: partly"
        in text
    )
    assert "✏️ Cut the dashboard" in text and "Fourth" not in text
