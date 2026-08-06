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
