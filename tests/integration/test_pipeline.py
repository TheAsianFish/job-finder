"""Integration tests: fetch (mocked) -> normalize -> persist -> dedupe -> close."""

from __future__ import annotations

import json

import pytest
import respx
from httpx import Response

from opportunity_radar.config import AppSettings
from opportunity_radar.db import repositories as repo
from opportunity_radar.db.engine import get_engine, reset_engine, session_scope
from opportunity_radar.db.tables import Base, JobChangeRow
from opportunity_radar.models.company import CompanySource
from opportunity_radar.pipeline.scanner import scan_companies
from tests.conftest import load_fixture

API_URL = "https://boards-api.greenhouse.io/v1/boards/acmecorp/jobs?content=true"


@pytest.fixture()
def db(tmp_path):
    reset_engine()
    url = f"sqlite:///{tmp_path}/pipeline.db"
    engine = get_engine(url)
    Base.metadata.create_all(engine)
    yield url
    reset_engine()


@pytest.fixture()
def settings():
    config = AppSettings()
    config.scheduler.retries = 0
    config.scheduler.backoff_seconds = [0.01]
    return config


def company() -> CompanySource:
    return CompanySource(
        id="acmecorp",
        name="AcmeCorp",
        tier="core",
        adapter="greenhouse",
        adapter_config={"board_token": "acmecorp"},
    )


def gh_payload() -> dict:
    return json.loads(load_fixture("greenhouse_jobs.json"))


@respx.mock
async def test_baseline_then_new_job_alerts_once(db, settings):
    payload = gh_payload()
    route = respx.get(API_URL).mock(return_value=Response(200, json=payload))

    # First run: auto-baseline (empty DB), no alerts even without --baseline.
    summary1 = await scan_companies([company()], settings, db_url=db)
    assert summary1.baseline is True
    assert summary1.total_new == 3
    assert summary1.immediate_job_ids == []
    with session_scope(db) as session:
        assert repo.count_jobs(session) == 3

    # Second run, unchanged: nothing new, nothing changed.
    summary2 = await scan_companies([company()], settings, db_url=db)
    assert summary2.baseline is False
    assert summary2.total_new == 0
    assert summary2.total_changed == 0

    # Third run: a brand-new Spring role appears -> exactly one immediate alert.
    new_job = dict(payload["jobs"][0])
    new_job.update(
        id=4011099,
        title="Software Engineer Intern - Spring 2027",
        absolute_url="https://boards.greenhouse.io/acmecorp/jobs/4011099",
        first_published="2026-08-05T08:00:00-04:00",
        updated_at="2026-08-05T08:00:00-04:00",
    )
    payload["jobs"].append(new_job)
    route.mock(return_value=Response(200, json=payload))
    summary3 = await scan_companies([company()], settings, db_url=db)
    assert summary3.total_new == 1
    assert len(summary3.immediate_job_ids) == 1

    # Fourth run with same data: the same job must not alert again.
    summary4 = await scan_companies([company()], settings, db_url=db)
    assert summary4.total_new == 0
    assert summary4.immediate_job_ids == []


@respx.mock
async def test_change_detection_records_meaningful_change(db, settings):
    payload = gh_payload()
    route = respx.get(API_URL).mock(return_value=Response(200, json=payload))
    await scan_companies([company()], settings, db_url=db)

    changed = json.loads(load_fixture("greenhouse_jobs.json"))
    changed["jobs"][0]["title"] = "Software Engineer Intern - Winter 2027"
    route.mock(return_value=Response(200, json=changed))
    summary = await scan_companies([company()], settings, db_url=db)
    assert summary.total_changed == 1

    with session_scope(db) as session:
        rows = session.query(JobChangeRow).filter(JobChangeRow.meaningful).all()
        fields = {r.field for r in rows}
        assert "title" in fields
        assert "season" in fields


@respx.mock
async def test_closure_after_two_missing_scans_not_after_failure(db, settings):
    payload = gh_payload()
    route = respx.get(API_URL).mock(return_value=Response(200, json=payload))
    await scan_companies([company()], settings, db_url=db)

    # Remove one job from the feed.
    smaller = json.loads(load_fixture("greenhouse_jobs.json"))
    removed = smaller["jobs"].pop(0)
    route.mock(return_value=Response(200, json=smaller))

    # Miss 1: still active.
    await scan_companies([company()], settings, db_url=db)
    with session_scope(db) as session:
        jobs = repo.active_jobs_for_company(session, "acmecorp")
        assert len(jobs) == 3  # still counted active

    # A FAILED scan in between must not advance the miss counter.
    route.mock(return_value=Response(500, text="boom"))
    failed = await scan_companies([company()], settings, db_url=db)
    assert failed.failures

    # Miss 2 (successful): now closed.
    route.mock(return_value=Response(200, json=smaller))
    summary = await scan_companies([company()], settings, db_url=db)
    assert summary.total_closed == 1
    with session_scope(db) as session:
        closed_title = removed["title"]
        all_jobs = repo.list_jobs(session, status="closed")
        assert any(j.title == closed_title for j in all_jobs)


@respx.mock
async def test_zero_drop_anomaly_does_not_close_all(db, settings):
    payload = gh_payload()
    route = respx.get(API_URL).mock(return_value=Response(200, json=payload))
    await scan_companies([company()], settings, db_url=db)
    # Pretend the source had >= 5 jobs previously.
    with session_scope(db) as session:
        state = repo.get_source_state(session, "acmecorp")
        state.last_job_count = 80

    route.mock(return_value=Response(200, json={"jobs": []}))
    summary = await scan_companies([company()], settings, db_url=db)
    assert summary.total_closed == 0
    with session_scope(db) as session:
        assert len(repo.active_jobs_for_company(session, "acmecorp")) == 3


@respx.mock
async def test_dedupe_same_job_from_two_adapters(db, settings):
    # Greenhouse first.
    respx.get(API_URL).mock(return_value=Response(200, json=gh_payload()))
    await scan_companies([company()], settings, db_url=db)

    # The same role then appears via JSON-LD on the company site with the
    # same title and location -> fuzzy identity must match, not duplicate.
    html = """
    <html><head><script type="application/ld+json">
    {"@type": "JobPosting",
     "title": "Software Engineer Intern - Summer 2027",
     "description": "Same role, careers-site copy.",
     "jobLocation": {"@type": "Place", "address": {"addressLocality": "San Francisco", "addressRegion": "CA"}},
     "url": "https://acmecorp.example/careers/swe-intern"}
    </script></head></html>
    """
    respx.get("https://acmecorp.example/robots.txt").mock(return_value=Response(404))
    respx.get("https://acmecorp.example/careers").mock(return_value=Response(200, text=html))
    jsonld_company = CompanySource(
        id="acmecorp",
        name="AcmeCorp",
        tier="core",
        adapter="jsonld",
        career_urls=["https://acmecorp.example/careers"],
    )
    summary = await scan_companies([jsonld_company], settings, db_url=db)
    assert summary.total_new == 0  # merged into the existing job
    with session_scope(db) as session:
        job = repo.list_jobs(session, search="Summer 2027")[0]
        alias_urls = {a.url for a in job.aliases}
        assert any("acmecorp.example" in (u or "") for u in alias_urls)


@respx.mock
async def test_location_fuzzy_mismatch_creates_separate_job(db, settings):
    respx.get(API_URL).mock(return_value=Response(200, json=gh_payload()))
    await scan_companies([company()], settings, db_url=db)

    html = """
    <html><head><script type="application/ld+json">
    {"@type": "JobPosting",
     "title": "Software Engineer Intern - Summer 2027",
     "description": "Different city listing.",
     "jobLocation": {"@type": "Place", "address": {"addressLocality": "Toronto", "addressCountry": "CA"}},
     "url": "https://acmecorp.example/careers/swe-intern-toronto"}
    </script></head></html>
    """
    respx.get("https://acmecorp.example/robots.txt").mock(return_value=Response(404))
    respx.get("https://acmecorp.example/careers").mock(return_value=Response(200, text=html))
    jsonld_company = CompanySource(
        id="acmecorp",
        name="AcmeCorp",
        tier="core",
        adapter="jsonld",
        career_urls=["https://acmecorp.example/careers"],
    )
    summary = await scan_companies([jsonld_company], settings, db_url=db)
    assert summary.total_new == 1  # different location set -> distinct job
