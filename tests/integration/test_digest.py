"""Digest builder + sender tests against a temp DB with a mocked webhook."""

from __future__ import annotations

import json
from datetime import timedelta

import pytest
import respx
from httpx import Response

from opportunity_radar.config import AppSettings
from opportunity_radar.db import repositories as repo
from opportunity_radar.db.engine import get_engine, reset_engine, session_scope
from opportunity_radar.db.tables import Base, JobRow
from opportunity_radar.models.company import CompanySource
from opportunity_radar.notifications.digest import build_digest, send_digest
from opportunity_radar.notifications.discord import DiscordNotifier
from opportunity_radar.utilities.dates import utcnow
from tests.unit.test_db import alias_hashes, make_record

WEBHOOK = "https://discord.com/api/webhooks/321/digest"


@pytest.fixture()
def db(tmp_path):
    reset_engine()
    url = f"sqlite:///{tmp_path}/digest.db"
    engine = get_engine(url)
    Base.metadata.create_all(engine)
    yield url
    reset_engine()


def _seed(db_url: str) -> int:
    with session_scope(db_url) as session:
        repo.sync_companies(session, [CompanySource(id="stripe", name="Stripe", tier="core")])
        record = make_record("10", "Platform Engineer Intern - Spring 2027")
        row = repo.insert_job(session, record, alias_hashes(record))
        row.match_score = 88.0
        row.digest_pending = True
        job_id = row.id
        # Approaching deadline on a saved application.
        app = repo.set_application_status(session, job_id, "saved")
        app.deadline = (utcnow() + timedelta(days=3)).date()
        # Meaningful change entry.
        repo.record_change(session, job_id, "season", "unspecified", "spring 2027", True)
        # A source that keeps failing.
        for _ in range(3):
            repo.update_source_state_failure(session, "stripe", "HTTP 500")
    return job_id


def test_build_digest_sections(db):
    _seed(db)
    payload = build_digest(AppSettings(), db_url=db)
    assert payload is not None
    text = json.dumps(payload)
    assert "New high-priority" in text
    assert "Deadlines approaching" in text
    assert "Changed / reopened" in text
    assert "Source failures" in text
    assert "Platform Engineer Intern" in text


def test_build_digest_empty_returns_none(db):
    assert build_digest(AppSettings(), db_url=db) is None


def test_changed_section_excludes_low_score_jobs(db):
    """Senior/non-SWE roles (scored below the digest bar) never reach the digest."""
    with session_scope(db) as session:
        repo.sync_companies(session, [CompanySource(id="stripe", name="Stripe")])
        record = make_record("20", "Senior Software Engineer")
        row = repo.insert_job(session, record, alias_hashes(record))
        row.match_score = 0.0  # hard-excluded titles score 0
        repo.record_change(session, row.id, "description", None, "similarity 66%", True)
    assert build_digest(AppSettings(), db_url=db) is None


def test_changed_section_only_reports_since_last_digest(db):
    """A change already covered by the previous digest is not repeated."""
    with session_scope(db) as session:
        repo.sync_companies(session, [CompanySource(id="stripe", name="Stripe")])
        record = make_record("30", "Software Engineer Intern - Summer 2027")
        row = repo.insert_job(session, record, alias_hashes(record))
        row.match_score = 75.0
        repo.record_change(session, row.id, "season", "unspecified", "summer 2027", True)

    # No digest yet: the change is reported.
    assert build_digest(AppSettings(), db_url=db) is not None

    # After a digest has covered it, it must not appear again.
    with session_scope(db) as session:
        repo.meta_set(session, "last_digest_at", utcnow().isoformat())
    assert build_digest(AppSettings(), db_url=db) is None


@respx.mock
async def test_send_digest_empty_sends_quiet_notice(db):
    """An empty digest still tells the channel 'no new updates'."""
    route = respx.post(WEBHOOK).mock(return_value=Response(204))
    ok = await send_digest(AppSettings(), DiscordNotifier(WEBHOOK), db_url=db)
    assert ok
    assert route.call_count == 1
    body = json.loads(route.calls[0].request.content)
    assert "No new updates" in json.dumps(body)
    with session_scope(db) as session:
        assert repo.meta_get(session, "last_digest_at") is not None


@respx.mock
async def test_send_digest_clears_pending(db):
    _seed(db)
    respx.post(WEBHOOK).mock(return_value=Response(204))
    ok = await send_digest(AppSettings(), DiscordNotifier(WEBHOOK), db_url=db)
    assert ok
    with session_scope(db) as session:
        pending = session.query(JobRow).filter(JobRow.digest_pending).count()
        assert pending == 0
        assert repo.meta_get(session, "last_digest_at") is not None
