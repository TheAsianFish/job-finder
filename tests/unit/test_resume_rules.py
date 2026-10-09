"""Pinned projects, the ATS keyword guarantee and the narrative-first writer (AD-38)."""

from __future__ import annotations

import copy

import pytest

from opportunity_radar.resume.bank import build_bank
from opportunity_radar.resume.polish import build_prompt
from opportunity_radar.resume.selector import Posting, guarantee_keywords, select
from opportunity_radar.resume.tailor import load_pinned
from tests.conftest import load_fixture

VISION = Posting.from_text(
    "Computer Vision Intern",
    "PyTorch, deep learning, computer vision models, CUDA, Rust, teamwork. " * 5,
)


@pytest.fixture
def bank():
    return build_bank(load_fixture("resume_sample.tex"))


def _names(selection) -> list[str]:
    return [e.name for e, _ in selection.projects]


def test_without_pins_a_reserve_can_displace_any_project(bank):
    shown = _names(select(bank, VISION, prefer=["VisionLab"]))
    assert "VisionLab — Defect Detector" in shown and len(shown) == 3


def test_pinned_projects_always_stay_and_swaps_only_touch_the_free_slot(bank):
    bank.pinned_projects = ["Indexer", "OS Kernel"]
    selection = select(bank, VISION, prefer=["Swap in VisionLab", "Budget Dashboard"])
    shown = _names(selection)
    assert {"Indexer — Code Search Engine", "Toy OS Kernel"} <= set(shown)
    assert "VisionLab — Defect Detector" in shown and "Budget Dashboard" not in shown
    assert selection.swapped_out == ["Budget Dashboard"]


def test_pins_that_match_nothing_are_ignored(bank):
    bank.pinned_projects = ["Nonexistent Project"]
    assert len(_names(select(bank, VISION))) == 3


def test_guarantee_names_true_posting_skills_only(bank):
    skills = copy.deepcopy(bank.skills)
    added = guarantee_keywords(skills, VISION, bank)
    line = " ".join(", ".join(v) for v in skills.values())
    assert {"PyTorch", "Deep learning", "Computer vision"} <= set(added)
    assert "Rust" not in line and "CUDA" not in line  # not his: stay gaps
    assert "Collaboration/teamwork" not in added  # soft skills never added
    assert guarantee_keywords(skills, VISION, bank) == []  # idempotent


def test_guarantee_puts_terms_in_a_fitting_row(bank):
    posting = Posting.from_text("Kernel Intern", "operating systems and kubernetes " * 6)
    skills = copy.deepcopy(bank.skills)
    for row in skills.values():  # make both terms missing from the line
        row[:] = [i for i in row if "kubernetes" not in i.lower()]
    guarantee_keywords(skills, posting, bank)
    assert "Operating systems" in skills["Concepts"]
    assert "Kubernetes" in skills["DevOps/Tools"]


def test_select_reports_what_the_guarantee_added(bank):
    selection = select(bank, VISION)
    assert "PyTorch" in selection.ats_added
    assert "PyTorch" in " ".join(", ".join(v) for v in selection.skills.values())


def test_rules_file_loads_pins(tmp_path):
    rules = tmp_path / "resume_rules.yaml"
    rules.write_text("pinned_projects:\n  - Repolix\n  - ''\n  - OS Kernel\n")
    assert load_pinned(rules) == ["Repolix", "OS Kernel"]
    assert load_pinned(tmp_path / "missing.yaml") == []


def test_writer_puts_narrative_and_star_first(bank):
    entries = [(e, e.live_bullets) for e in bank.projects if e.active]
    prompt = build_prompt(
        entries, title="Backend Intern", company="Acme", description="", skills_line="Python"
    )
    assert "complete STAR story" in prompt and "one consistent story" in prompt.lower()
    assert "first words" not in prompt and "must first pass" not in prompt
    assert "never bend a bullet to fit a" in prompt
