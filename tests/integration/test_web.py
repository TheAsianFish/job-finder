"""Dashboard integration tests via FastAPI TestClient."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from opportunity_radar.db import repositories as repo
from opportunity_radar.db.engine import get_engine, reset_engine, session_scope
from opportunity_radar.db.tables import Base
from opportunity_radar.models.company import CompanySource
from opportunity_radar.web.app import create_app
from opportunity_radar.web.schemas import csrf_token
from tests.unit.test_db import alias_hashes, make_record


@pytest.fixture()
def client(tmp_path, monkeypatch):
    reset_engine()
    url = f"sqlite:///{tmp_path}/web.db"
    monkeypatch.setenv("OPPORTUNITY_RADAR_DB_URL", url)
    from opportunity_radar.config import get_settings

    get_settings.cache_clear()
    engine = get_engine(url)
    Base.metadata.create_all(engine)
    with session_scope(url) as session:
        repo.sync_companies(session, [CompanySource(id="stripe", name="Stripe", tier="core")])
        record = make_record("1", "Software Engineer Intern - Summer 2027")
        repo.insert_job(session, record, alias_hashes(record))
    yield TestClient(create_app())
    reset_engine()
    get_settings.cache_clear()


def test_home_renders(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Opportunity Radar" in response.text


def test_jobs_list_and_filters(client):
    response = client.get("/jobs")
    assert response.status_code == 200
    assert "Software Engineer Intern - Summer 2027" in response.text
    filtered = client.get("/jobs", params={"q": "nonexistent-xyz"})
    assert "No jobs match" in filtered.text


def test_job_detail_shows_apply_link(client):
    response = client.get("/jobs/1")
    assert response.status_code == 200
    assert "boards.greenhouse.io/stripe/jobs/1" in response.text
    assert "Apply on employer site" in response.text


def test_job_detail_404(client):
    assert client.get("/jobs/999").status_code == 404


def test_status_change_requires_csrf(client):
    bad = client.post("/jobs/1/status", data={"status": "saved", "csrf": "wrong"})
    assert bad.status_code == 403
    good = client.post(
        "/jobs/1/status",
        data={"status": "saved", "csrf": csrf_token()},
        follow_redirects=False,
    )
    assert good.status_code == 303
    detail = client.get("/jobs/1")
    assert "saved" in detail.text


def test_description_html_is_escaped(client, tmp_path):
    url = f"sqlite:///{tmp_path}/web.db"
    with session_scope(url) as session:
        record = make_record("2", "XSS Test Intern")
        record = record.model_copy(
            update={"description_text": "<script>alert('xss')</script> build software"}
        )
        repo.insert_job(session, record, alias_hashes(record))
        job_id = repo.list_jobs(session, search="XSS")[0].id
    response = client.get(f"/jobs/{job_id}")
    assert "<script>alert" not in response.text
    assert "&lt;script&gt;" in response.text


def test_companies_and_health_pages(client):
    assert client.get("/companies").status_code == 200
    assert client.get("/health").status_code == 200
    assert client.get("/settings").status_code == 200
