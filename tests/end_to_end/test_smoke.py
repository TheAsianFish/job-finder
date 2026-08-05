"""End-to-end smoke test (spec §23.4).

A fake Greenhouse-style careers source publishes a job, updates it, then
removes it. Verifies: baseline import, one immediate alert with the direct
apply link, no duplicate alert, meaningful-change tracking, and closure —
with Discord fully mocked.
"""

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
from opportunity_radar.notifications.discord import DiscordNotifier
from opportunity_radar.pipeline.scanner import scan_companies

API_URL = "https://boards-api.greenhouse.io/v1/boards/fakeco/jobs?content=true"
WEBHOOK = "https://discord.com/api/webhooks/999/test"


@pytest.fixture()
def db(tmp_path):
    reset_engine()
    url = f"sqlite:///{tmp_path}/e2e.db"
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
        id="fakeco",
        name="FakeCo",
        tier="core",
        adapter="greenhouse",
        adapter_config={"board_token": "fakeco"},
    )


def job_payload(job_id: int, title: str, content: str) -> dict:
    return {
        "id": job_id,
        "title": title,
        "updated_at": "2026-08-05T10:00:00-04:00",
        "first_published": "2026-08-05T09:00:00-04:00",
        "location": {"name": "San Francisco, CA"},
        "absolute_url": f"https://boards.greenhouse.io/fakeco/jobs/{job_id}",
        "content": content,
        "departments": [],
        "offices": [],
    }


GOOD_CONTENT = (
    "Build production distributed systems in Python and Java with Docker, "
    "Kubernetes, and PostgreSQL. Backend cloud infrastructure at scale. "
    "Must be graduating between December 2026 and June 2028."
)


@respx.mock
async def test_full_lifecycle(db, settings):
    webhook_calls: list[dict] = []

    def capture(request):
        webhook_calls.append(json.loads(request.content))
        return Response(204)

    respx.post(WEBHOOK).mock(side_effect=capture)
    notifier = DiscordNotifier(WEBHOOK)

    # --- Phase 1: baseline with one existing job -------------------------
    baseline_job = job_payload(1, "Software Engineer Intern - Summer 2027", GOOD_CONTENT)
    route = respx.get(API_URL).mock(return_value=Response(200, json={"jobs": [baseline_job]}))
    summary = await scan_companies([company()], settings, db_url=db)
    assert summary.baseline
    assert summary.total_new == 1
    assert not summary.immediate_job_ids
    await notifier.send_baseline_summary(db_url=db)
    assert len(webhook_calls) == 1
    assert "Baseline import complete" in json.dumps(webhook_calls[0])

    # --- Phase 2: a new Spring 2027 role is published --------------------
    new_job = job_payload(2, "Backend Engineer Intern - Spring 2027", GOOD_CONTENT)
    route.mock(return_value=Response(200, json={"jobs": [baseline_job, new_job]}))
    summary = await scan_companies([company()], settings, db_url=db)
    assert summary.total_new == 1
    assert len(summary.immediate_job_ids) == 1
    sent = await notifier.send_immediate_alerts(summary.immediate_job_ids, db_url=db)
    assert sent == 1
    alert = webhook_calls[-1]
    embed = alert["embeds"][0]
    assert embed["url"] == "https://boards.greenhouse.io/fakeco/jobs/2"
    assert "Spring 2027" in embed["title"]
    assert alert["allowed_mentions"] == {"parse": []}
    link_field = next(f for f in embed["fields"] if f["name"] == "Links")
    assert "boards.greenhouse.io/fakeco/jobs/2" in link_field["value"]

    # Re-sending the same ids must not re-alert (never alert twice).
    assert await notifier.send_immediate_alerts(summary.immediate_job_ids, db_url=db) == 0

    # --- Phase 3: the job is updated (title/season change) ----------------
    updated = dict(new_job)
    updated["title"] = "Backend Engineer Intern - Fall 2027"
    route.mock(return_value=Response(200, json={"jobs": [baseline_job, updated]}))
    summary = await scan_companies([company()], settings, db_url=db)
    assert summary.total_changed == 1
    with session_scope(db) as session:
        fields = {
            c.field
            for c in session.query(JobChangeRow).filter(JobChangeRow.meaningful).all()
        }
        assert "title" in fields and "season" in fields

    # --- Phase 4: the job disappears -> closed after 2 successful scans ---
    route.mock(return_value=Response(200, json={"jobs": [baseline_job]}))
    summary = await scan_companies([company()], settings, db_url=db)
    assert summary.total_closed == 0  # first miss
    summary = await scan_companies([company()], settings, db_url=db)
    assert summary.total_closed == 1  # second miss closes it
    with session_scope(db) as session:
        closed = repo.list_jobs(session, status="closed")
        assert len(closed) == 1
        assert closed[0].title == "Backend Engineer Intern - Fall 2027"
        # The direct apply link is preserved on the closed record.
        assert closed[0].apply_url == "https://boards.greenhouse.io/fakeco/jobs/2"
