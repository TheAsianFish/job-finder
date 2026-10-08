"""Resume engine: parse -> bank -> select -> guarded polish -> render -> ATS."""

from __future__ import annotations

import json

import pytest

from opportunity_radar.resume.ats import analyse, render_markdown
from opportunity_radar.resume.bank import build_bank
from opportunity_radar.resume.compiler import find_pdflatex
from opportunity_radar.resume.latex import escape, find_macros, split_sections, to_plain
from opportunity_radar.resume.polish import guard, polish, to_tex
from opportunity_radar.resume.render import render
from opportunity_radar.resume.selector import Posting, select
from opportunity_radar.resume.tailor import tailor
from tests.conftest import load_fixture

SOURCE = load_fixture("resume_sample.tex")


@pytest.fixture(scope="module")
def bank():
    return build_bank(SOURCE)


# ---------------------------------------------------------------- latex


def test_find_macros_reads_balanced_arguments():
    calls = find_macros(
        r"\resumeItem{Cut \textbf{latency {90\%}} fast} \resumeItemListEnd", "resumeItem", 1
    )
    assert len(calls) == 1
    assert calls[0].args[0] == r"Cut \textbf{latency {90\%}} fast"


def test_split_sections_separates_live_commented_and_superseded():
    preamble, sections = split_sections(SOURCE)
    assert "\\begin{document}" in preamble and "Alex Example" in preamble
    names = [s.name for s in sections]
    assert names == ["Education", "Experience", "Projects", "Technical Skills"]
    experience = sections[1]
    assert "Research Assistant" in experience.commented
    assert "Did some ML stuff" not in experience.commented  # %% superseded wording dropped
    assert "Research Assistant" not in experience.active


def test_to_plain_and_escape_round_trip_specials():
    tex = r"\textbf{cutting latency 90\% (2.5--3s to ${\sim}$200ms)} for 1{,}500+ C\# users"
    plain = to_plain(tex)
    assert plain == "cutting latency 90% (2.5–3s to ~200ms) for 1,500+ C# users"  # noqa: RUF001
    assert escape("90% & C# {x} ~5") == r"90\% \& C\# \{x\} ${\sim}$5"


# ---------------------------------------------------------------- bank


def test_bank_structure(bank):
    assert bank.candidate_name == "Alex Example"
    live_exp = [e.name for e in bank.experiences if e.active]
    assert live_exp == [
        "Software Engineering Intern @ Acme Cloud",
        "Student IT Worker @ Springfield City Hall",
        "Open Source Fellow @ Example Fellowship",
    ]
    reserve = next(e for e in bank.experiences if not e.active)
    assert reserve.org == "Example Vision Lab" and len(reserve.bullets) == 2
    assert [p.name for p in bank.projects if not p.active] == ["VisionLab — Defect Detector"]
    assert bank.skills["Languages"][1] == "C#"
    assert {"PyTorch", "Computer vision", "Operating systems"} <= bank.all_skills
    work = {e.name: e.is_work for e in bank.experiences if e.active}
    assert work["Open Source Fellow @ Example Fellowship"] is False
    assert work["Student IT Worker @ Springfield City Hall"] is True


# ---------------------------------------------------------------- selector


def test_ml_posting_swaps_in_reserve_ml_content(bank):
    posting = Posting.from_text(
        "Machine Learning Engineer Intern",
        "Train PyTorch deep learning models for computer vision. Python data pipelines.",
    )
    selection = select(bank, posting)
    names = [e.name for e, _ in selection.experiences]
    assert "Research Assistant @ Example Vision Lab" in names
    assert "Open Source Fellow @ Example Fellowship" not in names  # flexible slot swapped
    assert "Software Engineering Intern @ Acme Cloud" in names  # real jobs always stay
    assert "Student IT Worker @ Springfield City Hall" in names
    projects = [e.name for e, _ in selection.projects]
    assert projects[0] == "Indexer — Code Search Engine"  # flagship anchor stays first
    assert "VisionLab — Defect Detector" in projects
    assert "PyTorch" in selection.matched_skills
    total_master = sum(len(e.bullets) for e in bank.entries if e.active)
    assert len(selection.bullets) <= total_master


def test_systems_posting_keeps_live_content_and_orders_skills(bank):
    posting = Posting.from_text(
        "Backend Software Engineer Intern",
        "Python, PostgreSQL, REST APIs, Docker, Kubernetes, CI/CD, React, TypeScript, "
        "operating systems, concurrency.",
    )
    selection = select(bank, posting)
    assert not selection.swapped_in  # nothing in reserve beats the live entries
    assert [e.name for e, _ in selection.projects][1:] != []
    assert selection.skills["Languages"][0] in ("Python", "SQL")
    assert set(selection.skills["Languages"]) == set(bank.skills["Languages"])  # nothing added
    assert "Kubernetes" in selection.matched_skills


def test_live_entries_keep_their_opening_bullet_first(bank):
    posting = Posting.from_text("SRE Intern", "Docker Kubernetes release automation.")
    selection = select(bank, posting)
    acme, bullets = selection.experiences[0]
    assert bullets[0] is acme.bullets[0]


# ---------------------------------------------------------------- guard / polish


def test_guard_accepts_faithful_rewrite_and_rejects_fabrication(bank):
    original = bank.experiences[0].bullets[0]  # billing service, 40 teams
    corpus = bank.plain_corpus().lower()
    ok = "Built a Python billing service on PostgreSQL that exposes REST APIs to 40 internal teams."
    assert guard(original, ok, bank, corpus) is None
    assert "new numbers" in guard(original, ok.replace("40", "45"), bank, corpus)
    assert "skill not in resume" in guard(original, ok.replace("PostgreSQL", "Kafka"), bank, corpus)
    assert "name or term" in guard(original, ok.replace("internal", "Google"), bank, corpus)
    assert "length" in guard(original, "Built a service.", bank, corpus)


def test_to_tex_rebolds_original_phrases(bank):
    original = bank.experiences[0].bullets[1]  # bold "cutting release time 60%"
    tex = to_tex(
        "Containerized deploys with Docker and Kubernetes, cutting release time 60%.", original
    )
    assert r"\textbf{cutting release time 60\%}" in tex


def test_polish_applies_only_guarded_rewrites(bank):
    bullets = bank.experiences[0].bullets[:2]
    reply = json.dumps(
        [
            {
                "id": bullets[0].id,
                "text": "Built a Python and PostgreSQL billing service whose REST APIs serve 40 internal teams.",
            },
            {
                "id": bullets[1].id,
                "text": "Containerized deployments with Docker, Kubernetes and Terraform, cutting release time 60%.",
            },
        ]
    )
    outcome = polish(bank, bullets, ["REST APIs"], "Backend Intern", runner=lambda prompt: reply)
    assert bullets[0].id in outcome.accepted
    assert outcome.rejected[bullets[1].id].startswith("skill not in resume: Terraform")


def test_polish_failures_never_break_tailoring(bank):
    def broken(prompt):
        raise RuntimeError("401 OAuth access token is invalid")

    outcome = polish(bank, bank.experiences[0].bullets, [], "x", runner=broken)
    assert outcome.skipped_reason.startswith("polish failed")
    assert polish(bank, [], [], "x", runner=None).skipped_reason == "Claude Code CLI not available"
    assert polish(bank, bank.projects[0].bullets, [], "x", runner=lambda p: "sorry").skipped_reason


# ---------------------------------------------------------------- render / ATS / tailor


def test_render_reuses_template_and_only_bank_content(bank):
    posting = Posting.from_text("ML Intern", "PyTorch computer vision Python")
    tex = render(bank, select(bank, posting))
    assert tex.startswith(bank.preamble.rstrip()[:200])
    assert "\\section{Experience}" in tex and tex.rstrip().endswith("\\end{document}")
    assert "Example Vision Lab" in tex
    assert "Did some ML stuff" not in tex
    assert r"C\#" in tex  # skills re-escaped


def test_ats_report_separates_shown_hidden_and_true_gaps(bank):
    posting = Posting.from_text("Backend Intern", "Python, Kafka, PyTorch, PostgreSQL")
    resume_text = (
        "alex@example.com 555-010-0199 Education Experience Projects Skills "
        + "x " * 300
        + " Python PostgreSQL"
    )
    report = analyse(resume_text, posting, bank, pages=1, baseline_text="Python")
    assert report.matched == ["Python", "PostgreSQL"]
    assert report.in_bank_not_shown == ["PyTorch"]
    assert report.true_gaps == ["Kafka"]
    assert report.passed_checks
    assert report.baseline_coverage == 0.25
    assert "real gaps" in render_markdown(report, "Backend Intern", "Acme")


def test_tailor_writes_outputs_without_compiler(bank, tmp_path):
    result = tailor(
        bank,
        title="ML Intern",
        company="Acme AI",
        description="PyTorch computer vision Python",
        out_dir=tmp_path,
        compile_pdf=False,
    )
    assert (tmp_path / "resume.tex").exists() and (tmp_path / "ats.md").exists()
    meta = json.loads((tmp_path / "meta.json").read_text())
    assert meta["company"] == "Acme AI"
    assert "Research Assistant @ Example Vision Lab" in meta["swapped_in"]
    assert meta["polish_skipped"] == "not requested"
    assert result.pdf_path is None


@pytest.mark.skipif(find_pdflatex() is None, reason="pdflatex (TinyTeX) not installed")
def test_tailor_compiles_one_page_pdf(bank, tmp_path):
    result = tailor(
        bank,
        title="Backend Intern",
        company="Acme",
        description="Python PostgreSQL REST APIs Docker Kubernetes",
        out_dir=tmp_path,
    )
    assert result.compile_error is None
    assert result.pdf_path is not None and result.pdf_path.exists()
    assert result.report.pages == 1
    assert (
        "Alex Example" in result.report.__dict__.get("matched", [])
        or result.report.checks["email present"]
    )
