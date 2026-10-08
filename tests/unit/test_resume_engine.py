"""Resume engine: parse -> bank -> select -> guarded polish -> render -> ATS."""

from __future__ import annotations

import json

import pytest

from opportunity_radar.resume.ats import analyse, render_markdown
from opportunity_radar.resume.bank import build_bank
from opportunity_radar.resume.compiler import find_pdflatex
from opportunity_radar.resume.latex import escape, find_macros, split_sections, to_plain
from opportunity_radar.resume.polish import (
    build_prompt,
    guard_bullet,
    headline_metrics,
    rewrite_entries,
    to_tex,
)
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


def test_ml_posting_reshuffles_projects_but_never_experience(bank):
    posting = Posting.from_text(
        "Machine Learning Engineer Intern",
        "Train PyTorch deep learning models for computer vision. Python data pipelines.",
    )
    selection = select(bank, posting)
    names = [e.name for e, _ in selection.experiences]
    # Experience is fixed (AD-31): every live entry, no reserve swaps.
    assert names == [
        e.name
        for e in sorted(
            (e for e in bank.experiences if e.active), key=lambda e: e.start, reverse=True
        )
    ]
    assert "Research Assistant @ Example Vision Lab" not in names
    projects = [e.name for e, _ in selection.projects]
    assert "VisionLab — Defect Detector" in projects  # projects reshuffle freely
    assert projects[0] == "VisionLab — Defect Detector"  # most relevant first
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


# ---------------------------------------------------------------- guarded story rewrite


def _entry_fixture(bank):
    from opportunity_radar.resume.selector import Posting, select

    selection = select(bank, Posting.from_text("Backend Intern", "Python PostgreSQL REST APIs"))
    return selection.experiences[:1]  # (Acme entry, its bullets)


def test_guard_bullet_checks_numbers_skills_names_length(bank):
    entry, _ = _entry_fixture(bank)[0]
    entry_text = " ".join(b.text for b in entry.bullets) + " " + entry.name
    numbers = {"40", "60"}
    corpus = bank.plain_corpus().lower()
    good = (
        "Architected a Python and PostgreSQL billing service with idempotent REST APIs consumed "
        "by 40 internal teams, cutting release time 60% via containerized deploys."
    )
    assert guard_bullet(good, numbers, bank, corpus, entry_text) is None
    assert "numbers" in guard_bullet(good.replace("40", "45"), numbers, bank, corpus, entry_text)
    assert "skill not in resume" in guard_bullet(
        good.replace("PostgreSQL", "Kafka"), numbers, bank, corpus, entry_text
    )
    assert "name or term" in guard_bullet(
        good.replace("internal", "Google"), numbers, bank, corpus, entry_text
    )
    assert "length" in guard_bullet("Built a service.", numbers, bank, corpus, entry_text)
    # Generic engineering acronyms are fine even if the resume never spells them...
    with_acronym = good.replace("REST APIs", "REST APIs under an SLA")
    assert guard_bullet(with_acronym, numbers, bank, corpus, entry_text) is None
    # ...but "p99" smuggles in a latency number nobody measured.
    with_p99 = good.replace("REST APIs", "REST APIs with p99 latency")
    assert "numbers" in guard_bullet(with_p99, numbers, bank, corpus, entry_text)


def test_to_tex_bolds_only_whole_headline_metrics(bank):
    tex = to_tex(
        "Cut release time 60% by containerizing deploys with Docker and Kubernetes.", ["60%"]
    )
    assert r"\textbf{60\%}" in tex
    assert r"\textbf" not in to_tex("Served 40 teams.", ["60%"])
    # A range is never bolded in fragments.
    ranged = to_tex(
        "Cut latency over 90% (2.5-3s to ~200ms) with memoized selectors.", ["90%", "3s"]
    )
    assert r"\textbf{90\%}" in ranged and r"\textbf{3s}" not in ranged


def test_headline_metrics_come_from_bold_phrases(bank):
    acme = bank.experiences[0]
    assert headline_metrics(acme.bullets) == ["60%"]


def test_prompt_carries_story_direction_and_job_description(bank):
    entries = _entry_fixture(bank)
    prompt = build_prompt(
        entries,
        title="Backend Intern",
        company="Acme",
        description="We value reliability.",
        skills_line="Python, PostgreSQL",
    )
    for phrase in ("STAR", "engineering vocabulary", "We value reliability.", "bullets_to_write"):
        assert phrase in prompt


def test_rewrite_entries_accepts_safe_stories_and_rejects_fabrication(bank):
    entries = _entry_fixture(bank)
    entry, shown = entries[0]
    good = [
        "Architected a Python/PostgreSQL billing service with REST APIs for 40 internal teams.",
        "Cut release time 60% by containerizing deploys with Docker and Kubernetes rollouts.",
        "Diagnosed an invoice-queue race condition and locked in the fix with unit tests.",
    ][: len(shown)]
    reply = json.dumps({"entries": [{"id": entry.id, "bullets": good}]})
    outcome = rewrite_entries(
        bank,
        entries,
        title="Backend Intern",
        company="Acme",
        description="",
        runner=lambda p: reply,
    )
    assert entry.id in outcome.accepted and len(outcome.accepted[entry.id]) == len(shown)

    bad = list(good)
    bad[0] = bad[0].replace("PostgreSQL", "Kafka")
    reply = json.dumps({"entries": [{"id": entry.id, "bullets": bad}]})
    outcome = rewrite_entries(
        bank, entries, title="x", company="y", description="", runner=lambda p: reply
    )
    assert entry.id not in outcome.accepted  # all-or-nothing per entry
    assert outcome.rejected[entry.id].startswith("skill not in resume: Kafka")

    short = json.dumps({"entries": [{"id": entry.id, "bullets": good[:1]}]})
    outcome = rewrite_entries(
        bank, entries, title="x", company="y", description="", runner=lambda p: short
    )
    assert "expected" in outcome.rejected[entry.id]


def test_rewrite_failures_never_break_tailoring(bank):
    def broken(prompt):
        raise RuntimeError("401 OAuth access token is invalid")

    entries = _entry_fixture(bank)
    kwargs = dict(title="x", company="y", description="")
    assert rewrite_entries(bank, entries, runner=broken, **kwargs).skipped_reason.startswith(
        "rewrite failed"
    )
    assert (
        rewrite_entries(bank, entries, runner=None, **kwargs).skipped_reason
        == "Claude Code CLI not available"
    )
    assert rewrite_entries(bank, entries, runner=lambda p: "sorry", **kwargs).skipped_reason


# ---------------------------------------------------------------- render / ATS / tailor


def test_render_reuses_template_and_only_bank_content(bank):
    posting = Posting.from_text("ML Intern", "PyTorch computer vision Python")
    tex = render(bank, select(bank, posting))
    assert tex.startswith(bank.preamble.rstrip()[:200])
    assert "\\section{Experience}" in tex and tex.rstrip().endswith("\\end{document}")
    assert "VisionLab" in tex  # reserve project swapped in
    assert "Example Vision Lab" not in tex  # reserve experience never is
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
    assert meta["swapped_in"] == ["VisionLab — Defect Detector"]
    assert meta["proposals"] == []
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


def test_reviewer_swaps_replace_the_weakest_project_only(bank):
    posting = Posting.from_text("Backend Intern", "Python PostgreSQL REST APIs Docker Kubernetes")
    plain = select(bank, posting)
    assert "VisionLab — Defect Detector" not in [e.name for e, _ in plain.projects]
    swapped = select(bank, posting, prefer=["Swap the dashboard for the VisionLab defect detector"])
    names = [e.name for e, _ in swapped.projects]
    assert "VisionLab — Defect Detector" in names
    assert len(names) == len(plain.projects)
    assert "VisionLab — Defect Detector" in swapped.swapped_in
    lab = select(bank, posting, prefer=["Example Vision Lab research assistant role"])
    assert "Research Assistant @ Example Vision Lab" not in [e.name for e, _ in lab.experiences]


def test_rewrite_rejects_entries_that_grow_the_page(bank):
    entries = _entry_fixture(bank)
    entry, shown = entries[0]
    padded = [
        (b.text + " Delivered with careful review and documentation for the team.")[:130]
        for b in shown
    ]
    reply = json.dumps({"entries": [{"id": entry.id, "bullets": padded}]})
    outcome = rewrite_entries(
        bank, entries, title="x", company="y", description="", runner=lambda p: reply
    )
    assert "over budget" in outcome.rejected.get(entry.id, "")
