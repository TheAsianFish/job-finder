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
