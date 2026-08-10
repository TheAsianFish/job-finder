"""Regression: alias hashes colliding across different jobs must not crash.

Scenario: two distinct jobs exist; one changes title/location so its fuzzy
key now equals the other job's fuzzy key. The alias table has a unique
(kind, hash) constraint — registration must skip hashes already owned by a
different job instead of raising IntegrityError and killing the whole scan.
"""

from __future__ import annotations

import pytest

from opportunity_radar.db import repositories as repo
from opportunity_radar.db.engine import get_engine, reset_engine, session_scope
from opportunity_radar.db.tables import Base
from opportunity_radar.pipeline import deduper
from opportunity_radar.pipeline.normalizer import alias_hashes_for
from tests.unit.test_db import alias_hashes, make_record


@pytest.fixture()
def db(tmp_path):
    reset_engine()
    url = f"sqlite:///{tmp_path}/collision.db"
    engine = get_engine(url)
    Base.metadata.create_all(engine)
    yield url
    reset_engine()


def test_fuzzy_collision_with_other_job_does_not_crash(db):
    from opportunity_radar.models.company import CompanySource

    with session_scope(db) as session:
        repo.sync_companies(session, [CompanySource(id="stripe", name="Stripe")])
        job_a = make_record("1", "Software Engineer Intern")
        job_b = make_record("2", "Platform Engineer Intern")
        repo.insert_job(session, job_a, alias_hashes(job_a))
        repo.insert_job(session, job_b, alias_hashes(job_b))

    # Job B's title changes to exactly match job A's title/location: its new
    # fuzzy hash collides with job A's existing fuzzy alias.
    changed_b = make_record("2", "Software Engineer Intern")
    with session_scope(db) as session:
        existing = deduper.find_existing(session, changed_b)
        assert existing is not None
        # Identity match must win over the fuzzy collision: it is still job B.
        assert existing.source_job_id == "2"
        repo.apply_record_to_row(existing, changed_b)
        # Must not raise IntegrityError even though the fuzzy hash is owned by A.
        deduper.register(session, existing, changed_b)

    with session_scope(db) as session:
        assert repo.count_jobs(session) == 2  # still two distinct jobs


def test_distinct_requisitions_with_same_title_and_location_stay_separate(db):
    """Same board, same title+location, different job IDs — two real jobs.

    Boards like Greenhouse post shift/team variants with identical titles and
    locations. The fuzzy key must not merge them: merging makes the stored
    description flip-flop between the variants on every scan, flooding the
    digest with bogus 'description changed' rows.
    """
    from opportunity_radar.models.company import CompanySource

    job_a = make_record("100", "Security Software Engineer (Starlink)")
    job_b = make_record("200", "Security Software Engineer (Starlink)")
    job_b.description_text = "A different requisition for the same title."
    job_b.content_hash = "different-content"

    with session_scope(db) as session:
        repo.sync_companies(session, [CompanySource(id="stripe", name="Stripe")])
        repo.insert_job(session, job_a, alias_hashes(job_a))

    with session_scope(db) as session:
        # Fuzzy hash matches job A, but the concrete IDs differ: not the same job.
        assert deduper.find_existing(session, job_b) is None
        # Insert must not crash on the fuzzy (kind, hash) already owned by A.
        repo.insert_job(session, job_b, alias_hashes(job_b))

    with session_scope(db) as session:
        assert repo.count_jobs(session) == 2
        # Each job is still findable by its own identity.
        for rec in (job_a, job_b):
            found = deduper.find_existing(session, rec)
            assert found is not None
            assert found.source_job_id == rec.source_job_id


def test_fuzzy_match_still_bridges_different_sources(db):
    """Cross-source dedup stays intact: same posting via another adapter merges."""
    from opportunity_radar.models.company import CompanySource

    job_a = make_record("100")
    with session_scope(db) as session:
        repo.sync_companies(session, [CompanySource(id="stripe", name="Stripe")])
        repo.insert_job(session, job_a, alias_hashes(job_a))

    via_jsonld = make_record("100")
    via_jsonld.source_adapter = "jsonld"
    via_jsonld.apply_url = "https://stripe.com/jobs/listing/12345"
    via_jsonld.identity_hash = "jsonld-identity-hash"
    with session_scope(db) as session:
        found = deduper.find_existing(session, via_jsonld)
        assert found is not None
        assert found.source_job_id == "100"


def test_register_is_idempotent(db):
    from opportunity_radar.models.company import CompanySource

    with session_scope(db) as session:
        repo.sync_companies(session, [CompanySource(id="stripe", name="Stripe")])
        record = make_record("1")
        row = repo.insert_job(session, record, alias_hashes_for(record))
        deduper.register(session, row, record)
        deduper.register(session, row, record)
    with session_scope(db) as session:
        job = repo.get_job(session, 1)
        assert len(job.aliases) == 3
