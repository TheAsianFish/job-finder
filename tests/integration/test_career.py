"""Applications log + tailored-resume delivery, end to end (Discord mocked)."""

from __future__ import annotations

import json
from datetime import timedelta

import pytest
import respx
from httpx import Response

from opportunity_radar.db import repositories as repo
from opportunity_radar.db.engine import get_engine, reset_engine, session_scope
from opportunity_radar.db.tables import Base, JobRow
from opportunity_radar.insights.outcomes import collect
from opportunity_radar.models.company import CompanySource
from opportunity_radar.notifications.discord import DiscordNotifier
from opportunity_radar.resume import ledger
from opportunity_radar.resume.deliver import deliver_pending, pending_jobs
from opportunity_radar.utilities.dates import utcnow
from tests.conftest import load_fixture
from tests.unit.test_db import alias_hashes, make_record

WEBHOOK = "https://discord.com/api/webhooks/777/career"


@pytest.fixture()
def private(tmp_path, monkeypatch):
    root = tmp_path / "private"
    root.mkdir()
    (root / "resume.tex").write_text(load_fixture("resume_sample.tex"), encoding="utf-8")
    monkeypatch.setenv("OPPORTUNITY_RADAR_PRIVATE_DIR", str(root))
    return root


@pytest.fixture()
def db(tmp_path):
    reset_engine()
    url = f"sqlite:///{tmp_path}/career.db"
    Base.metadata.create_all(get_engine(url))
    with session_scope(url) as session:
        repo.sync_companies(session, [CompanySource(id="stripe", name="Stripe", tier="core")])
    yield url
    reset_engine()


def _insert(db_url, job_id, title, *, alerted=False, description="Python PostgreSQL REST APIs"):
    with session_scope(db_url) as session:
        record = make_record(job_id, title).model_copy(update={"description_text": description})
        row = repo.insert_job(session, record, alias_hashes(record))
        if alerted:
            row.alerted_at = utcnow() - timedelta(minutes=5)
        return row.id, row.apply_url


def test_ledger_round_trip_and_upsert(tmp_path):
    path = tmp_path / "applications.yaml"
    ledger.upsert(
        path,
        "https://boards.greenhouse.io/stripe/jobs/1?utm_source=x",
        status="applied",
        company="Stripe",
        title="SWE Intern",
        resume="backend",
    )
    ledger.upsert(path, "https://boards.greenhouse.io/stripe/jobs/1", status="interview")
    apps = ledger.load(path)
    assert len(apps) == 1  # same posting (tracking params ignored)
    assert apps[0].status == "interview" and apps[0].resume == "backend"
    assert path.read_text().startswith("# Applications log")
    with pytest.raises(ValueError):
        ledger.upsert(path, "https://x.example/1", status="ghosted")


def test_ledger_sync_feeds_outcomes(db, tmp_path):
    _, url = _insert(db, "11", "Software Engineer Intern")
    path = tmp_path / "applications.yaml"
    ledger.upsert(path, url, status="oa", resume="backend", referral="Sam")
    ledger.upsert(path, "https://unknown.example/jobs/9", status="applied")
    with session_scope(db) as session:
        result = ledger.sync_to_db(session, ledger.load(path))
        assert result.matched == 1 and result.unmatched == ["https://unknown.example/jobs/9"]
        dims = collect(session)
    assert dims["Overall"]["all"].responded == 1
    assert dims["Resume version"]["backend"].applied == 1
    assert dims["Referral"]["yes"].applied == 1


@respx.mock
async def test_deliver_sends_pdf_or_message_and_marks_job(db, private):
    job_id, _ = _insert(db, "21", "Backend Engineer Intern", alerted=True)
    _insert(db, "22", "Old Intern Role")  # never alerted: not delivered
    assert pending_jobs(db) == [job_id]
    route = respx.post(WEBHOOK).mock(return_value=Response(204))
    report = await deliver_pending(DiscordNotifier(WEBHOOK), db_url=db, push=False)
    assert report.delivered == ["Stripe: Backend Engineer Intern"]
    assert route.called
    request = route.calls[0].request
    body = request.content.decode("latin-1")
    assert "Tailored resume for" in body
    out_dirs = list((private / "tailored").iterdir())
    assert len(out_dirs) == 1 and (out_dirs[0] / "ats.md").exists()
    meta = json.loads((out_dirs[0] / "meta.json").read_text())
    assert meta["job_id"] == job_id
    with session_scope(db) as session:
        assert session.get(JobRow, job_id).resume_sent_at is not None
    assert pending_jobs(db) == []  # never sent twice
    assert report.git == "private dir is not a git repo; saved locally only"


async def test_deliver_without_resume_source_skips_cleanly(db, tmp_path, monkeypatch):
    monkeypatch.setenv("OPPORTUNITY_RADAR_PRIVATE_DIR", str(tmp_path / "missing"))
    _insert(db, "31", "Backend Engineer Intern", alerted=True)
    report = await deliver_pending(DiscordNotifier(None), db_url=db, push=False)
    assert report.pending == 1 and report.skipped_reason.startswith("no resume source")
