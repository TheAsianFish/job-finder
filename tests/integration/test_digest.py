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


def test_non_software_roles_never_reach_digest(db):
    """Score alone must not carry a non-SWE role into any digest section."""
    with session_scope(db) as session:
        repo.sync_companies(session, [CompanySource(id="stripe", name="Stripe")])
        record = make_record("50", "Civil Engineering Internship")
        record.role_family = "irrelevant"
        row = repo.insert_job(session, record, alias_hashes(record))
        row.match_score = 73.0
        row.digest_pending = True
        repo.record_change(session, row.id, "season", "unspecified", "spring 2027", True)
    assert build_digest(AppSettings(), db_url=db) is None


def test_non_us_roles_never_reach_digest(db):
    """A Lisbon-based SWE intern is not workable for a US-only candidate."""
    with session_scope(db) as session:
        repo.sync_companies(session, [CompanySource(id="stripe", name="Stripe")])
        record = make_record("60", "Software Engineer Intern - Summer 2027")
        record.all_locations = ["Lisbon, Portugal"]
        record.primary_location = "Lisbon, Portugal"
        row = repo.insert_job(session, record, alias_hashes(record))
        row.match_score = 78.0
        row.digest_pending = True
        repo.record_change(session, row.id, "season", "unspecified", "summer 2027", True)
    assert build_digest(AppSettings(), db_url=db) is None


def test_digest_sections_ordered_by_score(db):
    """Sections truncate to 10 lines, so entries must be best-first."""
    with session_scope(db) as session:
        repo.sync_companies(session, [CompanySource(id="stripe", name="Stripe")])
        for job_id, title, score in (
            ("40", "Okay Engineer Intern", 62.0),
            ("41", "Great Engineer Intern", 79.0),
            ("42", "Good Engineer Intern", 70.0),
        ):
            record = make_record(job_id, title)
            row = repo.insert_job(session, record, alias_hashes(record))
            row.match_score = score
            row.digest_pending = True
    payload = build_digest(AppSettings(), db_url=db)
    assert payload is not None
    text = json.dumps(payload)
    assert text.index("Great") < text.index("Good") < text.index("Okay")


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


def test_digest_caps_lines_per_company(db):
    with session_scope(db) as session:
        repo.sync_companies(
            session,
            [
                CompanySource(id="bigco", name="BigCo", tier="core"),
                CompanySource(id="smallco", name="SmallCo", tier="broad"),
            ],
        )
        for i in range(6):
            record = make_record(f"big-{i}", f"Software Engineer Intern {i} - Summer 2027")
            record = record.model_copy(update={"company_id": "bigco", "company_name": "BigCo"})
            row = repo.insert_job(session, record, alias_hashes(record))
            row.match_score = 90.0 - i
            row.digest_pending = True
        record = make_record("small-1", "Backend Engineer Intern - Summer 2027")
        record = record.model_copy(update={"company_id": "smallco", "company_name": "SmallCo"})
        row = repo.insert_job(session, record, alias_hashes(record))
        row.match_score = 80.0
        row.digest_pending = True
    payload = build_digest(AppSettings(), db_url=db)
    assert payload is not None
    section = next(f for f in payload["embeds"][0]["fields"] if f["name"] == "New high-priority")
    lines = section["value"].splitlines()
    # 3 BigCo lines + the SmallCo line + one overflow note.
    assert sum("BigCo" in line and "SmallCo" not in line for line in lines[:-1]) == 3
    assert any("SmallCo" in line for line in lines)
    assert "3 more at BigCo" in lines[-1]


def test_digest_flags_silent_zero_job_sources(db):
    with session_scope(db) as session:
        repo.sync_companies(
            session,
            [
                CompanySource(id="stripe", name="Stripe", tier="core"),
                CompanySource(id="quietco", name="QuietCo", tier="broad"),
            ],
        )
        repo.update_source_state_success(session, "quietco", 0)
        record = make_record("q1", "Software Engineer Intern - Summer 2027")
        row = repo.insert_job(session, record, alias_hashes(record))
        row.match_score = 70.0
        row.digest_pending = True
    payload = build_digest(AppSettings(), db_url=db)
    text = json.dumps(payload)
    assert "returning 0 jobs" in text
    assert "quietco" in text


def test_digest_keeps_internships_and_aligned_full_time_roles(db):
    settings = AppSettings()  # default policy: full_time_roles = aligned
    with session_scope(db) as session:
        repo.sync_companies(session, [CompanySource(id="stripe", name="Stripe", tier="core")])
        for job_id, title in (
            ("i1", "Backend Engineer Intern"),
            ("g1", "Graduate Software Engineer"),
            ("f1", "Mission Software Engineer"),
        ):
            record = make_record(job_id, title)
            row = repo.insert_job(session, record, alias_hashes(record))
            row.match_score = 70.0
            row.digest_pending = True
    text = json.dumps(build_digest(settings, db_url=db))
    assert "Backend Engineer Intern" in text
    assert "Graduate Software Engineer" in text
    assert "Mission Software Engineer" not in text

    settings.profile.preferences.full_time_roles = "never"
    with session_scope(db) as session:
        for row in repo.list_jobs(session, limit=10):
            row.digest_pending = True
    text = json.dumps(build_digest(settings, db_url=db))
    assert "Backend Engineer Intern" in text
    assert "Graduate Software Engineer" not in text


def test_disabled_sources_do_not_raise_silent_warnings(db):
    settings = AppSettings()
    settings.companies = [
        CompanySource(id="stripe", name="Stripe", tier="core"),
        CompanySource(id="canva", name="Canva", tier="broad", enabled=False),
        CompanySource(id="quietco", name="QuietCo", tier="broad"),
    ]
    with session_scope(db) as session:
        repo.sync_companies(session, settings.companies)
        repo.update_source_state_success(session, "canva", 0)
        repo.update_source_state_success(session, "quietco", 0)
        record = make_record("q1", "Software Engineer Intern - Summer 2027")
        row = repo.insert_job(session, record, alias_hashes(record))
        row.match_score = 70.0
        row.digest_pending = True
    text = json.dumps(build_digest(settings, db_url=db))
    assert "quietco" in text
    assert "canva" not in text


def test_digest_skips_roles_already_applied_or_dismissed(db):
    with session_scope(db) as session:
        repo.sync_companies(session, [CompanySource(id="stripe", name="Stripe", tier="core")])
        ids = {}
        for job_id, title in (
            ("a1", "Backend Engineer Intern"),
            ("a2", "Platform Engineer Intern"),
            ("a3", "Data Engineer Intern"),
        ):
            record = make_record(job_id, title)
            row = repo.insert_job(session, record, alias_hashes(record))
            row.match_score = 70.0
            row.digest_pending = True
            ids[title] = row.id
        repo.set_application_status(session, ids["Backend Engineer Intern"], "applied")
        repo.set_application_status(session, ids["Platform Engineer Intern"], "dismissed")
    text = json.dumps(build_digest(AppSettings(), db_url=db))
    assert "Data Engineer Intern" in text
    assert "Backend Engineer Intern" not in text and "Platform Engineer Intern" not in text
