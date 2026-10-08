"""Fit assessment, ATS description fetching, Simplify CSV import, ledger merges."""

from __future__ import annotations

import respx
from httpx import Response

from opportunity_radar.resume import ledger
from opportunity_radar.resume.assess import assess
from opportunity_radar.resume.bank import build_bank
from opportunity_radar.resume.describe import fetch_description
from opportunity_radar.resume.review import Review, render_markdown
from opportunity_radar.resume.selector import Posting
from opportunity_radar.resume.simplify_import import parse_simplify_csv
from tests.conftest import load_fixture

BANK = build_bank(load_fixture("resume_sample.tex"))
MASTER = (
    "Python PostgreSQL REST APIs Docker Kubernetes C# SQL Server FastAPI React TypeScript "
    "ChromaDB Git CI/CD unit tests virtual memory page fault LLM"
)


def test_fitting_role_is_quiet():
    posting = Posting.from_text(
        "Backend Engineer Intern", "Python PostgreSQL REST APIs Docker Kubernetes"
    )
    fit = assess(BANK, posting, MASTER)
    assert fit.severity == "fits" and not fit.needs_attention


def test_headline_skill_missing_from_resume_is_a_gap():
    posting = Posting.from_text("Rust Systems Intern", "Rust, Kafka, Terraform, Go tooling, Linux.")
    fit = assess(BANK, posting, MASTER)
    assert fit.severity == "gap"
    assert "Rust" in fit.headline_gaps and "Rust" in fit.true_gaps
    assert any("centres on Rust" in r for r in fit.reasons)


def test_hidden_material_triggers_tune():
    posting = Posting.from_text(
        "Software Engineer Intern", "Python, PyTorch, deep learning, computer vision, Docker."
    )
    fit = assess(BANK, posting, MASTER)
    assert fit.severity == "tune"
    assert {"PyTorch", "Computer vision"} <= set(fit.hidden_skills)


def test_review_markdown_without_model_still_explains_flags():
    fit = assess(BANK, Posting.from_text("Rust Intern", "Rust Kafka Terraform Go"), MASTER)
    text = render_markdown(Review(error="not requested"), fit, title="Rust Intern", company="Acme")
    assert "Severity: GAP" in text and "Why this was flagged" in text and "not requested" in text


@respx.mock
def test_fetch_description_for_each_ats():
    respx.get("https://boards-api.greenhouse.io/v1/boards/acme/jobs/123").mock(
        return_value=Response(
            200, json={"content": "&lt;p&gt;Build &lt;b&gt;Rust&lt;/b&gt; services&lt;/p&gt;"}
        )
    )
    lever_id = "0f2e3d4c-5b6a-7980-1a2b-3c4d5e6f7a8b"
    respx.get(f"https://api.lever.co/v0/postings/acme/{lever_id}").mock(
        return_value=Response(
            200,
            json={
                "descriptionPlain": "Lever role",
                "lists": [{"text": "You", "content": "<li>Python</li>"}],
            },
        )
    )
    ashby_id = "11111111-2222-3333-4444-555555555555"
    respx.get("https://api.ashbyhq.com/posting-api/job-board/acme").mock(
        return_value=Response(
            200, json={"jobs": [{"id": ashby_id, "descriptionPlain": "Ashby role"}]}
        )
    )
    respx.get("https://acme.wd5.myworkdayjobs.com/wday/cxs/acme/Ext/job/US/SWE-Intern_R1").mock(
        return_value=Response(
            200, json={"jobPostingInfo": {"jobDescription": "<p>Workday role</p>"}}
        )
    )
    greenhouse = fetch_description("https://boards.greenhouse.io/acme/jobs/123")
    assert greenhouse is not None and "Rust" in greenhouse and "services" in greenhouse
    assert "Python" in fetch_description(f"https://jobs.lever.co/acme/{lever_id}")
    assert fetch_description(f"https://jobs.ashbyhq.com/acme/{ashby_id}") == "Ashby role"
    assert "Workday role" in fetch_description(
        "https://acme.wd5.myworkdayjobs.com/en-US/Ext/job/US/SWE-Intern_R1"
    )
    assert fetch_description("https://careers.example.com/jobs/1") is None


def test_simplify_csv_import_maps_statuses_and_skips_saved(tmp_path):
    csv_path = tmp_path / "simplify.csv"
    csv_path.write_text(
        "Company Name,Position Title,Location,Status,Date Applied,Job Link\n"
        "Stripe,Software Engineer Intern,SF,Applied,10/01/2026,https://stripe.com/jobs/1\n"
        "Google,SWE Intern,MTV,Interviewing,2026-09-20,\n"
        "Meta,Production Engineer Intern,Menlo Park,Rejected,Sep 15, 2026,\n"
        "Notion,Backend Intern,NYC,Saved,,\n",
        encoding="utf-8",
    )
    apps, skipped = parse_simplify_csv(csv_path)
    by_company = {a.company: a for a in apps}
    assert skipped == 1  # Notion was only saved
    assert by_company["Stripe"].status == "applied" and by_company["Stripe"].applied == "2026-10-01"
    assert by_company["Google"].status == "interview" and by_company["Google"].url == ""
    assert by_company["Meta"].status == "rejected"


def test_ledger_merge_is_idempotent_and_forward_only(tmp_path):
    path = tmp_path / "applications.yaml"
    first = [ledger.Application(company="Google", title="SWE Intern", status="interview")]
    assert ledger.merge(path, first) == (1, 0)
    assert ledger.merge(path, first) == (0, 0)  # same export again: no change
    older = [
        ledger.Application(
            company="Google", title="SWE Intern", status="applied", url="https://g.co/1"
        )
    ]
    assert ledger.merge(path, older) == (0, 1)  # gains the URL, keeps "interview"
    app = ledger.load(path)[0]
    assert app.status == "interview" and app.url == "https://g.co/1"
