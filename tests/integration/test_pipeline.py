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


@respx.mock
async def test_newly_added_source_is_baselined_on_its_own(db, settings):
    """Adding a company to a live registry imports its board without alerts."""
    payload = gh_payload()
    respx.get(API_URL).mock(return_value=Response(200, json=payload))
    await scan_companies([company()], settings, db_url=db)  # DB-level baseline

    other_url = "https://boards-api.greenhouse.io/v1/boards/newco/jobs?content=true"
    # Distinct apply URLs: identical URLs would (correctly) merge across sources.
    payload = json.loads(
        json.dumps(payload).replace("boards.greenhouse.io/acmecorp", "boards.greenhouse.io/newco")
    )
    respx.get(other_url).mock(return_value=Response(200, json=payload))
    newco = CompanySource(
        id="newco",
        name="NewCo",
        tier="core",
        adapter="greenhouse",
        adapter_config={"board_token": "newco"},
    )
    summary = await scan_companies([company(), newco], settings, db_url=db)
    assert summary.baseline is False
    assert summary.total_new == 3
    assert summary.immediate_job_ids == []
    assert summary.digest_job_ids == []
    assert summary.baselined_company_ids == ["newco"]
    # The Summer 2027 intern role is worth summarising once; the rest are not.
    assert len(summary.baselined_job_ids) >= 1
    with session_scope(db) as session:
        rows = [j for j in repo.list_jobs(session, limit=100) if j.company_id == "newco"]
        assert rows and all(j.is_baseline for j in rows)
        assert not any(j.digest_pending for j in rows)

    # Once live, a genuinely new posting on that source alerts normally.
    new_job = dict(payload["jobs"][0])
    new_job.update(
        id=5011099,
        title="Software Engineer Intern - Spring 2027",
        absolute_url="https://boards.greenhouse.io/newco/jobs/5011099",
    )
    grown = dict(payload)
    grown["jobs"] = [*payload["jobs"], new_job]
    respx.get(other_url).mock(return_value=Response(200, json=grown))
    summary3 = await scan_companies([newco], settings, db_url=db)
    assert summary3.baselined_company_ids == []
    assert len(summary3.immediate_job_ids) == 1


@respx.mock
async def test_repointed_silent_source_is_baselined_too(db, settings):
    """A seed that previously scanned 'successfully' with 0 jobs gets a
    per-source baseline once it finally returns a real board."""
    payload = gh_payload()
    respx.get(API_URL).mock(return_value=Response(200, json=payload))
    await scan_companies([company()], settings, db_url=db)
    with session_scope(db) as session:
        repo.update_source_state_success(session, "silentco", 0)  # months of 0 jobs

    silent_url = "https://boards-api.greenhouse.io/v1/boards/silentco/jobs?content=true"
    fixed = json.loads(
        json.dumps(payload).replace(
            "boards.greenhouse.io/acmecorp", "boards.greenhouse.io/silentco"
        )
    )
    respx.get(silent_url).mock(return_value=Response(200, json=fixed))
    silentco = CompanySource(
        id="silentco",
        name="SilentCo",
        tier="strong",
        adapter="greenhouse",
        adapter_config={"board_token": "silentco"},
    )
    summary = await scan_companies([silentco], settings, db_url=db)
    assert summary.baselined_company_ids == ["silentco"]
    assert summary.immediate_job_ids == [] and summary.digest_job_ids == []


@respx.mock
async def test_detail_skipping_adapter_keeps_stored_description(db, settings):
    """When a per-posting-detail adapter skips a known posting, the stored
    description survives and no bogus 'description changed' row appears."""
    wd_company = CompanySource(
        id="wdco",
        name="WdCo",
        tier="strong",
        adapter="workday",
        adapter_config={"host": "acme.wd5.myworkdayjobs.com", "site": "AcmeCareers"},
    )
    respx.get("https://acme.wd5.myworkdayjobs.com/robots.txt").mock(
        return_value=Response(200, text="User-agent: *\nAllow: /\n")
    )
    respx.post("https://acme.wd5.myworkdayjobs.com/wday/cxs/acme/AcmeCareers/jobs").mock(
        return_value=Response(200, text=load_fixture("workday_jobs.json"))
    )
    template = json.loads(load_fixture("workday_detail.json"))

    def detail_for(request):
        # The shared fixture carries one req id; echo the one from the path
        # so the three postings stay distinct, as on a real tenant.
        req_id = str(request.url).rsplit("_", 1)[1]
        body = json.loads(json.dumps(template))
        info = body["jobPostingInfo"]
        info["jobReqId"] = req_id
        # A real tenant's detail title matches its listing title.
        info["title"] = {
            "JR100001": "2027 Software Engineering Intern",
            "JR100002": "Software Engineer, New College Grad",
            "JR100003": "Senior Software Engineer, Compilers",
        }[req_id]
        info["externalUrl"] = f"https://acme.wd5.myworkdayjobs.com/AcmeCareers/job/x/{req_id}"
        return Response(200, json=body)

    detail = respx.get(url__regex=r".*/wday/cxs/acme/AcmeCareers/job/.*").mock(
        side_effect=detail_for
    )
    await scan_companies([wd_company], settings, db_url=db)
    first_detail_calls = detail.call_count
    assert first_detail_calls == 3
    with session_scope(db) as session:
        rows = {j.source_job_id: j for j in repo.list_jobs(session, limit=100)}
        assert "Summer 2027" in rows["JR100001"].description_text

    summary = await scan_companies([wd_company], settings, db_url=db)
    assert detail.call_count == first_detail_calls  # nothing re-fetched
    assert summary.total_changed == 0
    with session_scope(db) as session:
        rows = {j.source_job_id: j for j in repo.list_jobs(session, limit=100)}
        assert "Summer 2027" in rows["JR100001"].description_text
        # Detail-derived fields survive the listing-only re-scan too.
        assert rows["JR100001"].all_locations == ["US, CA, Santa Clara", "US, TX, Austin"]
        assert rows["JR100001"].apply_url.endswith("/job/x/JR100001")
        assert rows["JR100001"].posted_at is not None
        assert session.query(JobChangeRow).count() == 0


SIMPLIFY_URL = (
    "https://raw.githubusercontent.com/SimplifyJobs/Summer2027-Internships/dev/"
    ".github/scripts/listings.json"
)


def _simplify_source() -> CompanySource:
    return CompanySource(
        id="simplify-internships",
        name="Simplify internships list",
        tier="broad",
        adapter="simplify",
        adapter_config={"url": SIMPLIFY_URL},
    )


@respx.mock
async def test_simplify_feed_alerts_big_tech_and_skips_direct_employers(db, settings):
    settings.companies = [
        CompanySource(id="google", name="Google", tier="core", enabled=False),
        CompanySource(id="stripe", name="Stripe", tier="core", adapter="greenhouse"),
        CompanySource(id="sig", name="SIG", tier="core", enabled=False),
        _simplify_source(),
    ]
    listings = json.loads(load_fixture("simplify_listings.json"))
    route = respx.get(SIMPLIFY_URL).mock(return_value=Response(200, json=listings))
    # Seed the DB so the global first-run guard does not apply.
    respx.get(API_URL).mock(return_value=Response(200, json=gh_payload()))
    await scan_companies([company()], settings, db_url=db)

    first = await scan_companies([_simplify_source()], settings, db_url=db)
    assert first.baselined_company_ids == ["simplify-internships"]  # per-source baseline
    assert first.immediate_job_ids == []

    new = dict(listings[0])
    new.update(
        id="aaaa0099-0000-0000-0000-000000000099",
        title="Software Engineering Intern, BS/MS",
        url="https://www.google.com/about/careers/applications/jobs/results/1099",
    )
    route.mock(return_value=Response(200, json=[*listings, new]))
    second = await scan_companies([_simplify_source()], settings, db_url=db)
    assert second.total_new == 1
    assert len(second.immediate_job_ids) == 1  # core-tier Summer 2027 intern

    with session_scope(db) as session:
        rows = [j for j in repo.list_jobs(session, limit=500) if j.source_adapter == "simplify"]
        by_company = {j.company_id for j in rows}
        assert "google" in by_company
        assert "acme-robotics" in by_company and "sig" in by_company
        assert "stripe" not in by_company  # employer scanned directly: skipped
        assert all(j.source_name == "simplify-internships" for j in rows)
        google = next(j for j in rows if j.source_job_id.endswith("99"))
        assert google.season == "summer" and google.season_year == 2027
        assert repo.get_company(session, "acme-robotics") is not None

    # Simplify retires the posting -> closed after two clean misses.
    route.mock(return_value=Response(200, json=listings))
    await scan_companies([_simplify_source()], settings, db_url=db)
    await scan_companies([_simplify_source()], settings, db_url=db)
    with session_scope(db) as session:
        google = next(
            j for j in repo.list_jobs(session, limit=500) if j.source_job_id.endswith("99")
        )
        assert google.status == "closed"
        # The primary source's jobs are untouched by the secondary closure pass.
        assert all(
            j.status == "active"
            for j in repo.list_jobs(session, limit=500)
            if j.company_id == "acmecorp"
        )


@respx.mock
async def test_unchanged_postings_take_fast_path_and_decay_like_full_rescore(
    db, settings, monkeypatch
):
    from datetime import UTC, datetime, timedelta

    from opportunity_radar.pipeline import normalizer as normalizer_mod
    from opportunity_radar.pipeline import scanner as scanner_mod

    # Same UTC day: the fingerprint deliberately includes the date (expired
    # target windows), so crossing midnight would force a full re-score.
    start = datetime(2026, 10, 7, 1, 0, tzinfo=UTC)
    monkeypatch.setattr(scanner_mod, "utcnow", lambda: start)
    respx.get(API_URL).mock(return_value=Response(200, json=gh_payload()))
    await scan_companies([company()], settings, db_url=db)  # baseline, full normalise

    calls = {"n": 0}
    real_normalize = normalizer_mod.normalize

    def counting(*args, **kwargs):
        calls["n"] += 1
        return real_normalize(*args, **kwargs)

    monkeypatch.setattr(normalizer_mod, "normalize", counting)
    later = start + timedelta(hours=20)
    monkeypatch.setattr(scanner_mod, "utcnow", lambda: later)
    summary = await scan_companies([company()], settings, db_url=db)
    assert calls["n"] == 0  # nothing re-normalised
    assert summary.total_changed == 0

    with session_scope(db) as session:
        rows = repo.list_jobs(session, limit=100)
        assert all(abs((ensure(j.last_seen_at) - later).total_seconds()) < 1 for j in rows)
        fast = {j.source_job_id: (j.match_score, j.score_components.get("freshness")) for j in rows}
        # Same answer as a full re-score at the same moment.
        for j in rows:
            raw_payload = next(x for x in gh_payload()["jobs"] if str(x["id"]) == j.source_job_id)
            from opportunity_radar.adapters.greenhouse import GreenhouseAdapter

            raw = GreenhouseAdapter()._to_raw(raw_payload, "acmecorp")
            full = real_normalize(
                raw, company(), settings, first_seen_at=ensure(j.first_seen_at), now=later
            )
            assert fast[j.source_job_id] == (
                full.match_score,
                full.score_components.get("freshness", fast[j.source_job_id][1]),
            )
            assert any(
                r.startswith("First seen ") and "20 hours" in r for r in j.match_reasons
            ) or (j.match_score == 0.0)


@respx.mock
async def test_scoring_change_invalidates_fast_path(db, settings, monkeypatch):
    from opportunity_radar.pipeline import normalizer as normalizer_mod

    respx.get(API_URL).mock(return_value=Response(200, json=gh_payload()))
    await scan_companies([company()], settings, db_url=db)

    calls = {"n": 0}
    real_normalize = normalizer_mod.normalize

    def counting(*args, **kwargs):
        calls["n"] += 1
        return real_normalize(*args, **kwargs)

    monkeypatch.setattr(normalizer_mod, "normalize", counting)
    settings.scoring.company_tier_points["core"] = 24.0  # e.g. tune adjusted a weight
    await scan_companies([company()], settings, db_url=db)
    assert calls["n"] == 3  # every stored job re-scored once, not twice
    with session_scope(db) as session:
        assert all(
            j.score_components.get("company_quality") in (24.0, None)
            for j in repo.list_jobs(session, limit=100)
        )


def ensure(value):
    from opportunity_radar.utilities.dates import ensure_utc

    return ensure_utc(value)


@respx.mock
async def test_legacy_merged_requisitions_split_quietly_and_stop_flip_flopping(db, settings):
    """Rows merged before AD-14/AD-23 carry a sibling's identity alias. The
    sibling is split out once, without an alert, and nothing flips after."""
    from opportunity_radar.db.tables import JobAliasRow
    from opportunity_radar.utilities.hashing import identity_hash as make_identity

    payload = gh_payload()
    respx.get(API_URL).mock(return_value=Response(200, json=payload))
    await scan_companies([company()], settings, db_url=db)

    sibling = dict(payload["jobs"][0])
    sibling.update(id=4011777, absolute_url="https://boards.greenhouse.io/acmecorp/jobs/4011777")
    with session_scope(db) as session:
        merged_into = next(
            j for j in repo.list_jobs(session, limit=10) if j.source_job_id == "4011001"
        )
        session.add(
            JobAliasRow(
                job_id=merged_into.id,
                alias_kind="identity",
                alias_hash=make_identity("greenhouse", "acmecorp", "4011777"),
                source_adapter="greenhouse",
                source_job_id="4011777",
                url=sibling["absolute_url"],
                first_seen_at=merged_into.first_seen_at,
            )
        )
    grown = dict(payload)
    grown["jobs"] = [*payload["jobs"], sibling]
    respx.get(API_URL).mock(return_value=Response(200, json=grown))

    split = await scan_companies([company()], settings, db_url=db)
    assert split.total_new == 0 and split.immediate_job_ids == []
    steady = await scan_companies([company()], settings, db_url=db)
    assert steady.total_changed == 0
    with session_scope(db) as session:
        ids = sorted(j.source_job_id for j in repo.list_jobs(session, limit=10))
        assert ids == ["4011001", "4011002", "4011003", "4011777"]
        assert next(
            j for j in repo.list_jobs(session, limit=10) if j.source_job_id == "4011777"
        ).is_baseline
