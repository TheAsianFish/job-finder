"""Database layer tests against an in-memory-ish temp SQLite file."""

from __future__ import annotations

import pytest

from opportunity_radar.db import repositories as repo
from opportunity_radar.db.engine import get_engine, reset_engine, session_scope
from opportunity_radar.db.tables import Base
from opportunity_radar.models.company import CompanySource
from opportunity_radar.models.job import JobRecord
from opportunity_radar.utilities.dates import utcnow
from opportunity_radar.utilities.hashing import (
    content_hash,
    fuzzy_key_hash,
    identity_hash,
    url_hash,
)


@pytest.fixture()
def db(tmp_path):
    reset_engine()
    url = f"sqlite:///{tmp_path}/test.db"
    engine = get_engine(url)
    Base.metadata.create_all(engine)
    yield url
    reset_engine()


def make_record(source_job_id: str = "123", title: str = "Software Engineer Intern") -> JobRecord:
    now = utcnow()
    return JobRecord(
        source_name="stripe",
        source_adapter="greenhouse",
        source_job_id=source_job_id,
        company_id="stripe",
        company_name="Stripe",
        title=title,
        normalized_title=title,
        role_family="general_swe",
        description_text="Build payments infrastructure.",
        all_locations=["San Francisco, CA"],
        primary_location="San Francisco, CA",
        first_seen_at=now,
        last_seen_at=now,
        apply_url=f"https://boards.greenhouse.io/stripe/jobs/{source_job_id}",
        canonical_url=f"https://boards.greenhouse.io/stripe/jobs/{source_job_id}",
        source_url="https://boards-api.greenhouse.io/v1/boards/stripe/jobs",
        content_hash=content_hash(title, "Build payments infrastructure.", ["San Francisco, CA"]),
        identity_hash=identity_hash("greenhouse", "stripe", source_job_id),
    )


def alias_hashes(record: JobRecord) -> dict[str, str]:
    return {
        "identity": record.identity_hash,
        "url": url_hash(record.apply_url),
        "fuzzy": fuzzy_key_hash(record.company_id, record.normalized_title, record.all_locations),
    }


def test_company_sync_and_lookup(db):
    companies = [
        CompanySource(id="stripe", name="Stripe", tier="core", adapter="greenhouse"),
        CompanySource(id="ramp", name="Ramp", tier="strong", adapter="ashby"),
    ]
    with session_scope(db) as session:
        assert repo.sync_companies(session, companies) == 2
    with session_scope(db) as session:
        rows = repo.list_companies(session)
        assert {r.id for r in rows} == {"stripe", "ramp"}
        assert repo.get_company(session, "stripe").tier == "core"


def test_insert_and_find_job_by_all_alias_kinds(db):
    record = make_record()
    with session_scope(db) as session:
        repo.sync_companies(session, [CompanySource(id="stripe", name="Stripe")])
        repo.insert_job(session, record, alias_hashes(record))
    with session_scope(db) as session:
        by_identity = repo.find_job_by_alias(session, {"identity": record.identity_hash})
        by_url = repo.find_job_by_alias(session, {"url": url_hash(record.apply_url)})
        by_fuzzy = repo.find_job_by_alias(
            session,
            {"fuzzy": fuzzy_key_hash("stripe", record.normalized_title, record.all_locations)},
        )
        assert by_identity is not None
        assert by_url is not None and by_url.id == by_identity.id
        assert by_fuzzy is not None and by_fuzzy.id == by_identity.id


def test_application_status_transitions(db):
    record = make_record()
    with session_scope(db) as session:
        repo.sync_companies(session, [CompanySource(id="stripe", name="Stripe")])
        row = repo.insert_job(session, record, alias_hashes(record))
        job_id = row.id
    with session_scope(db) as session:
        app = repo.set_application_status(session, job_id, "saved")
        assert app.saved_at is not None
    with session_scope(db) as session:
        app = repo.set_application_status(
            session, job_id, "applied", resume_variant="backend_infrastructure"
        )
        assert app.applied_at is not None
        assert app.resume_variant == "backend_infrastructure"


def test_source_state_failure_then_success(db):
    with session_scope(db) as session:
        assert repo.update_source_state_failure(session, "stripe", "boom") == 1
        assert repo.update_source_state_failure(session, "stripe", "boom") == 2
    with session_scope(db) as session:
        repo.update_source_state_success(session, "stripe", 42)
    with session_scope(db) as session:
        state = repo.get_source_state(session, "stripe")
        assert state.consecutive_failures == 0
        assert state.last_job_count == 42


def test_meta_roundtrip(db):
    with session_scope(db) as session:
        repo.meta_set(session, "baseline_done", "1")
    with session_scope(db) as session:
        assert repo.meta_get(session, "baseline_done") == "1"
        assert repo.meta_get(session, "missing") is None


def test_list_jobs_filters(db):
    with session_scope(db) as session:
        repo.sync_companies(session, [CompanySource(id="stripe", name="Stripe")])
        a = make_record("1", "Software Engineer Intern")
        b = make_record("2", "Senior Staff Accountant")
        repo.insert_job(session, a, alias_hashes(a))
        repo.insert_job(session, b, alias_hashes(b))
    with session_scope(db) as session:
        results = repo.list_jobs(session, search="intern")
        assert len(results) == 1
        assert results[0].title == "Software Engineer Intern"
