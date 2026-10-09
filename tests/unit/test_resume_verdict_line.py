"""The alert's resume line when a listing arrives without its description."""

from __future__ import annotations

import pytest

from opportunity_radar.resume import verdict
from opportunity_radar.resume.describe import can_fetch


@pytest.fixture
def resume(tmp_path, monkeypatch):
    source = tmp_path / "resume.tex"
    source.write_text("% resume")
    monkeypatch.setattr(verdict, "resume_source", lambda: source)


def test_can_fetch_only_public_ats_links():
    assert can_fetch("https://job-boards.greenhouse.io/acme/jobs/123")
    assert can_fetch("https://jobs.lever.co/acme/0f0e0d0c-0b0a-0908-0706-050403020100")
    assert can_fetch("https://acme.wd5.myworkdayjobs.com/en-US/Careers/job/Remote/SWE_R1")
    assert not can_fetch("https://www.tesla.com/careers/search/job/intern-246810")
    assert not can_fetch("")


def test_company_site_listing_says_why_it_was_not_assessed(resume):
    line = verdict.resume_fit_line(
        "Intern", "", important=True, apply_url="https://www.tesla.com/careers/search/job/1"
    )
    assert line is not None
    assert "company's own careers site" in line and "no full description" not in line


def test_fetchable_listing_says_what_happens_next(resume):
    url = "https://job-boards.greenhouse.io/acme/jobs/123"
    assert "review follows here" in (verdict.resume_fit_line("I", "", True, url) or "")
    assert "review-role check" in (verdict.resume_fit_line("I", "", False, url) or "")


def test_no_resume_means_no_line(tmp_path, monkeypatch):
    monkeypatch.setattr(verdict, "resume_source", lambda: tmp_path / "missing.tex")
    assert verdict.resume_fit_line("I", "", True, "https://x") is None
