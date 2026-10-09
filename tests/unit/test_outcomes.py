from datetime import date, timedelta

from opportunity_radar.db import repositories as repo
from opportunity_radar.db.engine import get_engine, reset_engine, session_scope
from opportunity_radar.db.tables import Base
from opportunity_radar.insights.outcomes import MIN_SAMPLE, collect, render
from opportunity_radar.models.company import CompanySource
from tests.unit.test_db import alias_hashes, make_record


def test_outcome_funnel_by_dimension(tmp_path):
    reset_engine()
    url = f"sqlite:///{tmp_path}/outcomes.db"
    Base.metadata.create_all(get_engine(url))
    with session_scope(url) as session:
        repo.sync_companies(session, [CompanySource(id="stripe", name="Stripe", tier="core")])
        statuses = ["applied", "oa", "interview", "offer", "rejected", "saved"]
        for i, status in enumerate(statuses):
            record = make_record(str(i), f"Software Engineer Intern {i}")
            row = repo.insert_job(session, record, alias_hashes(record))
            app = repo.set_application_status(session, row.id, status)
            app.resume_variant = "backend" if i % 2 else "ml"
            app.applied_at = row.first_seen_at + timedelta(hours=6 if i < 3 else 100)
        dims = collect(session)
    reset_engine()
    overall = dims["Overall"]["all"]
    assert overall.applied == 5  # "saved" is not an application
    assert overall.responded == 3 and overall.interviewed == 2 and overall.offers == 1
    assert dims["Company tier"]["core"].applied == 5
    assert dims["Applied after first seen"]["within 1 day"].applied == 3
    assert set(dims["Resume version"]) == {"backend", "ml"}
    text = render(dims, today=date(2026, 10, 8))
    assert "*too early*" in text and MIN_SAMPLE > 5
    assert "| all | 5 | 3 | 60%" in text


def test_render_without_applications_explains_how_to_start():
    text = render({}, today=date(2026, 10, 8))
    assert "No applications logged yet" in text
    assert "jobs status" in text


def test_tailored_resume_adds_project_and_panel_breakdowns(tmp_path):
    import json

    from opportunity_radar.resume.paths import private_dir

    folder = private_dir() / "tailored" / "2026-10-08-stripe-backend"
    folder.mkdir(parents=True)
    (folder / "meta.json").write_text(
        json.dumps(
            {
                "projects": ["Repolix", "OS Kernel"],
                "panel": {"recruiter": "yes", "hiring_manager": "maybe"},
            }
        )
    )
    reset_engine()
    url = f"sqlite:///{tmp_path}/outcomes.db"
    Base.metadata.create_all(get_engine(url))
    with session_scope(url) as session:
        repo.sync_companies(session, [CompanySource(id="stripe", name="Stripe", tier="core")])
        for i, (status, variant) in enumerate(
            [("oa", "2026-10-08-stripe-backend"), ("rejected", "master")]
        ):
            record = make_record(str(i), f"Backend Intern {i}")
            row = repo.insert_job(session, record, alias_hashes(record))
            repo.set_application_status(session, row.id, status).resume_variant = variant
        dims = collect(session)
    reset_engine()
    assert dims["Project shown"]["Repolix"].responded == 1
    assert dims["Panel: recruiter advance"]["yes"].applied == 1
    assert dims["Panel: manager interview"]["maybe"].responded == 1
    assert "master" not in dims["Project shown"]
